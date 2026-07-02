"""Section 1.0: worker behaviour against a fake fast pipeline. Integration tier."""

from meetingnotes.jobs import queue as q
from meetingnotes.jobs.importer import import_wav
from meetingnotes.jobs.worker import Worker, retry_meeting
from meetingnotes.llm.errors import LMStudioUnavailable
from meetingnotes.storage import meetings as m
from meetingnotes.storage.db import open_db


def _import(conn, vault, fixtures_dir, title):
    wav = fixtures_dir / "audio" / "two_speaker_meeting.wav"
    return import_wav(conn, vault, wav, title=title)


def test_ac_1_0_b_two_meetings_in_order(conn, vault, stages, fixtures_dir):
    """Two meetings enqueued back to back are both processed to completion,
    in order."""
    a = _import(conn, vault, fixtures_dir, "Meeting A")
    b = _import(conn, vault, fixtures_dir, "Meeting B")

    Worker(conn, stages).run_pending()

    assert m.get_meeting(conn, a)["processing_status"] == "ready"
    assert m.get_meeting(conn, b)["processing_status"] == "ready"
    transcribed = [mid for stage, mid in stages.calls if stage == "transcribe"]
    assert transcribed == [a, b], "first in, first out"
    # A finished every stage before B started any.
    order = [mid for _, mid in stages.calls]
    assert order.index(b) > max(i for i, mid in enumerate(order) if mid == a)


def test_ac_1_0_c_second_recording_while_processing(conn, vault, stages, fixtures_dir):
    """Starting a second recording while the first is processing neither
    blocks nor drops either meeting."""
    a = _import(conn, vault, fixtures_dir, "Meeting A")
    worker = Worker(conn, stages)
    job_a = q.claim_next(conn)  # A is mid-processing
    assert job_a.meeting_id == a

    b = _import(conn, vault, fixtures_dir, "Meeting B")  # accepted at once
    assert q.jobs_for_meeting(conn, b)[0].status == "queued"

    worker.run_job(job_a)
    worker.run_pending()
    assert m.get_meeting(conn, a)["processing_status"] == "ready"
    assert m.get_meeting(conn, b)["processing_status"] == "ready"


def test_ac_1_0_d_queue_persists_across_restart(conn, vault, stages, fixtures_dir):
    """The queue is rows in SQLite: after a simulated restart, queued and
    interrupted jobs resume and finish."""
    a = _import(conn, vault, fixtures_dir, "Interrupted")
    b = _import(conn, vault, fixtures_dir, "Queued behind")

    # The worker claims A and dies mid-run: the job is left 'running'.
    claimed = q.claim_next(conn)
    assert claimed.meeting_id == a
    conn.close()

    # Restart: a fresh connection, reset of interrupted jobs, a fresh worker.
    conn2 = open_db(vault.db_path)
    try:
        worker = Worker(conn2, stages)
        q.reset_interrupted(conn2)
        worker.run_pending()
        assert m.get_meeting(conn2, a)["processing_status"] == "ready"
        assert m.get_meeting(conn2, b)["processing_status"] == "ready"
        assert all(j.status == "done" for mid in (a, b) for j in q.jobs_for_meeting(conn2, mid))
    finally:
        conn2.close()


def test_ac_1_0_e_lmstudio_down_partial_completion(conn, vault, stages, fixtures_dir):
    """With LM Studio unavailable a meeting still completes transcription and
    diarisation and is left summary pending; the summary succeeds on retry
    once LM Studio is back."""
    meeting_id = _import(conn, vault, fixtures_dir, "Summary later")

    lmstudio_up = False

    def summarise(mid: str) -> None:
        if not lmstudio_up:
            raise LMStudioUnavailable("connection refused on 127.0.0.1:1234")
        m.set_summary_status(conn, mid, "ready")

    stages["summarise"] = summarise
    worker = Worker(conn, stages)
    worker.run_pending()

    row = m.get_meeting(conn, meeting_id)
    assert [s for s, _ in stages.calls] == ["transcribe", "diarise", "enrich", "embed"]
    assert row["processing_status"] == "ready", "usable without the summary"
    assert row["summary_status"] == "pending"
    assert row["last_error"] is None, "LM Studio being down is not a failure"

    lmstudio_up = True
    retry_meeting(conn, meeting_id)
    worker.run_pending()

    row = m.get_meeting(conn, meeting_id)
    assert row["summary_status"] == "ready"
    assert row["processing_status"] == "ready"
    # The retry re-ran only the summary stage, not the whole pipeline.
    assert [s for s, _ in stages.calls].count("transcribe") == 1
