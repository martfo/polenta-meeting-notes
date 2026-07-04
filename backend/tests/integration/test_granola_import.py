"""Importing a Granola CSV export into the vault."""

import csv
import io

from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import read_meeting_md
from meetingnotes.tools.granola_import import (
    import_granola_csv,
    map_columns,
    parse_transcript,
)


def _csv(rows: list[dict], headers: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def test_column_mapping_is_tolerant_of_names():
    """Headers are matched case- and separator-insensitively."""
    mapping, unmapped = map_columns(
        ["Title", "Note Summary", "Transcript", "Created At", "Workspace", "id", "Mystery"])
    assert mapping["title"] == "Title"
    assert mapping["summary"] == "Note Summary"
    assert mapping["transcript"] == "Transcript"
    assert mapping["date"] == "Created At"
    assert mapping["folder"] == "Workspace"
    assert mapping["granola_id"] == "id"
    assert unmapped == ["Mystery"]


def test_parse_transcript_speakers_and_fallback():
    """Speaker turns are recognised; a bare blob becomes one segment."""
    segments = parse_transcript("Ben Adams: Hello there.\nRoger Neel: Hi Ben.\nBen Adams: How are you?")
    assert [s.speaker for s in segments] == ["Ben Adams", "Roger Neel", "Ben Adams"]
    assert segments[0].text == "Hello there."

    plain = parse_transcript("Just some text with no speakers at all.")
    assert len(plain) == 1 and plain[0].speaker is None


def test_import_creates_meetings_folders_and_files(conn, vault):
    text = _csv(
        [
            {
                "Title": "Client review",
                "Summary": "## Core items discussed\n\nBudget approved.",
                "Transcript": "Ben Adams: We reviewed the budget.\nRoger Neel: Agreed.",
                "Date": "2026-06-01 14:00:00",
                "Workspace": "Clients",
                "Attendees": "Ben Adams; Roger Neel",
                "id": "doc-abc-123",
            },
            {
                "Title": "Internal sync",
                "Summary": "## Core items discussed\n\nRoadmap.",
                "Transcript": "Just a quick chat about the roadmap.",
                "Date": "2026-06-02",
                "Workspace": "Internal",
                "Attendees": "",
                "id": "doc-def-456",
            },
        ],
        ["Title", "Summary", "Transcript", "Date", "Workspace", "Attendees", "id"],
    )

    report = import_granola_csv(conn, vault, text)

    assert report.imported == 2 and report.skipped == 0
    assert set(report.folders_created) == {"Clients", "Internal"}

    listing = m.library_listing(conn)
    by_folder = {g["folder"]: g["meetings"] for g in listing}
    assert "Clients" in by_folder and "Internal" in by_folder

    review_id = "granola-docabc123"
    front, body = read_meeting_md(vault.meeting_md_path(review_id))
    assert front["title"] == "Client review"
    assert front["date"] == "2026-06-01"
    assert front["source"] == "imported"
    assert "granola-import" in front["tags"]
    assert "Budget approved." in body
    transcript = vault.transcript_path(review_id).read_text()
    assert "Ben Adams" in transcript and "reviewed the budget" in transcript
    assert [a["name"] for a in m.list_attendees(conn, review_id)] == ["Ben Adams", "Roger Neel"]
    assert m.get_meeting(conn, review_id)["summary_status"] == "ready"


def test_import_is_idempotent(conn, vault):
    text = _csv(
        [{"Title": "Once", "Summary": "S", "Transcript": "A: hi", "id": "doc-1"}],
        ["Title", "Summary", "Transcript", "id"],
    )
    first = import_granola_csv(conn, vault, text)
    second = import_granola_csv(conn, vault, text)
    assert first.imported == 1 and second.imported == 0 and second.skipped == 1
    assert conn.execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 1


def test_import_indexes_each_meeting(conn, vault):
    indexed: list[str] = []
    text = _csv(
        [{"Title": "A", "Summary": "S", "Transcript": "Ben: hello", "id": "doc-1"}],
        ["Title", "Summary", "Transcript", "id"],
    )
    import_granola_csv(conn, vault, text, indexer=indexed.append)
    assert indexed == ["granola-doc1"]


def test_import_without_recognised_columns_reports_clearly(conn, vault):
    text = _csv([{"Foo": "x", "Bar": "y"}], ["Foo", "Bar"])
    report = import_granola_csv(conn, vault, text)
    assert report.imported == 0
    assert report.warnings and "recognised" in report.warnings[0].lower()


def test_note_without_summary_is_pending(conn, vault):
    text = _csv(
        [{"Title": "No summary", "Transcript": "Ben: hi", "id": "doc-9"}],
        ["Title", "Transcript", "id"],
    )
    import_granola_csv(conn, vault, text)
    row = m.get_meeting(conn, "granola-doc9")
    assert row["summary_status"] == "pending"
