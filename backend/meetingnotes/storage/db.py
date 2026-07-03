"""SQLite index with a small migration runner. No server.

The schema is pinned in DESIGN.md. Migrations are append-only; the runner
applies whatever is newer than the database's user_version.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: the Phase 1 schema.
    """
    CREATE TABLE folders(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    );
    CREATE TABLE meetings(
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        folder_id INTEGER REFERENCES folders(id),
        started_at TEXT NOT NULL,
        duration_s INTEGER,
        source TEXT NOT NULL DEFAULT 'online',
        vault_path TEXT NOT NULL,
        processing_status TEXT NOT NULL DEFAULT 'queued',
        summary_status TEXT NOT NULL DEFAULT 'pending',
        last_error TEXT,
        failed_stage TEXT,
        expected_speakers INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE attendees(
        id INTEGER PRIMARY KEY,
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        email TEXT,
        from_calendar INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE speakers(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    );
    CREATE TABLE voiceprints(
        id INTEGER PRIMARY KEY,
        speaker_id INTEGER NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('positive', 'negative')),
        embedding_ref TEXT NOT NULL,
        source_meeting_id TEXT,
        flagged INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE meeting_speakers(
        id INTEGER PRIMARY KEY,
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        diarised_label TEXT NOT NULL,
        speaker_id INTEGER REFERENCES speakers(id),
        display_name TEXT,
        confirmed INTEGER NOT NULL DEFAULT 0,
        assigned_by TEXT CHECK (assigned_by IN ('enrolment', 'attendee', 'manual') OR assigned_by IS NULL),
        matched_voiceprint_id INTEGER,
        match_score REAL,
        cluster_embedding_ref TEXT,
        UNIQUE (meeting_id, diarised_label)
    );
    CREATE TABLE processing_jobs(
        id INTEGER PRIMARY KEY,
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        stage TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'running', 'done', 'failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 2: whether the user has edited the summary body by hand. An edited
    # summary is never regenerated without asking; a machine summary follows
    # the notes automatically.
    """
    ALTER TABLE meetings ADD COLUMN summary_edited INTEGER NOT NULL DEFAULT 0;
    """,
]

PROCESSING_STATUSES = {
    "recording", "queued", "transcribing", "diarising", "enriching",
    "summarising", "ready", "needs_attention", "failed",
}
SUMMARY_STATUSES = {"pending", "ready", "needs_attention"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_db(path: Path | str) -> sqlite3.Connection:
    # The API thread and the worker thread share this connection; WAL plus
    # SQLite's own serialisation make that safe for our short writes.
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in enumerate(MIGRATIONS, start=1):
        if version > current:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]
