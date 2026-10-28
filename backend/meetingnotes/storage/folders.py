"""Folders are flat, and a meeting belongs to exactly one folder: the single
folder_id column on the meetings row is the whole relationship."""

from __future__ import annotations

import sqlite3

from meetingnotes.storage.db import utcnow


def create_folder(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("a folder needs a name")
    if "/" in name or "\\" in name:
        raise ValueError("folders are flat; nested folder names are not allowed")
    row = conn.execute("SELECT id FROM folders WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO folders(name, created_at) VALUES (?, ?)", (name, utcnow())
    )
    conn.commit()
    return cur.lastrowid


def list_folders(conn: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM folders ORDER BY name").fetchall()]


def folder_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM folders WHERE name = ?", (name,)).fetchone()
    return None if row is None else row["id"]


def folder_examples(
    conn: sqlite3.Connection, per_folder: int = 8
) -> dict[str, list[str]]:
    """The most recent meeting titles already filed in each folder, so a
    suggestion can learn from how meetings have been categorised before. Only
    folders that already contain meetings appear, newest titles first, capped
    per folder to keep the prompt small."""
    rows = conn.execute(
        """SELECT f.name AS folder, m.title AS title
           FROM meetings m JOIN folders f ON m.folder_id = f.id
           WHERE m.title IS NOT NULL AND m.title != ''
           ORDER BY m.started_at DESC"""
    ).fetchall()
    examples: dict[str, list[str]] = {}
    for row in rows:
        titles = examples.setdefault(row["folder"], [])
        if len(titles) < per_folder:
            titles.append(row["title"])
    return examples
