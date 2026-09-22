"""Transcript import: bringing an already-written transcript into the app.

A markdown or text transcript (this app's own transcript.md, a Teams or Zoom
export, notes typed up by hand) becomes a meeting in the vault with no audio.
The turns are parsed into the same segments the pipeline produces, so the
meeting is indexed, summarised, and chattable exactly like a recording; only
the audio stages are skipped, because there is no audio to run them on.

Audio import (jobs/importer.py) is the parallel path for recordings.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.jobs import queue as q
from meetingnotes.jobs.filename_date import datetime_from_filename
from meetingnotes.pipeline.segments import SegmentList, save_segments
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import write_meeting_md
from meetingnotes.storage.transcript import render_transcript
from meetingnotes.storage.vault import Vault
from meetingnotes.tools.transcript_text import (
    apply_owner_label,
    parse_markdown_transcript,
    transcript_duration_s,
)

# The stage an imported transcript starts from: there is nothing to
# transcribe, diarise, or enrol, so it enters the queue at the search index
# and runs on to the summary.
FIRST_STAGE = "embed"

# What a dropped transcript can be. Subtitle exports (.vtt, .srt) are
# transcripts too: a tool that writes captions is transcribing a meeting.
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".vtt", ".srt"}


def title_from_filename(name: str) -> str:
    """A readable title from a file's stem, or "" when the name is only a
    date and time. A timestamp is how the file was named, not what the
    meeting was called, and it becomes the meeting's date instead.
    """
    cleaned = " ".join(re.sub(r"[_\-]+", " ", name).split())
    return cleaned if re.search(r"[A-Za-z]", cleaned) else ""


def _fallback_title(started_at: datetime) -> str:
    return f"Transcript {started_at.day} {started_at:%B %Y}"


def import_transcript_text(
    conn: sqlite3.Connection,
    vault: Vault,
    text: str,
    title: str | None = None,
    started_at: datetime | None = None,
    filename: str | None = None,
    owner_name: str | None = None,
) -> str:
    """Create a meeting from a written transcript and enqueue it.

    The title and date come from the document where it declares them (front
    matter, then a level-one heading, then a date in the filename), and
    otherwise from the caller or the filename. Returns the meeting id without
    waiting for the summary.
    """
    parsed = parse_markdown_transcript(text)
    if not parsed.segments:
        raise ValueError("no transcript text found in the file")
    # Other tools write the person recording as "Me"; the summary is told to
    # ignore placeholder labels, so give them their name.
    parsed.segments = apply_owner_label(parsed.segments, owner_name)

    stem = Path(filename).stem if filename else ""
    started_at = (started_at or parsed.started_at
                  or (datetime_from_filename(stem) if stem else None)
                  or datetime.now().astimezone())
    title = (title or parsed.title or title_from_filename(stem)
             or _fallback_title(started_at))

    meeting_id = vault.new_meeting_id(started_at, title)
    meeting_dir = vault.meeting_dir(meeting_id)
    meeting_dir.mkdir(parents=True)

    # Written atomically: a failure part-way leaves no half-made meeting
    # behind, matching how the Granola importer treats a row.
    try:
        duration_s = transcript_duration_s(parsed.segments)
        save_segments(SegmentList(segments=parsed.segments), meeting_dir / "segments.json")
        vault.transcript_path(meeting_id).write_text(render_transcript(parsed.segments))

        m.create_meeting(
            conn, meeting_id, title=title,
            started_at=started_at.isoformat(timespec="seconds"),
            vault_path=str(meeting_dir), source="imported",
            duration_s=duration_s,
        )
        speakers = list(dict.fromkeys(s.speaker for s in parsed.segments if s.speaker))
        # The document names its speakers, so record them as the meeting's
        # speakers. There is no audio behind the names, so nothing is taught
        # to the voice gallery, but they show in the Speakers tab and can be
        # renamed across the transcript and summary like any other.
        gallery = Gallery(conn, vault)
        for name in speakers:
            asg.record_named_speaker(gallery, meeting_id, name, name)
        for name in parsed.attendees:
            m.add_attendee(conn, meeting_id, name)

        write_meeting_md(
            vault.meeting_md_path(meeting_id),
            {
                "id": meeting_id,
                "title": title,
                "date": started_at.date().isoformat(),
                "start_time": started_at.strftime("%H:%M"),
                "duration_s": duration_s,
                "source": "imported",
                "folder": None,
                "attendees": [{"name": name} for name in parsed.attendees],
                "speakers": speakers,
                "tags": ["transcript-import"],
                "processing_status": "queued",
                "summary_status": "pending",
            },
            "_Imported transcript; the summary is being written._",
        )
    except Exception:
        conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        conn.commit()
        shutil.rmtree(meeting_dir, ignore_errors=True)
        raise

    q.enqueue(conn, meeting_id, stage=FIRST_STAGE)
    return meeting_id


def import_transcript_file(
    conn: sqlite3.Connection,
    vault: Vault,
    path: Path | str,
    title: str | None = None,
    started_at: datetime | None = None,
    owner_name: str | None = None,
) -> str:
    """Read a transcript file and import it. Anything unreadable as text, or
    empty of turns, is refused rather than becoming a blank meeting."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"no file at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ValueError(f"could not read '{path.name}'") from exc
    except OSError as exc:
        raise ValueError(f"could not read '{path.name}'") from exc
    if not text.strip():
        raise ValueError(f"'{path.name}' is empty")
    return import_transcript_text(
        conn, vault, text, title=title, started_at=started_at, filename=path.name,
        owner_name=owner_name)
