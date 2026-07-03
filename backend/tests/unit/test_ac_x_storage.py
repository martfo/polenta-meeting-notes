"""Cross-cutting: storage integrity."""

from meetingnotes.storage.db import migrate, open_db, schema_version
from meetingnotes.storage.frontmatter import read_meeting_md, write_meeting_md


def test_ac_x_b_storage_integrity_roundtrip(tmp_path, vault):
    """Migrations apply cleanly and idempotently, vault paths resolve, and
    front matter round-trips through write and read."""
    conn = open_db(vault.db_path)
    try:
        assert schema_version(conn) == 2
        migrate(conn)  # applying again changes nothing
        assert schema_version(conn) == 2
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(meetings)").fetchall()}
        assert "summary_edited" in columns
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()}
        assert {"folders", "meetings", "attendees", "speakers", "voiceprints",
                "meeting_speakers", "processing_jobs", "settings"} <= tables
    finally:
        conn.close()

    # Vault paths resolve under the root.
    assert vault.audio_path("some-id") == vault.root / "meetings" / "some-id" / "audio.wav"
    assert vault.summary_prompt_path == vault.root / "settings" / "summary_prompt.md"
    assert vault.db_path.parent == vault.root

    # Front matter round-trip.
    front = {
        "id": "2026-07-02_1400_client-review",
        "title": "Client review",
        "date": "2026-07-02",
        "start_time": "14:00",
        "duration_s": 3212,
        "source": "online",
        "folder": "Clients",
        "attendees": [{"name": "Ben Adams", "email": "ben@example.com"}],
        "speakers": ["Ben Adams", "Roger Neel"],
        "tags": [],
        "processing_status": "ready",
        "summary_status": "ready",
    }
    path = tmp_path / "meeting.md"
    write_meeting_md(path, front, "## Core items discussed\n\nBody text.")
    read_front, body = read_meeting_md(path)
    assert read_front == front
    assert body == "## Core items discussed\n\nBody text."
