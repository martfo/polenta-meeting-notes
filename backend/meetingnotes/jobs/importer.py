"""Audio import: the permanent way to bring an existing WAV into the app, and
how the pipeline is tested. Import writes the audio into the vault, creates
the meeting row, enqueues processing, and returns at once. Capture does
exactly the same on Stop, so both paths produce the same downstream job.

A live recording also has a placeholder: the meeting is created when
recording starts (status "recording"), so notes, links and screenshots can go
into it during the call, and Stop attaches the audio to that same meeting."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import wave
from datetime import datetime
from pathlib import Path

from meetingnotes.jobs import queue as q
from meetingnotes.jobs.filename_date import datetime_from_filename
from meetingnotes.notes.notes import read_notes
from meetingnotes.pipeline.audio_io import ensure_16k_mono_wav
from meetingnotes.storage import meetings as m
from meetingnotes.storage.captures import release_capture
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
    meeting_id: str | None = None,
) -> str:
    """Copy the WAV into a new meeting folder, create the row, enqueue a job.

    With meeting_id, the audio belongs to that recording's placeholder and is
    attached to it, keeping the notes and title it gathered during the call.
    If the placeholder is gone (deleted mid-recording), a new meeting is
    created instead, so the audio is never lost.

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
    if meeting_id is not None and _is_placeholder(conn, meeting_id):
        return _attach_audio(conn, vault, meeting_id, wav_path, source,
                             expected_speakers, mic_path, system_path)
    title = title or wav_path.stem.replace("_", " ").replace("-", " ").strip() or "Imported meeting"
    # An imported recording is usually named for when it was made, so read the
    # date from the filename and file the meeting under that day rather than the
    # moment of import. Captures pass their own started_at and are untouched.
    if started_at is None and source == "imported":
        started_at = datetime_from_filename(wav_path.stem)
    started_at = started_at or datetime.now().astimezone()

    meeting_id = vault.new_meeting_id(started_at, title)
    meeting_dir = vault.meeting_dir(meeting_id)
    meeting_dir.mkdir(parents=True)
    # Store the audio correctly whatever the source format (an imported mp3, a
    # WAV at another rate): the vault always holds 16 kHz mono PCM. A captured
    # recording already is that, so this is just a copy.
    try:
        ensure_16k_mono_wav(wav_path, vault.audio_path(meeting_id))
    except (subprocess.CalledProcessError, OSError) as exc:
        shutil.rmtree(meeting_dir, ignore_errors=True)
        raise ValueError(f"could not read the audio file '{wav_path.name}'") from exc
    _copy_channels(meeting_dir, mic_path, system_path)

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
    _release_captures(vault, meeting_id, wav_path, mic_path, system_path)
    return meeting_id


def _copy_channels(meeting_dir: Path, mic_path, system_path) -> None:
    if mic_path and system_path:
        mic_path, system_path = Path(mic_path), Path(system_path)
        if mic_path.exists() and system_path.exists():
            shutil.copyfile(mic_path, meeting_dir / "mic.wav")
            shutil.copyfile(system_path, meeting_dir / "system.wav")


def _is_placeholder(conn: sqlite3.Connection, meeting_id: str) -> bool:
    row = conn.execute(
        "SELECT processing_status FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    return row is not None and row["processing_status"] == "recording"


def begin_recording(
    conn: sqlite3.Connection,
    vault: Vault,
    title: str,
    source: str = "online",
    started_at: datetime | None = None,
) -> str:
    """Create the placeholder for a recording that has just started: a meeting
    folder with no audio yet, status "recording". Returns its id."""
    started_at = started_at or datetime.now().astimezone()
    meeting_id = vault.new_meeting_id(started_at, title)
    meeting_dir = vault.meeting_dir(meeting_id)
    meeting_dir.mkdir(parents=True)
    m.create_meeting(
        conn, meeting_id, title=title,
        started_at=started_at.isoformat(timespec="seconds"),
        vault_path=str(meeting_dir), source=source, processing_status="recording",
    )
    return meeting_id


def _attach_audio(conn, vault, meeting_id, wav_path, source, expected_speakers,
                  mic_path, system_path) -> str:
    meeting_dir = vault.meeting_dir(meeting_id)
    meeting_dir.mkdir(parents=True, exist_ok=True)
    try:
        ensure_16k_mono_wav(wav_path, vault.audio_path(meeting_id))
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ValueError(f"could not read the audio file '{wav_path.name}'") from exc
    _copy_channels(meeting_dir, mic_path, system_path)
    conn.execute(
        """UPDATE meetings SET processing_status = 'queued', source = ?, duration_s = ?,
               expected_speakers = COALESCE(?, expected_speakers) WHERE id = ?""",
        (source, wav_duration_s(vault.audio_path(meeting_id)), expected_speakers, meeting_id),
    )
    conn.commit()
    q.enqueue(conn, meeting_id, stage="transcribe")
    _release_captures(vault, meeting_id, wav_path, mic_path, system_path)
    return meeting_id


def _release_captures(vault: Vault, meeting_id: str, wav_path, mic_path, system_path) -> None:
    """The meeting now holds the audio and its job is queued, so the app's raw
    captures are duplicates: remove each one whose copy is identical."""
    meeting_dir = vault.meeting_dir(meeting_id)
    release_capture(vault, wav_path, vault.audio_path(meeting_id))
    release_capture(vault, mic_path, meeting_dir / "mic.wav")
    release_capture(vault, system_path, meeting_dir / "system.wav")


def has_notes(vault: Vault, meeting_id: str) -> bool:
    """Anything the person wrote or pasted into the meeting."""
    assets = vault.assets_dir(meeting_id)
    return bool(read_notes(vault, meeting_id).strip()) or (
        assets.exists() and any(assets.iterdir()))


NO_AUDIO_MESSAGE = "The recording captured no audio. Your notes are kept."


def settle_recording(conn: sqlite3.Connection, vault: Vault, meeting_id: str) -> str:
    """A placeholder whose recording ended without audio (it captured nothing,
    or the app quit mid-call). With notes it is kept and marked failed, so
    nothing written is lost; without, it is removed. Returns "kept",
    "removed", or "unchanged" when it is not a placeholder."""
    if not _is_placeholder(conn, meeting_id):
        return "unchanged"
    if has_notes(vault, meeting_id):
        m.record_failure(conn, meeting_id, "record", NO_AUDIO_MESSAGE)
        return "kept"
    conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
    conn.commit()
    shutil.rmtree(vault.meeting_dir(meeting_id), ignore_errors=True)
    return "removed"


def settle_stale_recordings(
    conn: sqlite3.Connection, vault: Vault, keep: list[str],
) -> list[str]:
    """Settle every placeholder except those in keep (recordings whose audio is
    still waiting to be handed over). Called by the app when it is not
    recording, so a placeholder left by a crash does not stay "recording"."""
    rows = conn.execute(
        "SELECT id FROM meetings WHERE processing_status = 'recording'").fetchall()
    settled = []
    for row in rows:
        if row["id"] not in keep:
            settle_recording(conn, vault, row["id"])
            settled.append(row["id"])
    return settled
