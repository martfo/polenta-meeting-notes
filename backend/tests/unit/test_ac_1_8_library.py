"""Section 1.8: the library view and Reveal in Finder. Unit tier."""

from meetingnotes.storage import folders as f
from meetingnotes.storage import meetings as m
from meetingnotes.storage.meetings import library_listing
from tests.conftest import make_meeting


def test_ac_1_8_a_library_grouped_by_folder(conn, vault):
    """The library groups meetings by folder and shows title, date,
    attendees, and processing state, straight from the database."""
    clients = f.create_folder(conn, "Clients")
    internal = f.create_folder(conn, "Internal")

    review = make_meeting(conn, vault, "2026-07-02_1400_client-review", "Client review")
    m.set_folder(conn, review, clients)
    m.add_attendee(conn, review, "Ben Adams")
    m.add_attendee(conn, review, "Roger Neel")
    m.set_processing_status(conn, review, "ready")

    standup = make_meeting(conn, vault, "2026-07-03_0930_standup", "Standup")
    m.set_folder(conn, standup, internal)
    m.set_processing_status(conn, standup, "transcribing")

    unfiled = make_meeting(conn, vault, "2026-07-03_1100_adhoc", "Ad hoc call")

    listing = library_listing(conn)
    by_folder = {group["folder"]: group["meetings"] for group in listing}
    assert set(by_folder) == {"Clients", "Internal", None}

    entry = by_folder["Clients"][0]
    assert entry["title"] == "Client review"
    assert entry["date"] == "2026-07-02"
    assert entry["attendees"] == ["Ben Adams", "Roger Neel"]
    assert entry["processing_status"] == "ready"
    assert by_folder["Internal"][0]["processing_status"] == "transcribing"
    assert by_folder[None][0]["id"] == unfiled


def test_ac_1_8_b_reveal_path_resolution(conn, vault):
    """Reveal in Finder opens the meeting's folder in the vault: the resolved
    path is that folder and it exists."""
    meeting_id = make_meeting(conn, vault, "2026-07-02_1400_client-review", "Client review")
    resolved = vault.meeting_dir(meeting_id)
    assert resolved == vault.root / "meetings" / "2026-07-02_1400_client-review"
    assert resolved.is_dir()
    assert m.get_meeting(conn, meeting_id)["vault_path"] == str(resolved)
