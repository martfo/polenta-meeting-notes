"""Section 1.7: folders and filing. Unit tier."""

import pytest

from meetingnotes.llm.folders import parse_suggestion, suggest_folder
from meetingnotes.storage import folders as f
from meetingnotes.storage import meetings as m
from tests.conftest import FakeLMClient, make_meeting

EXISTING = ["Clients", "Internal", "Suppliers"]


def test_ac_1_7_a_nested_folder_rejected(conn):
    """Folders are flat: a nested create is rejected."""
    with pytest.raises(ValueError):
        f.create_folder(conn, "Clients/Acme")
    with pytest.raises(ValueError):
        f.create_folder(conn, "Clients\\Acme")
    assert f.list_folders(conn) == []


def test_ac_1_7_b_suggestion_and_malformed_fallback(fixtures_dir):
    """A canned JSON suggestion is offered pre-selected; a malformed reply
    falls back to no suggestion and never blocks saving."""
    ok = (fixtures_dir / "llm" / "folder_suggestion_ok.json").read_text()
    suggestion = suggest_folder(FakeLMClient(ok), EXISTING, "A client meeting")
    assert suggestion is not None
    assert (suggestion.folder, suggestion.is_new) == ("Clients", False)

    malformed = (fixtures_dir / "llm" / "folder_suggestion_malformed.txt").read_text()
    assert suggest_folder(FakeLMClient(malformed), EXISTING, "x") is None

    # A folder that is neither in the list nor marked new is unusable too.
    unknown = (fixtures_dir / "llm" / "folder_suggestion_unknown.json").read_text()
    assert parse_suggestion(unknown, EXISTING) is None

    # A proposed new folder is fine when marked new.
    new = (fixtures_dir / "llm" / "folder_suggestion_new.json").read_text()
    suggestion = parse_suggestion(new, EXISTING)
    assert suggestion is not None and suggestion.is_new is True


def test_ac_1_7_c_accept_override_create_persist(conn, vault):
    """Accepting, overriding, or creating a folder persists the right id."""
    meeting_id = make_meeting(conn, vault)
    clients = f.create_folder(conn, "Clients")
    internal = f.create_folder(conn, "Internal")

    m.set_folder(conn, meeting_id, clients)  # accept the suggestion
    assert m.get_meeting(conn, meeting_id)["folder_id"] == clients

    m.set_folder(conn, meeting_id, internal)  # pick another existing folder
    assert m.get_meeting(conn, meeting_id)["folder_id"] == internal

    brand_new = f.create_folder(conn, "Hydroponics")  # create a new one
    m.set_folder(conn, meeting_id, brand_new)
    assert m.get_meeting(conn, meeting_id)["folder_id"] == brand_new


def test_ac_1_7_d_single_folder_membership(conn, vault):
    """A meeting belongs to exactly one folder: the relationship is a single
    column, so reassigning replaces rather than accumulates."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(meetings)").fetchall()}
    assert "folder_id" in columns
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()}
    assert not any("meeting_folder" in t for t in tables), "no many-to-many table"

    meeting_id = make_meeting(conn, vault)
    a, b = f.create_folder(conn, "A"), f.create_folder(conn, "B")
    m.set_folder(conn, meeting_id, a)
    m.set_folder(conn, meeting_id, b)
    assert m.get_meeting(conn, meeting_id)["folder_id"] == b
