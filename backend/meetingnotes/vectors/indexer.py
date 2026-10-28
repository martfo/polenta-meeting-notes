"""The embed stage's work: on each meeting save, cut the meeting into
passages (transcript, summary, notes, pasted-image text), embed each with the
injected embedder (bge-m3 in production), and store them in LanceDB with
meeting, folder, source, speaker, and timestamps.

Also the one-off rebuild that moves an existing vault onto the current
passage layout (backfill_index)."""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Callable, Protocol

import numpy as np

from meetingnotes.enrolment import assignments as asg
from meetingnotes.pipeline.segments import load_segments
from meetingnotes.storage import meetings as m
from meetingnotes.storage.vault import Vault
from meetingnotes.vectors.chunking import (
    SOURCE_IMAGE,
    Chunk,
    chunk_notes,
    chunk_segments,
    chunk_summary,
)
from meetingnotes.vectors.store import VectorStore


class TextEmbedder(Protocol):
    def embed_texts(self, texts: list[str]) -> np.ndarray: ...


class BgeM3Embedder:
    """The real embedder, run inside the backend so it never occupies the LM
    Studio model slot. Heavy import, deferred; vectors L2 normalised."""

    def __init__(self, model_name: str = "bge-m3"):
        from FlagEmbedding import BGEM3FlagModel

        # config.json pins the short name bge-m3; the Hugging Face repo id
        # carries the owner prefix.
        if "/" not in model_name:
            model_name = f"BAAI/{model_name}"
        self._model = BGEM3FlagModel(model_name, use_fp16=False)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts)["dense_vecs"]
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-9, None)


# One embedding at a time: the worker's embed stage, the re-index after a
# rename or an edit, and the rebuild all share one model, which is not safe to
# drive from several threads at once.
_INDEX_LOCK = threading.Lock()

log = logging.getLogger("meetingnotes.index")


def meeting_chunks(conn: sqlite3.Connection, vault: Vault, meeting_id: str) -> list[Chunk]:
    """Every searchable passage of a meeting, in source order."""
    chunks: list[Chunk] = []
    segments_path = vault.meeting_dir(meeting_id) / "segments.json"
    if segments_path.exists():
        segments = load_segments(segments_path).segments
        chunks += chunk_segments(segments, asg.display_names(conn, meeting_id))

    meeting_md = vault.meeting_md_path(meeting_id)
    if meeting_md.exists():
        from meetingnotes.storage.frontmatter import read_meeting_md

        # The summary is a bonus for search, never a reason for processing to
        # fail: a meeting.md that does not parse is simply left out.
        try:
            _, body = read_meeting_md(meeting_md)
        except Exception:
            body = ""
        from meetingnotes.llm.summary import NO_SPEECH_BODY

        # A silent recording's stock "no speech" note says nothing about the
        # meeting; indexed for every silent meeting it would only be noise.
        if body.strip() != NO_SPEECH_BODY.strip():
            title = m.get_meeting(conn, meeting_id)["title"]
            chunks += chunk_summary(body, title=title)

    from meetingnotes.notes.notes import read_notes
    from meetingnotes.notes.ocr import read_ocr_texts

    chunks += chunk_notes(read_notes(vault, meeting_id))
    # Text recognised from pasted images is searchable too, attributed to a
    # pseudo-speaker so a citation reads sensibly.
    for i, ocr_text in enumerate(read_ocr_texts(vault, meeting_id)):
        chunks.append(Chunk(text=ocr_text, speaker="Pasted image", start_s=0.0,
                            end_s=0.0, source=SOURCE_IMAGE, seq=i))
    return chunks


def index_meeting(
    conn: sqlite3.Connection, vault: Vault, store: VectorStore,
    embedder: TextEmbedder, meeting_id: str,
) -> int:
    """(Re)index one meeting, replacing its passages. A meeting with nothing
    searchable has its passages removed."""
    chunks = meeting_chunks(conn, vault, meeting_id)
    folder_id = m.get_meeting(conn, meeting_id)["folder_id"]
    with _INDEX_LOCK:
        vectors = embedder.embed_texts([c.text for c in chunks]) if chunks else np.zeros((0, 1))
        return store.replace_meeting(meeting_id, folder_id, chunks, vectors)


def backfill_index(
    conn: sqlite3.Connection, vault: Vault, store: VectorStore,
    embedder: TextEmbedder, stop: Callable[[], bool] = lambda: False,
) -> int:
    """Index every meeting not yet in the current table, then switch search
    over to it. Safe to stop and resume: progress is the set of meetings
    already indexed, so a restart carries on where it left off. Returns how
    many meetings were indexed this run.

    Library search keeps using the previous table until this finishes, so
    it never returns nothing mid-rebuild."""
    if store.ready:
        return 0
    done = store.indexed_meeting_ids()
    pending = [row["id"] for row in conn.execute(
        "SELECT id FROM meetings ORDER BY started_at DESC").fetchall()
        if row["id"] not in done]
    count = 0
    for meeting_id in pending:
        if stop():
            return count
        try:
            index_meeting(conn, vault, store, embedder, meeting_id)
            count += 1
        except Exception:
            # One unreadable meeting must not hold the whole vault back; it is
            # indexed again the next time it is processed or edited.
            log.warning("rebuilding the search index skipped a meeting",
                        extra={"meeting_id": meeting_id, "stage": "embed"})
    store.mark_ready()
    log.info("search index rebuilt", extra={"stage": "embed"})
    return count
