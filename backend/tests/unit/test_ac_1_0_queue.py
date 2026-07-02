"""Section 1.0: import, the processing queue, and concurrency. Unit tier."""

from meetingnotes.jobs import queue as q
from meetingnotes.jobs.importer import import_wav
from meetingnotes.jobs.worker import Worker
from meetingnotes.storage import meetings as m


def test_ac_1_0_a_enqueue_returns_before_processing(conn, vault, stages, fixtures_dir):
    """Importing creates the meeting row, enqueues a job, and returns without
    waiting for processing: the job is still queued and no stage has run."""
    meeting_id = import_wav(conn, vault, fixtures_dir / "audio" / "two_speaker_meeting.wav")

    row = m.get_meeting(conn, meeting_id)
    assert row["processing_status"] == "queued"
    jobs = q.jobs_for_meeting(conn, meeting_id)
    assert len(jobs) == 1 and jobs[0].status == "queued"
    assert stages.calls == [], "no stage may run until the worker is asked to"


def test_ac_1_0_g_stage_status_updates_and_failure_moves_on(conn, vault, stages, fixtures_dir):
    """Each stage updates processing_status; a failed stage records the error,
    sets failed, and the worker continues to the next job."""
    wav = fixtures_dir / "audio" / "two_speaker_meeting.wav"
    failing = import_wav(conn, vault, wav, title="Fails")
    healthy = import_wav(conn, vault, wav, title="Succeeds")

    statuses_seen: list[str] = []

    def observing_enrich(meeting_id: str) -> None:
        statuses_seen.append(m.get_meeting(conn, meeting_id)["processing_status"])

    def failing_diarise(meeting_id: str) -> None:
        if meeting_id == failing:
            raise RuntimeError("diarisation model missing")

    stages["enrich"] = observing_enrich
    stages["diarise"] = failing_diarise

    Worker(conn, stages).run_pending()

    failed = m.get_meeting(conn, failing)
    assert failed["processing_status"] == "failed"
    assert failed["failed_stage"] == "diarise"
    assert "diarisation model missing" in failed["last_error"]
    assert q.jobs_for_meeting(conn, failing)[0].status == "failed"

    # The worker moved on: the healthy meeting ran every stage, and while its
    # enrich stage ran the meeting showed the matching in-progress status.
    assert m.get_meeting(conn, healthy)["processing_status"] == "ready"
    assert statuses_seen == ["enriching"]


def test_ac_1_0_h_import_wav_enqueues_same_job(conn, vault, fixtures_dir):
    """Importing a WAV produces the same downstream job as capture: a queued
    transcribe job for a meeting whose audio sits in the vault."""
    src = fixtures_dir / "audio" / "two_speaker_meeting.wav"
    meeting_id = import_wav(conn, vault, src, title="Imported")

    audio = vault.audio_path(meeting_id)
    assert audio.exists() and audio.stat().st_size == src.stat().st_size
    job = q.jobs_for_meeting(conn, meeting_id)[0]
    assert (job.stage, job.status) == ("transcribe", "queued")
    assert m.get_meeting(conn, meeting_id)["duration_s"] == 27
