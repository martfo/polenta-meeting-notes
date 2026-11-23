"""How much space the library takes, what takes it, and how fast it grows,
for the Storage section in Settings. Sizes are read from disk each time, so
the figures are always current; walking the vault is quick (a few thousand
files)."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meetingnotes.storage.vault import Vault


def _tree_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _is_recording(name: str) -> bool:
    return name.endswith(".wav") or name.endswith(".wav.orig")


def library_usage(
    conn: sqlite3.Connection, vault: Vault, now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    recordings = notes_and_text = 0
    per_meeting: dict[str, int] = {}
    if vault.meetings_dir.is_dir():
        for meeting_dir in vault.meetings_dir.iterdir():
            if not meeting_dir.is_dir():
                continue
            for root, _dirs, files in os.walk(meeting_dir):
                for name in files:
                    try:
                        size = os.lstat(os.path.join(root, name)).st_size
                    except OSError:
                        continue
                    if _is_recording(name) and Path(root) == meeting_dir:
                        recordings += size
                        per_meeting[meeting_dir.name] = per_meeting.get(meeting_dir.name, 0) + size
                    else:
                        notes_and_text += size
    captures = _tree_bytes(vault.captures_dir) if vault.captures_dir.is_dir() else 0
    search_index = _tree_bytes(vault.lancedb_dir) if vault.lancedb_dir.is_dir() else 0
    total = _tree_bytes(vault.root)
    other = max(total - recordings - notes_and_text - captures - search_index, 0)

    # Growth: the audio recorded in the last 30 days that is still here.
    cutoff = now - timedelta(days=30)
    recent_bytes = 0
    recent_hours = 0.0
    for row in conn.execute("SELECT id, started_at, duration_s FROM meetings"):
        started = datetime.fromisoformat(row["started_at"])
        started = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
        if started >= cutoff:
            recent_bytes += per_meeting.get(row["id"], 0)
            if per_meeting.get(row["id"]):
                recent_hours += (row["duration_s"] or 0) / 3600

    disk = shutil.disk_usage(vault.root)
    return {
        "total_bytes": total,
        "parts": {
            "recordings": recordings,
            "captures": captures,
            "notes_and_transcripts": notes_and_text,
            "search_index": search_index,
            "other": other,
        },
        "meetings": conn.execute("SELECT COUNT(*) FROM meetings").fetchone()[0],
        "meetings_with_audio": len(per_meeting),
        "last_30_days": {"bytes": recent_bytes, "hours": round(recent_hours, 1)},
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
    }
