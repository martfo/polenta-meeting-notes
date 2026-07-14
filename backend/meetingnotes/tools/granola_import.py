"""Import meetings from a Granola CSV export.

Granola exports historical data as a CSV (Settings, Profile, Generate CSV)
carrying a title, summary, transcript, and basic details per note. This turns
each row into a meeting in the vault: a folder, transcript.md, meeting.md with
the summary, the folder membership, and an entry in the search index.

Granola keeps no local audio, so imported meetings have no audio.wav. They are
complete historical records, searchable and chattable and re-summarisable from
the transcript, but not re-recordable.

The column mapping is deliberately tolerant of naming differences, and the
result reports which columns were mapped and which were ignored, so adjusting
to a specific export is a small change.
"""

from __future__ import annotations

import csv
import hashlib
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from meetingnotes.pipeline.segments import Segment, SegmentList, save_segments
from meetingnotes.storage import folders as fol
from meetingnotes.storage import meetings as m
from meetingnotes.storage.db import utcnow
from meetingnotes.storage.frontmatter import write_meeting_md
from meetingnotes.storage.transcript import render_transcript
from meetingnotes.storage.vault import Vault

# Candidate header names for each field, compared after normalising to
# lowercase alphanumerics. The first CSV column that matches wins. Fields are
# claimed in declaration order, so with both a summary and a notes column the
# summary field takes "summary" and the notes field takes "notes" (the user's
# own typed notes, kept separate in Granola exactly as they are here); with
# only a "notes" column, the summary falls back to it as before. The real
# export's columns are document_id, user_email, document_title,
# workspace_name, document_created, summary, notes, transcript; user_email is
# the exporting account, the same on every row, and is deliberately ignored.
FIELD_CANDIDATES: dict[str, set[str]] = {
    "title": {"title", "name", "meetingtitle", "notetitle", "documenttitle", "subject"},
    "summary": {"summary", "notesummary", "notes", "ainotes", "aisummary",
                "enhancednotes", "enhancednote", "content"},
    "notes": {"notes", "mynotes", "usernotes", "typednotes", "personalnotes",
              "manualnotes"},
    "transcript": {"transcript", "fulltranscript", "transcripttext", "rawtranscript"},
    "date": {"date", "created", "createdat", "meetingdate", "timestamp",
             "datetime", "createddate", "documentcreated", "datecreated",
             "starttime", "startedat"},
    "folder": {"folder", "folders", "workspace", "workspaces", "workspacename",
               "list", "lists"},
    "attendees": {"attendees", "participants", "people", "attendeelist", "guests"},
    "granola_id": {"id", "noteid", "documentid", "uuid", "docid"},
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def map_columns(headers: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    """Return the field-to-column mapping and the list of unmapped columns."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field_name, candidates in FIELD_CANDIDATES.items():
        for header in headers:
            if header in used:
                continue
            if _norm(header) in candidates:
                mapping[field_name] = header
                used.add(header)
                break
    unmapped = [h for h in headers if h not in used]
    return mapping, unmapped


# A leading timestamp and a "Speaker: text" opening, both optional.
_TURN = re.compile(
    r"^\s*(?:\[?(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?"
    r"(?:(?P<speaker>[A-Z][\w .'\-]{0,39}?):\s+)?(?P<text>\S.*)$"
)


def _ts_to_seconds(ts: str) -> float:
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_transcript(text: str) -> list[Segment]:
    """Parse a Granola transcript into segments. Recognises optional leading
    timestamps and 'Speaker: text' turns; falls back to plain paragraphs.
    Where no timestamps are given, turns get monotonic synthetic ones so the
    rendered transcript reads tidily."""
    if not text or not text.strip():
        return []
    segments: list[Segment] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _TURN.match(line)
        if not match:
            continue
        speaker = (match.group("speaker") or "").strip() or None
        body = match.group("text").strip()
        ts = match.group("ts")
        start = _ts_to_seconds(ts) if ts else float(len(segments))
        if segments and speaker == segments[-1].speaker and ts is None:
            segments[-1] = segments[-1].model_copy(
                update={"text": segments[-1].text + " " + body, "end": start + 1})
        else:
            segments.append(Segment(start=start, end=start + 1, speaker=speaker, text=body))
    return segments


def _parse_date(value: str | None) -> datetime:
    if value and value.strip():
        text = value.strip()
        for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M",
                    "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _meeting_id(row: dict, mapping: dict, title: str, date: datetime) -> str:
    """A stable id so re-importing the same export skips rather than
    duplicates."""
    raw = row.get(mapping.get("granola_id", ""), "") if "granola_id" in mapping else ""
    if raw and raw.strip():
        safe = re.sub(r"[^A-Za-z0-9]", "", raw)[:16]
        return f"granola-{safe}"
    digest = hashlib.sha1(f"{title}|{date.isoformat()}".encode()).hexdigest()[:12]
    return f"granola-{digest}"


def _split_attendees(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    parts = re.split(r"[;,\n]", value)
    return [p.strip() for p in parts if p.strip()]


@dataclass
class ImportFailure:
    row: int  # 1-based CSV data row
    title: str
    reason: str


@dataclass
class ImportReport:
    total_rows: int = 0
    imported: int = 0
    skipped: int = 0
    empty: int = 0
    folders_created: list[str] = field(default_factory=list)
    mapped_columns: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    failures: list[ImportFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def accounted(self) -> int:
        return self.imported + self.skipped + self.empty + self.failed

    @property
    def reconciled(self) -> bool:
        """Every CSV data row must end up in exactly one bucket."""
        return self.accounted == self.total_rows


def import_granola_csv(
    conn: sqlite3.Connection,
    vault: Vault,
    csv_text: str,
    indexer: Callable[[str], None] | None = None,
) -> ImportReport:
    """Import every row of a Granola CSV export into the vault. Idempotent:
    rows already imported are skipped. Every row lands in exactly one bucket
    (imported, skipped as a duplicate, empty, or failed with a reason), and
    the report reconciles that count against the number of rows read, so no
    line is ever silently dropped. `indexer`, when given, adds each new
    meeting to the search index."""
    reader = csv.DictReader(csv_text.splitlines())
    headers = reader.fieldnames or []
    mapping, unmapped = map_columns(headers)
    report = ImportReport(mapped_columns=mapping, unmapped_columns=unmapped)

    if "title" not in mapping and "summary" not in mapping and "transcript" not in mapping:
        report.warnings.append(
            "No title, summary, or transcript column recognised. Columns seen: "
            + ", ".join(headers))
        return report

    rows = list(reader)
    report.total_rows = len(rows)
    existing_folders = {name: fol.folder_id(conn, name) for name in fol.list_folders(conn)}

    for index, row in enumerate(rows):
        row_number = index + 1
        raw_title = (row.get(mapping.get("title", ""), "") or "").strip()
        summary = (row.get(mapping.get("summary", ""), "") or "").strip()
        notes_text = (row.get(mapping.get("notes", ""), "") or "").strip()
        transcript_text = (row.get(mapping.get("transcript", ""), "") or "").strip()

        # A wholly empty row carries nothing to import; account for it, do not
        # create a blank meeting. A row with only typed notes is still a record.
        if not raw_title and not summary and not notes_text and not transcript_text:
            report.empty += 1
            continue

        title = raw_title or f"Granola note {row_number}"
        date = _parse_date(row.get(mapping.get("date", "")))
        meeting_id = _meeting_id(row, mapping, title, date)

        if vault.meeting_dir(meeting_id).exists() or _meeting_exists(conn, meeting_id):
            report.skipped += 1
            continue

        # Each row is written atomically: any error rolls back the partial
        # meeting so no orphan row or folder is left behind, and the row is
        # recorded as a failure rather than lost.
        try:
            segments = parse_transcript(transcript_text)
            attendees = _split_attendees(row.get(mapping.get("attendees", "")))
            folder_name = (row.get(mapping.get("folder", ""), "") or "").strip()

            _write_meeting(conn, vault, meeting_id, title, date, summary, segments,
                           attendees, notes_text)

            if folder_name:
                if folder_name not in existing_folders:
                    existing_folders[folder_name] = fol.create_folder(conn, folder_name)
                    report.folders_created.append(folder_name)
                m.set_folder(conn, meeting_id, existing_folders[folder_name])

            report.imported += 1
        except Exception as exc:
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
            shutil.rmtree(vault.meeting_dir(meeting_id), ignore_errors=True)
            report.failures.append(ImportFailure(row_number, title, str(exc)))
            continue

        if indexer is not None:
            try:
                indexer(meeting_id)
            except Exception as exc:  # indexing is best effort; the meeting is in
                report.warnings.append(f"could not index {meeting_id}: {exc}")

    if not report.reconciled:
        report.warnings.append(
            f"reconciliation mismatch: {report.imported} imported + {report.skipped} "
            f"skipped + {report.empty} empty + {report.failed} failed = {report.accounted}, "
            f"but {report.total_rows} rows were read")
    return report


def _meeting_exists(conn: sqlite3.Connection, meeting_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)).fetchone() is not None


def _write_meeting(
    conn: sqlite3.Connection, vault: Vault, meeting_id: str, title: str,
    date: datetime, summary: str, segments: list[Segment], attendees: list[str],
    notes_text: str = "",
) -> None:
    meeting_dir = vault.meeting_dir(meeting_id)
    meeting_dir.mkdir(parents=True, exist_ok=True)

    if segments:
        save_segments(SegmentList(segments=segments), meeting_dir / "segments.json")
        vault.transcript_path(meeting_id).write_text(render_transcript(segments))

    # The user's own typed notes travel separately from the AI summary in the
    # export, and land in notes.md here, where they feed chat and any later
    # re-summarisation exactly like notes typed in the app.
    if notes_text:
        from meetingnotes.notes.notes import write_notes

        write_notes(vault, meeting_id, notes_text)

    summary_status = "ready" if summary else "pending"
    m.create_meeting(
        conn, meeting_id, title=title,
        started_at=date.isoformat(timespec="seconds"),
        vault_path=str(meeting_dir), source="imported",
        duration_s=int(segments[-1].end) if segments else None,
        processing_status="ready",
    )
    m.set_summary_status(conn, meeting_id, summary_status)

    speakers = list(dict.fromkeys(s.speaker for s in segments if s.speaker))
    front = {
        "id": meeting_id,
        "title": title,
        "date": date.date().isoformat(),
        "start_time": date.strftime("%H:%M"),
        "duration_s": int(segments[-1].end) if segments else None,
        "source": "imported",
        "folder": None,
        "attendees": [{"name": name} for name in attendees],
        "speakers": speakers,
        "tags": ["granola-import"],
        "processing_status": "ready",
        "summary_status": summary_status,
    }
    body = summary if summary else "_Imported from Granola; no summary was included._"
    write_meeting_md(vault.meeting_md_path(meeting_id), front, body)

    for name in attendees:
        m.add_attendee(conn, meeting_id, name)


def _main() -> None:
    import argparse

    from meetingnotes.config import load_config
    from meetingnotes.storage.db import open_db

    parser = argparse.ArgumentParser(description="Import a Granola CSV export into the vault.")
    parser.add_argument("csv_path")
    parser.add_argument("config_path", help="path to the vault's settings/config.json")
    args = parser.parse_args()

    config = load_config(Path(args.config_path))
    vault = Vault(config.vault_path)
    conn = open_db(vault.db_path)
    report = import_granola_csv(conn, vault, Path(args.csv_path).read_text())
    print(f"imported {report.imported}, skipped {report.skipped}")
    print("mapped columns:", report.mapped_columns)
    if report.unmapped_columns:
        print("ignored columns:", report.unmapped_columns)
    for warning in report.warnings:
        print("warning:", warning)


if __name__ == "__main__":
    _main()
