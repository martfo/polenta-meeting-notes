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


def test_ac_1_7_e_examples_learn_from_filed_titles(conn, vault):
    """folder_examples returns the titles already filed in each folder, newest
    first and capped per folder."""
    clients = f.create_folder(conn, "Clients")
    for i, title in enumerate(["Acme kickoff", "Acme review", "Globex sync"]):
        mid = make_meeting(conn, vault, f"2026-07-0{i+1}_1000_m", title)
        conn.execute(
            "UPDATE meetings SET started_at = ? WHERE id = ?",
            (f"2026-07-0{i+1}T10:00:00+00:00", mid))
        m.set_folder(conn, mid, clients)
    conn.commit()
    examples = f.folder_examples(conn)
    assert examples["Clients"][0] == "Globex sync"  # newest first
    assert set(examples["Clients"]) == {"Acme kickoff", "Acme review", "Globex sync"}
    assert f.folder_examples(conn, per_folder=1)["Clients"] == ["Globex sync"]


def test_ac_1_7_f_suggestion_prompt_carries_example_titles(fixtures_dir):
    """The example titles reach the model so it can match on past filing."""
    ok = (fixtures_dir / "llm" / "folder_suggestion_ok.json").read_text()
    client = FakeLMClient(ok)
    suggest_folder(
        client, EXISTING, "A meeting about the Acme rollout",
        folder_examples={"Clients": ["Acme kickoff", "Acme review"]},
    )
    prompt = client.requests[0][0]["content"]
    assert "Acme kickoff; Acme review" in prompt
    assert "Suppliers: (no meetings filed yet)" in prompt


def test_ac_1_7_g_suggestion_is_computed_once_and_cached(conn, vault, fixtures_dir):
    """The slow LLM call runs once; opening the meeting again reads the cached
    suggestion instead of asking the model every time."""
    from meetingnotes.llm.folder_filing import suggested_folder

    ok = (fixtures_dir / "llm" / "folder_suggestion_ok.json").read_text()  # -> "Clients"
    f.create_folder(conn, "Clients")
    meeting_id = make_meeting(conn, vault)
    client = FakeLMClient(ok)

    first = suggested_folder(conn, vault, client, meeting_id)
    second = suggested_folder(conn, vault, client, meeting_id)

    assert first == "Clients" and second == "Clients"
    assert len(client.requests) == 1, "the model is asked once, then the cache serves"
    assert m.get_meeting(conn, meeting_id)["suggested_folder"] == "Clients"


def test_ac_1_7_h_no_suggestion_is_not_cached(conn, vault, fixtures_dir):
    """A miss (no usable suggestion) is not cached, so it can be retried once
    the model or the folders improve, rather than being stuck on nothing."""
    from meetingnotes.llm.folder_filing import suggested_folder

    malformed = (fixtures_dir / "llm" / "folder_suggestion_malformed.txt").read_text()
    meeting_id = make_meeting(conn, vault)
    client = FakeLMClient(malformed)

    assert suggested_folder(conn, vault, client, meeting_id) is None
    assert m.get_meeting(conn, meeting_id)["suggested_folder"] is None
    assert suggested_folder(conn, vault, client, meeting_id) is None
    assert len(client.requests) == 2, "a miss is retried, not cached"
