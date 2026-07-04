"""Section 2.1: library-wide retrieval over LanceDB, with a deterministic
keyword embedder standing in for bge-m3."""

import numpy as np
import pytest

from meetingnotes.llm.librarychat import ChatScope, ask_library, retrieve
from meetingnotes.pipeline.segments import SegmentList, load_segments, save_segments
from meetingnotes.storage import folders as f
from meetingnotes.storage import meetings as m
from meetingnotes.vectors.indexer import index_meeting
from meetingnotes.vectors.store import VectorStore
from tests.conftest import FIXTURES, FakeLMClient, make_meeting

KEYWORDS = ["hydroponics", "invoice", "sensors", "budget"]


class KeywordEmbedder:
    """One dimension per known keyword: retrieval outcomes are forced
    exactly, no acoustic or semantic model involved."""

    def embed_texts(self, texts):
        vectors = []
        for text in texts:
            vector = np.zeros(len(KEYWORDS) + 1)
            lowered = text.lower()
            for i, keyword in enumerate(KEYWORDS):
                if keyword in lowered:
                    vector[i] = 1.0
            if not vector.any():
                vector[-1] = 1.0
            vectors.append(vector / np.linalg.norm(vector))
        return np.array(vectors)


@pytest.fixture
def store(vault):
    return VectorStore(vault.lancedb_dir)


@pytest.fixture
def embedder():
    return KeywordEmbedder()


def seed_meeting(conn, vault, meeting_id, title, folder_id, text_by_speaker):
    make_meeting(conn, vault, meeting_id, title)
    m.set_folder(conn, meeting_id, folder_id)
    segments = SegmentList(segments=[
        {"start": float(i * 10), "end": float(i * 10 + 8), "speaker": speaker, "text": text}
        for i, (speaker, text) in enumerate(text_by_speaker)
    ])
    save_segments(segments, vault.meeting_dir(meeting_id) / "segments.json")
    return meeting_id


def test_ac_2_1_a_chunks_embedded_to_lancedb(conn, vault, store, embedder):
    """On save, the transcript is chunked and embedded, and vectors land in
    LanceDB with meeting id, folder id, speaker, and timestamps."""
    clients = f.create_folder(conn, "Clients")
    meeting_id = make_meeting(conn, vault)
    m.set_folder(conn, meeting_id, clients)
    fixture = load_segments(FIXTURES / "segments" / "two_speaker_meeting.json")
    save_segments(fixture, vault.meeting_dir(meeting_id) / "segments.json")

    count = index_meeting(conn, vault, store, embedder, meeting_id)

    rows = store.rows_for_meeting(meeting_id)
    assert count == len(rows) == 4, "one chunk per turn in the fixture"
    for row in rows:
        assert row["meeting_id"] == meeting_id
        assert row["folder_id"] == clients
        assert row["speaker"].startswith("SPEAKER_")
        assert 0 <= row["start_s"] < row["end_s"]
        assert len(row["vector"]) == 5
    assert any("hydroponics" in row["chunk_text"] for row in rows)


def test_ac_2_1_b_folder_scoped_retrieval(conn, vault, store, embedder):
    """A folder-scoped query retrieves chunks only from that folder."""
    clients = f.create_folder(conn, "Clients")
    internal = f.create_folder(conn, "Internal")
    a = seed_meeting(conn, vault, "2026-07-01_1000_a", "Client call", clients,
                     [("SPEAKER_00", "The hydroponics budget was approved.")])
    b = seed_meeting(conn, vault, "2026-07-02_1000_b", "Internal call", internal,
                     [("SPEAKER_00", "The hydroponics rollout plan is drafted.")])
    for meeting_id in (a, b):
        index_meeting(conn, vault, store, embedder, meeting_id)

    results = retrieve(store, embedder, "what about hydroponics",
                       scope=ChatScope.FOLDER, folder_id=clients)
    assert results, "the scoped folder has a matching chunk"
    assert {r["meeting_id"] for r in results} == {a}


def test_ac_2_1_c_all_folders_retrieval(conn, vault, store, embedder):
    """An all-folders query retrieves across the vault."""
    clients = f.create_folder(conn, "Clients")
    internal = f.create_folder(conn, "Internal")
    a = seed_meeting(conn, vault, "2026-07-01_1000_a", "Client call", clients,
                     [("SPEAKER_00", "The invoice for the sensors went out.")])
    b = seed_meeting(conn, vault, "2026-07-02_1000_b", "Internal call", internal,
                     [("SPEAKER_00", "Chase the invoice with accounts.")])
    for meeting_id in (a, b):
        index_meeting(conn, vault, store, embedder, meeting_id)

    results = retrieve(store, embedder, "where is the invoice", scope=ChatScope.ALL)
    assert {r["meeting_id"] for r in results} == {a, b}, "results span folders"


