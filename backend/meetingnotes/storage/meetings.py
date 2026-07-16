"""Meeting rows: creation, status transitions, and error records."""

from __future__ import annotations

import sqlite3
from typing import Any

from meetingnotes.storage.db import PROCESSING_STATUSES, SUMMARY_STATUSES, utcnow


def create_meeting(
    conn: sqlite3.Connection,
    meeting_id: str,
    title: str,
    started_at: str,
    vault_path: str,
    source: str = "online",
    duration_s: int | None = None,
    expected_speakers: int | None = None,
    processing_status: str = "queued",
) -> str:
    conn.execute(
        """INSERT INTO meetings(id, title, started_at, duration_s, source, vault_path,
               processing_status, summary_status, expected_speakers, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (meeting_id, title, started_at, duration_s, source, vault_path,
         processing_status, expected_speakers, utcnow()),
    )
    conn.commit()
    return meeting_id


def get_meeting(conn: sqlite3.Connection, meeting_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if row is None:
        raise KeyError(f"no meeting {meeting_id}")
    return row


def set_processing_status(conn: sqlite3.Connection, meeting_id: str, status: str) -> None:
    assert status in PROCESSING_STATUSES, status
    conn.execute("UPDATE meetings SET processing_status = ? WHERE id = ?", (status, meeting_id))
    conn.commit()


def set_summary_status(conn: sqlite3.Connection, meeting_id: str, status: str) -> None:
    assert status in SUMMARY_STATUSES, status
    conn.execute("UPDATE meetings SET summary_status = ? WHERE id = ?", (status, meeting_id))
    conn.commit()


def record_failure(conn: sqlite3.Connection, meeting_id: str, stage: str, message: str) -> None:
    """A plain-language error and the failing stage, shown in the library and
    on the meeting. Never carries transcript or summary content."""
    conn.execute(
        "UPDATE meetings SET processing_status = 'failed', last_error = ?, failed_stage = ? WHERE id = ?",
        (message, stage, meeting_id),
    )
    conn.commit()


def clear_failure(conn: sqlite3.Connection, meeting_id: str) -> None:
    conn.execute(
        "UPDATE meetings SET last_error = NULL, failed_stage = NULL WHERE id = ?",
        (meeting_id,),
    )
    conn.commit()


def set_folder(conn: sqlite3.Connection, meeting_id: str, folder_id: int) -> None:
    conn.execute("UPDATE meetings SET folder_id = ? WHERE id = ?", (folder_id, meeting_id))
    conn.commit()


def set_suggested_folder(conn: sqlite3.Connection, meeting_id: str, folder: str) -> None:
    """Cache the model's folder suggestion so it is computed once, not on every
    open."""
    conn.execute(
        "UPDATE meetings SET suggested_folder = ? WHERE id = ?", (folder, meeting_id))
    conn.commit()


def add_attendee(
    conn: sqlite3.Connection, meeting_id: str, name: str,
    email: str | None = None, from_calendar: bool = False,
) -> int:
    cur = conn.execute(
        "INSERT INTO attendees(meeting_id, name, email, from_calendar) VALUES (?, ?, ?, ?)",
        (meeting_id, name, email, int(from_calendar)),
    )
    conn.commit()
    return cur.lastrowid


def list_attendees(conn: sqlite3.Connection, meeting_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM attendees WHERE meeting_id = ? ORDER BY id", (meeting_id,)
    ).fetchall()


def library_listing(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Meetings grouped by folder for the library view: title, date, attendees,
    folder, and processing state. Unfiled meetings group under None."""
    rows = conn.execute(
        """SELECT m.*, f.name AS folder_name
           FROM meetings m LEFT JOIN folders f ON m.folder_id = f.id
           ORDER BY f.name IS NULL, f.name, m.started_at DESC"""
    ).fetchall()
    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        attendees = [a["name"] for a in list_attendees(conn, row["id"])]
        groups.setdefault(row["folder_name"], []).append(
            {
                "id": row["id"],
                "title": row["title"],
                "date": row["started_at"][:10],
                "started_at": row["started_at"],
                "attendees": attendees,
                "folder": row["folder_name"],
                "processing_status": row["processing_status"],
                "summary_status": row["summary_status"],
                "last_error": row["last_error"],
                "failed_stage": row["failed_stage"],
            }
        )
    return [{"folder": name, "meetings": items} for name, items in groups.items()]
