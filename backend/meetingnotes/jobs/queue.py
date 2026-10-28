"""The persisted processing queue, backed by the processing_jobs table.

Capture and import enqueue and return at once. A single worker claims jobs
first in, first out. Because the queue is rows in SQLite, an app or backend
restart resumes pending and interrupted jobs and never loses a recording.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from meetingnotes.storage.db import utcnow

STAGES = ["transcribe", "diarise", "enrich", "embed", "summarise"]


@dataclass
class Job:
    id: int
    meeting_id: str
    stage: str
    status: str
    attempts: int


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"], meeting_id=row["meeting_id"], stage=row["stage"],
        status=row["status"], attempts=row["attempts"],
    )


def enqueue(conn: sqlite3.Connection, meeting_id: str, stage: str = "transcribe") -> int:
    assert stage in STAGES, stage
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO processing_jobs(meeting_id, stage, status, created_at, updated_at)
           VALUES (?, ?, 'queued', ?, ?)""",
        (meeting_id, stage, now, now),
    )
    conn.commit()
    return cur.lastrowid


def claim_next(conn: sqlite3.Connection) -> Job | None:
    """Mark the oldest queued job running and return it. First in, first out."""
    row = conn.execute(
        "SELECT * FROM processing_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE processing_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
        (utcnow(), row["id"]),
    )
    conn.commit()
    job = _row_to_job(row)
    job.status = "running"
    job.attempts += 1
    return job


def mark_done(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE processing_jobs SET status = 'done', updated_at = ? WHERE id = ?",
        (utcnow(), job_id),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    conn.execute(
        "UPDATE processing_jobs SET status = 'failed', last_error = ?, updated_at = ? WHERE id = ?",
        (error, utcnow(), job_id),
    )
    conn.commit()


def reset_interrupted(conn: sqlite3.Connection) -> int:
    """At startup, put jobs a dead worker left running back in the queue."""
    cur = conn.execute(
        "UPDATE processing_jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
        (utcnow(),),
    )
    conn.commit()
    return cur.rowcount


def get_job(conn: sqlite3.Connection, job_id: int) -> Job:
    row = conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(f"no job {job_id}")
    return _row_to_job(row)


def jobs_for_meeting(conn: sqlite3.Connection, meeting_id: str) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM processing_jobs WHERE meeting_id = ? ORDER BY id", (meeting_id,)
    ).fetchall()
    return [_row_to_job(r) for r in rows]
