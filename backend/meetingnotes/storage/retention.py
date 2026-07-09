"""Audio retention: audio.wav is purged after the configured number of days.
The transcript, summary, and notes are always kept. The clock is injected so
the tests can age meetings."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from meetingnotes.config import Config
from meetingnotes.storage.vault import Vault

SETTINGS_KEY = "audio_retention_days"


def retention_days(config: Config, conn: sqlite3.Connection) -> int:
    """The period comes from config.json; a value changed in the settings
    table takes precedence, so both places work."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)).fetchone()
    if row is not None:
        return int(row["value"])
    return config.audio_retention_days


def set_retention_days(conn: sqlite3.Connection, days: int) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SETTINGS_KEY, str(days)),
    )
    conn.commit()


def purge_old_audio(
    conn: sqlite3.Connection, vault: Vault, days: int,
    now: datetime | None = None,
) -> list[str]:
    """Remove audio.wav from meetings older than the period. Returns the
    meeting ids purged."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    purged = []
    for row in conn.execute("SELECT id, started_at FROM meetings").fetchall():
        started = datetime.fromisoformat(row["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        meeting_dir = vault.meeting_dir(row["id"])
        audio_files = [vault.audio_path(row["id"]), meeting_dir / "mic.wav", meeting_dir / "system.wav"]
        if started < cutoff and any(f.exists() for f in audio_files):
            for f in audio_files:
                f.unlink(missing_ok=True)
            purged.append(row["id"])
    return purged
