"""The embed stage's work: on each meeting save, chunk the transcript, embed
each chunk with the injected embedder (bge-m3 in production), and store the
vectors in LanceDB with meeting, folder, speaker, and timestamps."""

from __future__ import annotations

import sqlite3
from typing import Protocol

import numpy as np

from meetingnotes.enrolment import assignments as asg
from meetingnotes.pipeline.segments import load_segments
from meetingnotes.storage import meetings as m
from meetingnotes.storage.vault import Vault
from meetingnotes.vectors.chunking import chunk_segments
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


def index_meeting(
    conn: sqlite3.Connection, vault: Vault, store: VectorStore,
    embedder: TextEmbedder, meeting_id: str,
) -> int:
    segments_path = vault.meeting_dir(meeting_id) / "segments.json"
    if not segments_path.exists():
        return 0
    segments = load_segments(segments_path).segments
    chunks = chunk_segments(segments, asg.display_names(conn, meeting_id))
    if not chunks:
        return 0
    vectors = embedder.embed_texts([c.text for c in chunks])
    folder_id = m.get_meeting(conn, meeting_id)["folder_id"]
    return store.replace_meeting(meeting_id, folder_id, chunks, vectors)
