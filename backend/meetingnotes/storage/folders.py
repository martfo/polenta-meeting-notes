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
