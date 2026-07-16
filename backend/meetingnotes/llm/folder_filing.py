"""Computing a meeting's folder suggestion once and caching it.

The suggestion is a slow LLM call (it feeds the model the meeting's summary and
the titles already filed in each folder), so it is computed a single time and
stored on the meeting row. The pipeline precomputes it after summarising, and
the endpoint falls back to computing it on demand; both go through here so the
cache is the one source of truth.
"""

from __future__ import annotations

import sqlite3

from meetingnotes.llm.client import LMStudioClient
from meetingnotes.llm.folders import suggest_folder
from meetingnotes.storage import folders as fol
from meetingnotes.storage import meetings as m
from meetingnotes.storage.vault import Vault


def _context(conn: sqlite3.Connection, vault: Vault, meeting_id: str, title: str) -> str:
    """Title, attendees, and a slice of the summary (or transcript) so the
    suggestion reflects what the meeting was about, not just its title."""
    parts = [f"Title: {title}"]
    attendees = [a["name"] for a in m.list_attendees(conn, meeting_id)]
    if attendees:
        parts.append("Attendees: " + ", ".join(attendees))
    meeting_md = vault.meeting_md_path(meeting_id)
    transcript_path = vault.transcript_path(meeting_id)
    if meeting_md.exists():
        from meetingnotes.storage.frontmatter import read_meeting_md

        _, body = read_meeting_md(meeting_md)
        parts.append("Summary:\n" + body[:1500])
    elif transcript_path.exists():
        parts.append("Transcript extract:\n" + transcript_path.read_text()[:1500])
    return "\n\n".join(parts)


def suggested_folder(
    conn: sqlite3.Connection, vault: Vault, lm_client: LMStudioClient, meeting_id: str,
) -> str | None:
    """The cached folder suggestion for a meeting, computing and storing it once
    if absent. Returns the folder name, or None when there is no usable
    suggestion (or LM Studio is unreachable) -- only a real suggestion is
    cached, so a miss is retried next time rather than stuck."""
    row = m.get_meeting(conn, meeting_id)
    cached = row["suggested_folder"]
    if cached:
        return cached
    context = _context(conn, vault, meeting_id, row["title"])
    suggestion = suggest_folder(
        lm_client, fol.list_folders(conn), context,
        folder_examples=fol.folder_examples(conn),
    )
    if suggestion is None:
        return None
    m.set_suggested_folder(conn, meeting_id, suggestion.folder)
    return suggestion.folder
