"""Remove junk meetings left by failed recording starts.

A recording whose audio tap failed to start used to be handed to the backend
as an empty WAV, which produced a meeting with a 0-byte audio file and no
transcript. The app no longer creates these, and this sweep clears any that a
previous version left behind. It runs once at backend startup and only ever
removes meetings that captured nothing.
"""

from __future__ import annotations

import shutil
import sqlite3

from meetingnotes.storage.vault import Vault


def purge_empty_recordings(conn: sqlite3.Connection, vault: Vault) -> list[str]:
    """Delete meetings whose audio file is empty or missing and that never
    produced a transcript. Returns the meeting ids removed."""
    removed: list[str] = []
    for row in conn.execute("SELECT id FROM meetings").fetchall():
        meeting_id = row["id"]
        audio = vault.audio_path(meeting_id)
        transcript = vault.transcript_path(meeting_id)
        audio_empty = (not audio.exists()) or audio.stat().st_size == 0
        if audio_empty and not transcript.exists():
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            shutil.rmtree(vault.meeting_dir(meeting_id), ignore_errors=True)
            removed.append(meeting_id)
    if removed:
        conn.commit()
    return removed
