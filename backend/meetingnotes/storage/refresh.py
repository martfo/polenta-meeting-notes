"""Rewriting a meeting's files after speaker naming changes.

transcript.md and meeting.md are written during processing with whatever
names were known then. Naming or correcting a speaker afterwards refreshes
them, so the files in the vault always show the resolved names. The summary
body is the user's document once produced: names are replaced in place, and
it is never regenerated behind their back."""

from __future__ import annotations

import re
import sqlite3

from meetingnotes.enrolment import assignments as asg
from meetingnotes.llm.summary import meeting_front_matter
from meetingnotes.pipeline.segments import load_segments
from meetingnotes.storage.frontmatter import read_meeting_md, write_meeting_md
from meetingnotes.storage.transcript import render_transcript
from meetingnotes.storage.vault import Vault


def refresh_meeting_files(conn: sqlite3.Connection, vault: Vault, meeting_id: str) -> None:
    segments_path = vault.meeting_dir(meeting_id) / "segments.json"
    if segments_path.exists():
        names = asg.display_names(conn, meeting_id)
        vault.transcript_path(meeting_id).write_text(
            render_transcript(load_segments(segments_path).segments, names)
        )

    meeting_md = vault.meeting_md_path(meeting_id)
    if meeting_md.exists():
        _, body = read_meeting_md(meeting_md)
        write_meeting_md(meeting_md, meeting_front_matter(conn, meeting_id), body)


def rename_speaker_in_summary(vault: Vault, meeting_id: str,
                              old_name: str | None, new_name: str | None) -> bool:
    """Replace a renamed speaker in the summary body, whole words only, and
    leave everything else (including the user's edits) exactly as written."""
    path = vault.meeting_md_path(meeting_id)
    if not path.exists() or not old_name or not new_name or old_name == new_name:
        return False
    front, body = read_meeting_md(path)
    replaced = re.sub(rf"(?<!\w){re.escape(old_name)}(?!\w)", new_name, body)
    if replaced == body:
        return False
    write_meeting_md(path, front, replaced)
    return True
