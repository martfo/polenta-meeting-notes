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


def test_every_row_is_reconciled(conn, vault):
    """Imported, duplicate, empty, and failed rows together account for every
    line read, so nothing is silently dropped."""
    text = _csv(
        [
            {"Title": "Good one", "Summary": "S", "Transcript": "Ben: hi", "id": "doc-1"},
            {"Title": "Good two", "Summary": "S", "Transcript": "Ben: hi", "id": "doc-2"},
            {"Title": "", "Summary": "", "Transcript": "", "id": ""},          # empty
            {"Title": "Good one", "Summary": "S", "Transcript": "Ben: hi", "id": "doc-1"},  # dup
        ],
        ["Title", "Summary", "Transcript", "id"],
    )
    report = import_granola_csv(conn, vault, text)

    assert report.total_rows == 4
    assert report.imported == 2
    assert report.skipped == 1
    assert report.empty == 1
    assert report.failed == 0
    assert report.reconciled
    assert report.accounted == report.total_rows


def test_a_failing_row_is_recorded_and_rolled_back(conn, vault, monkeypatch):
    """A row that fails mid-write is recorded as a failure, leaves no orphan
    meeting behind, and does not stop the rest of the import."""
    import meetingnotes.tools.granola_import as gi

    real_write = gi._write_meeting
    calls = {"n": 0}

    def flaky_write(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            real_write(*args, **kwargs)  # partially create, then blow up
            raise RuntimeError("disk gremlin")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(gi, "_write_meeting", flaky_write)

    text = _csv(
        [
            {"Title": "Boom", "Summary": "S", "Transcript": "Ben: hi", "id": "doc-boom"},
            {"Title": "Fine", "Summary": "S", "Transcript": "Ben: hi", "id": "doc-fine"},
        ],
        ["Title", "Summary", "Transcript", "id"],
    )
    report = import_granola_csv(conn, vault, text)

    assert report.imported == 1
    assert report.failed == 1
    assert report.failures[0].title == "Boom"
    assert "disk gremlin" in report.failures[0].reason
    assert report.reconciled
    # No orphan left from the failed row.
    assert not vault.meeting_dir("granola-docboom").exists()
    assert not _meeting_exists_helper(conn, "granola-docboom")
    # The later row still imported.
    assert _meeting_exists_helper(conn, "granola-docfine")


def _meeting_exists_helper(conn, meeting_id):
    return conn.execute("SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)).fetchone() is not None


def test_new_folders_created_and_notes_filed(conn, vault):
    """Folders in the export that do not exist yet are created and their
    notes filed into them."""
    from meetingnotes.storage import folders as fol

    assert fol.list_folders(conn) == []
    text = _csv(
        [
            {"Title": "A", "Summary": "S", "Transcript": "x", "Workspace": "New Folder One", "id": "1"},
            {"Title": "B", "Summary": "S", "Transcript": "x", "Workspace": "New Folder Two", "id": "2"},
            {"Title": "C", "Summary": "S", "Transcript": "x", "Workspace": "New Folder One", "id": "3"},
        ],
        ["Title", "Summary", "Transcript", "Workspace", "id"],
    )
    report = import_granola_csv(conn, vault, text)

    assert set(report.folders_created) == {"New Folder One", "New Folder Two"}
    assert set(fol.list_folders(conn)) == {"New Folder One", "New Folder Two"}
    listing = {g["folder"]: [x["title"] for x in g["meetings"]] for g in m.library_listing(conn)}
    assert set(listing["New Folder One"]) == {"A", "C"}
    assert listing["New Folder Two"] == ["B"]


def test_note_without_summary_is_pending(conn, vault):
    text = _csv(
        [{"Title": "No summary", "Transcript": "Ben: hi", "id": "doc-9"}],
        ["Title", "Transcript", "id"],
    )
    import_granola_csv(conn, vault, text)
    row = m.get_meeting(conn, "granola-doc9")
    assert row["summary_status"] == "pending"
