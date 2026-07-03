"""Cross-cutting: readable logs that never carry meeting content, and the
failed-stage record with Retry."""

import json
import logging
import re

from meetingnotes.jobs import queue as q
from meetingnotes.jobs.importer import import_wav
from meetingnotes.jobs.worker import Worker, retry_meeting
from meetingnotes.logging.setup import JSON_LOG_NAME, LOG_NAME, configure_logging
from meetingnotes.storage import meetings as m

LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2} "
    r"(INFO|WARNING|ERROR) \[meeting 2026-07-02_1400_client-review, stage transcribe\] .+$"
)


def test_ac_x_h_log_line_format(tmp_path):
    """A line reads at a glance: ISO timestamp, level, meeting id and stage
    where relevant, and a plain message. The JSON companion record parses."""
    logs = tmp_path / "logs"
    configure_logging(logs)
    logging.getLogger("meetingnotes.test").info(
        "stage started",
        extra={"meeting_id": "2026-07-02_1400_client-review", "stage": "transcribe"},
    )

    human_line = (logs / LOG_NAME).read_text().strip()
    assert LINE.match(human_line), human_line

    record = json.loads((logs / JSON_LOG_NAME).read_text().strip())
    assert record["level"] == "INFO"
    assert record["meeting_id"] == "2026-07-02_1400_client-review"
    assert record["stage"] == "transcribe"
    assert record["message"] == "stage started"


def test_ac_x_i_logs_never_contain_content(tmp_path, conn, vault, stages, fixtures_dir):
    """A stage error with transcript content close at hand leaves no content
    in either log file."""
    logs = tmp_path / "logs"
    configure_logging(logs)
    marker = "SECRET TRANSCRIPT SENTENCE about the hydroponics budget"

    meeting_id = import_wav(conn, vault, fixtures_dir / "audio" / "two_speaker_meeting.wav")

    def leaky_transcribe(mid: str) -> None:
        raise RuntimeError(f"parser choked near: {marker}")

    stages["transcribe"] = leaky_transcribe
    Worker(conn, stages).run_pending()

    for name in (LOG_NAME, JSON_LOG_NAME):
        content = (logs / name).read_text()
        assert marker not in content, f"{name} leaked meeting content"
        assert meeting_id in content, "identifiers are fine and expected"


def test_ac_x_j_failed_stage_error_and_retry(conn, vault, stages, fixtures_dir):
    """A failed stage stores a plain-language last_error and the failing
    stage on the meeting, and Retry re-enqueues from that stage."""
    meeting_id = import_wav(conn, vault, fixtures_dir / "audio" / "two_speaker_meeting.wav")

    calls = []
    broken = True

    def flaky_enrich(mid: str) -> None:
        calls.append(mid)
        if broken:
            raise RuntimeError("speaker embedding model not cached yet")

    stages["enrich"] = flaky_enrich
    worker = Worker(conn, stages)
    worker.run_pending()

    row = m.get_meeting(conn, meeting_id)
    assert row["processing_status"] == "failed"
    assert row["failed_stage"] == "enrich"
    assert "speaker embedding model not cached yet" in row["last_error"]

    broken = False
    job_id = retry_meeting(conn, meeting_id)
    assert q.get_job(conn, job_id).stage == "enrich", "resume from the failed stage"

    worker.run_pending()
    row = m.get_meeting(conn, meeting_id)
    assert row["processing_status"] == "ready"
    assert row["last_error"] is None and row["failed_stage"] is None
    # transcribe ran once; enrich ran twice (the failure and the retry).
    assert [s for s, _ in stages.calls].count("transcribe") == 1
    assert len(calls) == 2