def test_ac_2_1_e_citations_match_chunks(conn, vault, store, embedder, fixtures_dir):
    """Given retrieved chunks and a canned answer, the response cites the
    meetings the chunks came from."""
    clients = f.create_folder(conn, "Clients")
    a = seed_meeting(conn, vault, "2026-07-01_1000_a", "Call one", clients,
                     [("Ben Adams", "The sensors arrived on Tuesday.")])
    b = seed_meeting(conn, vault, "2026-07-02_1000_b", "Call two", clients,
                     [("Roger Neel", "The sensors are installed and organized.")])
    for meeting_id in (a, b):
        index_meeting(conn, vault, store, embedder, meeting_id)

    client = FakeLMClient((fixtures_dir / "llm" / "chat_answer.md").read_text())
    result = ask_library(client, store, embedder, "what happened with the sensors",
                         scope=ChatScope.FOLDER, folder_id=clients)

    # No Sources line in this canned reply: every retrieved meeting is cited.
    assert set(result.citations) == {a, b}
    # The chunks themselves were sent, labelled by meeting.
    sent = client.requests[0][-1]["content"]
    assert f"[meeting {a}]" in sent and f"[meeting {b}]" in sent
    assert "—" not in result.answer and "organised" in result.answer

    # A reply that names its sources narrows the citations to the meetings
    # the answer actually drew on, and the trailer is not shown.
    naming = FakeLMClient(f"Ben said the sensors arrived on Tuesday.\n\nSources: {a}")
    result = ask_library(naming, store, embedder, "when did the sensors arrive",
                         scope=ChatScope.FOLDER, folder_id=clients)
    assert result.citations == [a], "only the meeting the answer used"
    assert "Sources:" not in result.answer

    # A hallucinated source is ignored in favour of the honest fallback.
    lying = FakeLMClient("Something.\n\nSources: 2026-01-01_0000_never-happened")
    result = ask_library(lying, store, embedder, "what about the sensors",
                         scope=ChatScope.FOLDER, folder_id=clients)
    assert set(result.citations) == {a, b}


def test_refiling_moves_chunks_in_index(conn, vault, store, embedder):
    """Moving a meeting to another folder updates the folder stored on its
    search chunks, so folder-scoped retrieval follows the move."""
    from meetingnotes.storage import meetings as m

    original = f.create_folder(conn, "Inbox")
    destination = f.create_folder(conn, "DesignTurbine")
    meeting = seed_meeting(conn, vault, "2026-07-04_1000_a", "Adiyah convo", original,
                           [("Adiyah", "The hydroponics budget was approved.")])
    index_meeting(conn, vault, store, embedder, meeting)

    # Refile it, as the folder endpoint does.
    m.set_folder(conn, meeting, destination)
    store.set_meeting_folder(meeting, destination)

    # It is now found under the new folder and no longer under the old one.
    in_new = retrieve(store, embedder, "hydroponics budget",
                      scope=ChatScope.FOLDER, folder_id=destination)
    assert {r["meeting_id"] for r in in_new} == {meeting}
    in_old = retrieve(store, embedder, "hydroponics budget",
                      scope=ChatScope.FOLDER, folder_id=original)
    assert in_old == []


def test_folder_scope_widens_when_empty(conn, vault, store, embedder, fixtures_dir):
    """A folder-scoped question with no match in that folder searches the
    whole vault rather than dead-ending, and says so."""
    clients = f.create_folder(conn, "Clients")
    empty_folder = f.create_folder(conn, "Empty")
    a = seed_meeting(conn, vault, "2026-07-01_1000_a", "Sensors call", clients,
                     [("Adiyah", "The hydroponics sensors were delivered.")])
    index_meeting(conn, vault, store, embedder, a)

    client = FakeLMClient(f"Adiyah discussed the sensors.\n\nSources: {a}")
    result = ask_library(client, store, embedder, "what about hydroponics",
                         scope=ChatScope.FOLDER, folder_id=empty_folder)

    assert result.citations == [a], "found in another folder"
    assert "searched every folder" in result.answer
