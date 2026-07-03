"""Section 1.9: the retention purge, with an injectable clock."""

from datetime import datetime, timezone

from meetingnotes.storage.retention import purge_old_audio
from tests.conftest import make_meeting


def _populate(vault, meeting_id):
    d = vault.meeting_dir(meeting_id)
    (d / "audio.wav").write_bytes(b"RIFFfake")
    (d / "transcript.md").write_text("# Transcript\n")
    (d / "meeting.md").write_text("---\nid: x\n---\n\nSummary\n")
    (d / "notes.md").write_text("my notes\n")


def test_ac_1_9_b_purge_old_audio(conn, vault):
    """The purge removes audio.wav older than the period and keeps the
    transcript, summary, and notes; younger meetings keep their audio."""
    old = make_meeting(conn, vault, "2026-05-01_0900_old-meeting", "Old meeting")
    recent = make_meeting(conn, vault, "2026-06-28_0900_recent", "Recent meeting")
    conn.execute("UPDATE meetings SET started_at = '2026-05-01T09:00:00+00:00' WHERE id = ?", (old,))
    conn.execute("UPDATE meetings SET started_at = '2026-06-28T09:00:00+00:00' WHERE id = ?", (recent,))
    conn.commit()
    _populate(vault, old)
    _populate(vault, recent)

    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)  # the injected clock
    purged = purge_old_audio(conn, vault, days=30, now=now)

    assert purged == [old]
    old_dir = vault.meeting_dir(old)
    assert not (old_dir / "audio.wav").exists()
    for kept in ("transcript.md", "meeting.md", "notes.md"):
        assert (old_dir / kept).exists()
    assert (vault.meeting_dir(recent) / "audio.wav").exists()

    # Running again purges nothing new.
    assert purge_old_audio(conn, vault, days=30, now=now) == []
