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


def test_import_rejects_empty_audio(conn, vault, tmp_path):
    """An empty capture file is never imported, so a failed recording start
    leaves no 0-byte meeting behind."""
    import pytest

    empty = tmp_path / "capture-empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        import_wav(conn, vault, empty)
    assert conn.execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 0


def test_import_converts_non_16k_audio_to_vault_format(conn, vault, tmp_path):
    """An imported file that is not already 16 kHz mono PCM (an mp3, or here a
    48 kHz stereo WAV standing in for one) is converted, so the vault always
    holds 16 kHz mono PCM and the normal single-channel pipeline runs."""
    import math
    import struct
    import wave

    src = tmp_path / "clip.wav"
    rate = 48_000
    with wave.open(str(src), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(rate):  # one second, stereo
            v = int(0.3 * math.sin(2 * math.pi * 220 * i / rate) * 32767)
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))

    meeting_id = import_wav(conn, vault, src, title="Imported clip", source="imported")

    with wave.open(str(vault.audio_path(meeting_id)), "rb") as out:
        assert out.getframerate() == 16_000
        assert out.getnchannels() == 1
        assert out.getsampwidth() == 2
        assert out.getnframes() > 0
    assert m.get_meeting(conn, meeting_id)["source"] == "imported"
    job = conn.execute(
        "SELECT stage FROM processing_jobs WHERE meeting_id = ?", (meeting_id,)).fetchone()
    assert job["stage"] == "transcribe"


def _tiny_wav(path):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x64\x00" * 16_000)  # 1 second of quiet tone


def test_imported_file_uses_the_date_in_its_name(conn, vault, tmp_path):
    """An imported recording named for when it was made files under that day
    and time, not the moment of import."""
    src = tmp_path / "2026-08-19 14-30-00.wav"
    _tiny_wav(src)
    meeting_id = import_wav(conn, vault, src, source="imported")
    assert meeting_id.startswith("2026-08-19_1430")
    assert m.get_meeting(conn, meeting_id)["started_at"].startswith("2026-08-19T14:30")


def test_capture_ignores_a_date_in_the_filename(conn, vault, tmp_path):
    """The filename date is only for imports; a captured recording (a different
    source) keeps its real time even if its staging file happens to be dated."""
    src = tmp_path / "2020-01-01 00-00-00.wav"
    _tiny_wav(src)
    meeting_id = import_wav(conn, vault, src, source="online")
    assert not meeting_id.startswith("2020-01-01")


def test_purge_empty_recordings(conn, vault, fixtures_dir):
    """The startup sweep removes meetings that captured nothing and keeps
    real ones."""
    from meetingnotes.storage import meetings as m
    from meetingnotes.storage.cleanup import purge_empty_recordings

    good = import_wav(conn, vault, fixtures_dir / "audio" / "two_speaker_meeting.wav", title="Real")

    # A junk meeting as an old app version would have left it: a row, a
    # folder, a 0-byte audio file, no transcript.
    junk = "2026-07-04_0900_aborted"
    vault.meeting_dir(junk).mkdir(parents=True)
    vault.audio_path(junk).write_bytes(b"")
    m.create_meeting(conn, junk, title="aborted", started_at="2026-07-04T09:00:00+00:00",
                     vault_path=str(vault.meeting_dir(junk)), processing_status="failed")

    removed = purge_empty_recordings(conn, vault)

    assert removed == [junk]
    assert not vault.meeting_dir(junk).exists()
    assert m.get_meeting(conn, good)["id"] == good, "the real meeting is untouched"
    assert vault.audio_path(good).exists()


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
