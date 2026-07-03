"""Library-wide chat: embed the question, retrieve the most relevant chunks
within the chosen scope, and send them with the question to the loaded model,
citing which meetings the answer came from.

Scoping is required and defaults to the current folder, because searching one
folder is the common case and searching the whole vault is rare."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from meetingnotes.language.britpass import british_pass
from meetingnotes.vectors.indexer import TextEmbedder
from meetingnotes.vectors.store import VectorStore


class ChatScope(str, Enum):
    FOLDER = "folder"
    ALL = "all"


DEFAULT_SCOPE = ChatScope.FOLDER

SYSTEM_PROMPT = (
    "You answer questions across a library of meeting transcripts, using only "
    "the excerpts provided. Each excerpt names its meeting and speaker. Answer "
    "plainly in British English and say which meetings the answer comes from. "
    "If the excerpts do not contain the answer, say so."
)


@dataclass
class LibraryAnswer:
    answer: str
    citations: list[str] = field(default_factory=list)  # meeting ids, in rank order


def retrieve(
    store: VectorStore, embedder: TextEmbedder, question: str,
    scope: ChatScope = DEFAULT_SCOPE, folder_id: int | None = None, limit: int = 8,
) -> list[dict]:
    """Chunks within the chosen scope only. Folder scope requires the folder."""
    if scope is ChatScope.FOLDER and folder_id is None:
        raise ValueError("folder scope needs the current folder")
    query_vector = embedder.embed_texts([question])[0]
    return store.search(
        query_vector, folder_id=folder_id if scope is ChatScope.FOLDER else None, limit=limit,
    )


def assemble_library_messages(question: str, chunks: list[dict]) -> list[dict[str, str]]:
    excerpts = [
        f"[meeting {c['meeting_id']}] {c['speaker']} at {c['start_s']:.0f}s: {c['chunk_text']}"
        for c in chunks
    ]
    content = "# Excerpts\n\n" + "\n\n".join(excerpts) + "\n\n# Question\n\n" + question
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def ask_library(
    client, store: VectorStore, embedder: TextEmbedder, question: str,
    scope: ChatScope = DEFAULT_SCOPE, folder_id: int | None = None,
    allowlist: set[str] | None = None,
) -> LibraryAnswer:
    chunks = retrieve(store, embedder, question, scope, folder_id)
    if not chunks:
        return LibraryAnswer(answer="Nothing in this scope matches the question.", citations=[])
    answer = client.chat(assemble_library_messages(question, chunks))
    citations = list(dict.fromkeys(c["meeting_id"] for c in chunks))
    return LibraryAnswer(answer=british_pass(answer, allowlist).text, citations=citations)
