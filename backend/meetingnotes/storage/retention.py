"""Audio retention: how long a meeting's recordings stay in the library.

Audio is only needed to process a meeting again. The transcript, summary,
notes, screenshots, speakers and search index never depend on it, so they
are always kept. The default is to keep audio forever; the person chooses a
period in Settings, and whether expired audio is deleted or moved to a folder
of their choosing (an external drive, say).

Only settled meetings lose their audio: one still processing, failed, or
needing attention keeps it, so it can be retried. Moving never falls back to
deleting: if the chosen folder is unavailable, nothing happens until it is.
The clock is injected so the tests can age meetings."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meetingnotes.storage.vault import Vault

log = logging.getLogger("meetingnotes.retention")

KEEP_DAYS_KEY = "audio_keep_days"
ARCHIVE_DIR_KEY = "audio_archive_dir"

# Only meetings in these states give up their audio; anything else may still
# need it to finish or to be retried.
SETTLED_STATUSES = ("ready", "needs_attention")


@dataclass(frozen=True)
class RetentionPolicy:
    # None keeps audio forever.
    keep_days: int | None = None
    # None deletes expired audio; a folder receives it instead.
    archive_dir: str | None = None


def audio_files(vault: Vault, meeting_id: str) -> list[Path]:
    """Every recording file in a meeting: the mixed track, the two channels,
    and any .orig kept by an audio repair."""
    d = vault.meeting_dir(meeting_id)
    if not d.is_dir():
        return []
    return sorted([*d.glob("*.wav"), *d.glob("*.wav.orig")])


def _read(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def _write(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_policy(conn: sqlite3.Connection) -> RetentionPolicy:
    days = _read(conn, KEEP_DAYS_KEY)
    return RetentionPolicy(
        keep_days=int(days) if days else None,
        archive_dir=_read(conn, ARCHIVE_DIR_KEY) or None,
    )


def validate_policy(vault: Vault, policy: RetentionPolicy) -> str | None:
    """A plain reason the policy cannot be used, or None when it can."""
    if policy.keep_days is not None and policy.keep_days < 1:
        return "The period must be at least one day."
    if policy.archive_dir is not None:
        folder = Path(policy.archive_dir).expanduser()
        if not folder.is_absolute():
            return "Choose a folder for the recordings."
        try:
            folder.resolve().relative_to(vault.root.resolve())
            return "Choose a folder outside the library, or nothing is saved."
        except ValueError:
            pass
    return None


def set_policy(conn: sqlite3.Connection, policy: RetentionPolicy) -> None:
    _write(conn, KEEP_DAYS_KEY, str(policy.keep_days) if policy.keep_days else None)
    _write(conn, ARCHIVE_DIR_KEY, policy.archive_dir)
    conn.commit()


def _started(value: str) -> datetime:
    started = datetime.fromisoformat(value)
    return started if started.tzinfo else started.replace(tzinfo=timezone.utc)


@dataclass
class Expired:
    meeting_id: str
    files: list[Path]
    bytes: int
    duration_s: int


def expired_audio(
    conn: sqlite3.Connection, vault: Vault, keep_days: int | None,
    now: datetime | None = None,
) -> list[Expired]:
    """The meetings whose audio is older than keep_days and may go."""
    if keep_days is None:
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    busy = {r["meeting_id"] for r in conn.execute(
        "SELECT meeting_id FROM processing_jobs WHERE status IN ('queued', 'running')")}
    placeholders = ",".join("?" * len(SETTLED_STATUSES))
    rows = conn.execute(
        f"SELECT id, started_at, duration_s FROM meetings "
        f"WHERE processing_status IN ({placeholders}) ORDER BY started_at",
        SETTLED_STATUSES).fetchall()
    found = []
    for row in rows:
        if row["id"] in busy or _started(row["started_at"]) >= cutoff:
            continue
        files = audio_files(vault, row["id"])
        if files:
            found.append(Expired(row["id"], files, sum(f.stat().st_size for f in files),
                                 row["duration_s"] or 0))
    return found


def preview(
    conn: sqlite3.Connection, vault: Vault, keep_days: int | None,
    now: datetime | None = None,
) -> dict:
    """What a policy would do now, shown to the person before it is saved."""
    now = now or datetime.now(timezone.utc)
    found = expired_audio(conn, vault, keep_days, now)
    return {
        "meetings": len(found),
        "hours": round(sum(e.duration_s for e in found) / 3600, 1),
        "bytes": sum(e.bytes for e in found),
        "before": (now - timedelta(days=keep_days)).isoformat(timespec="seconds")
        if keep_days else None,
    }


@dataclass
class RetentionRun:
    meetings: list[str] = field(default_factory=list)
    bytes: int = 0
    # Why nothing could be done, such as an unplugged archive drive.
    problem: str | None = None


def _move(source: Path, dest_dir: Path) -> None:
    """Move one file into dest_dir, then check the copy before the original
    is gone. A file already there and identical is simply the source's twin."""
    dest = dest_dir / source.name
    if dest.exists():
        if dest.stat().st_size == source.stat().st_size:
            source.unlink()
            return
        raise OSError(f"a different {source.name} is already in {dest_dir}")
    partial = dest_dir / (source.name + ".partial")
    shutil.copy2(source, partial)
    if partial.stat().st_size != source.stat().st_size:
        partial.unlink(missing_ok=True)
        raise OSError(f"the copy of {source.name} is incomplete")
    os.replace(partial, dest)
    source.unlink()


_lock = threading.Lock()

# The most recent run, for the Storage section: when, and any problem.
last_run: dict = {"at": None, "problem": None}


def apply_retention(
    conn: sqlite3.Connection, vault: Vault, policy: RetentionPolicy,
    now: datetime | None = None,
) -> RetentionRun:
    """Delete or move the audio of every expired meeting. Safe to call on a
    timer: a run already in progress makes this one a no-op."""
    run = RetentionRun()
    if policy.keep_days is None:
        return run
    if not _lock.acquire(blocking=False):
        return run
    try:
        archive = Path(policy.archive_dir).expanduser() if policy.archive_dir else None
        if archive is not None and not (archive.is_dir() and os.access(archive, os.W_OK)):
            run.problem = (f"The folder for old recordings, {archive}, is not available "
                           "(is the drive connected?). Nothing was moved or deleted.")
            last_run.update(at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            problem=run.problem)
            return run
        now = now or datetime.now(timezone.utc)
        for item in expired_audio(conn, vault, policy.keep_days, now):
            try:
                if archive is None:
                    for f in item.files:
                        f.unlink(missing_ok=True)
                    dest = None
                else:
                    dest = archive / item.meeting_id
                    dest.mkdir(parents=True, exist_ok=True)
                    for f in item.files:
                        _move(f, dest)
            except OSError as exc:
                log.warning("old audio could not be %s: %s",
                            "deleted" if archive is None else "moved", exc,
                            extra={"meeting_id": item.meeting_id})
                if archive is not None:
                    run.problem = f"Some recordings could not be moved: {exc}"
                    break
                continue
            conn.execute(
                "UPDATE meetings SET audio_removed_at = ?, audio_archive_path = ? WHERE id = ?",
                (now.isoformat(timespec="seconds"), str(dest) if dest else None,
                 item.meeting_id))
            conn.commit()
            run.meetings.append(item.meeting_id)
            run.bytes += item.bytes
        last_run.update(at=now.isoformat(timespec="seconds"), problem=run.problem)
        if run.meetings:
            log.info("old audio %s for %d meetings",
                     "deleted" if archive is None else "moved", len(run.meetings))
        return run
    finally:
        _lock.release()
