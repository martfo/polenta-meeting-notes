"""Audio import: the permanent way to bring an existing WAV into the app, and
how the pipeline is tested. Import writes the audio into the vault, creates
the meeting row, enqueues processing, and returns at once. Capture does
exactly the same on Stop, so both paths produce the same downstream job."""

from __future__ import annotations

import shutil
import sqlite3
import wave
from datetime import datetime
from pathlib import Path

from meetingnotes.jobs import queue as q
from meetingnotes.storage import meetings as m
from meetingnotes.storage.vault import Vault


def wav_duration_s(path: Path) -> int:
    with wave.open(str(path), "rb") as w:
        return round(w.getnframes() / w.getframerate())


def import_wav(
    conn: sqlite3.Connection,
    vault: Vault,
    wav_path: Path | str,
    title: str | None = None,
    started_at: datetime | None = None,
    source: str = "online",
    expected_speakers: int | None = None,
    mic_path: Path | str | None = None,
    system_path: Path | str | None = None,
) -> str:
    """Copy the WAV into a new meeting folder, create the row, enqueue a job.

    When mic_path and system_path are given, the recording was captured as two
    channels (the owner on the microphone, the remote participants on the
    system audio); both are stored so the pipeline can transcribe them
    separately. The mixed wav_path is kept for playback.

    Returns the meeting id without waiting for any processing.
    """
    wav_path = Path(wav_path)
    # A 16 kHz mono PCM header is 44 bytes; at or below that the file carries
    # no audio, so it is never imported as a meeting.
    if not wav_path.exists() or wav_path.stat().st_size <= 44:
        raise ValueError("cannot import an empty or missing audio file")
    title = title or wav_path.stem.replace("_", " ").replace("-", " ").strip() or "Imported meeting"
    started_at = started_at or datetime.now().astimezone()

    meeting_id = vault.new_meeting_id(started_at, title)
    meeting_dir = vault.meeting_dir(meeting_id)
    meeting_dir.mkdir(parents=True)
    shutil.copyfile(wav_path, vault.audio_path(meeting_id))
    if mic_path and system_path:
        mic_path, system_path = Path(mic_path), Path(system_path)
        if mic_path.exists() and system_path.exists():
            shutil.copyfile(mic_path, meeting_dir / "mic.wav")
            shutil.copyfile(system_path, meeting_dir / "system.wav")

    m.create_meeting(
        conn,
        meeting_id,
        title=title,
        started_at=started_at.isoformat(timespec="seconds"),
        vault_path=str(meeting_dir),
        source=source,
        duration_s=wav_duration_s(vault.audio_path(meeting_id)),
        expected_speakers=expected_speakers,
    )
    q.enqueue(conn, meeting_id, stage="transcribe")
    return meeting_id
