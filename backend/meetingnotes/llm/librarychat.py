"""Library-wide chat: embed the question, retrieve the most relevant chunks
within the chosen scope, and send them with the question to the loaded model,
citing which meetings the answer came from.

Scoping is required and defaults to the current folder, because searching one
folder is the common case and searching the whole vault is rare."""

from __future__ import annotations

import re
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
    "plainly in British English. If the excerpts do not contain the answer, "
    "say so. End your reply with a single line in exactly this form, naming "
    "only the meetings your answer actually drew on:\n"
    "Sources: <meeting id>, <meeting id>"
)

_SOURCES_LINE = re.compile(r"^\s*Sources:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def extract_citations(answer: str, retrieved_ids: list[str]) -> tuple[str, list[str]]:
    """The meetings the answer drew on: the model's Sources line, validated
    against what was actually retrieved so nothing can be invented; the ids
    mentioned in the text as the next best; every retrieved meeting as the
    honest fallback. The Sources line is stripped from the shown answer."""
    match = None
    for match in _SOURCES_LINE.finditer(answer):
        pass  # keep the last occurrence
    if match:
        listed = {part.strip() for part in match.group(1).split(",")}
        valid = [mid for mid in retrieved_ids if mid in listed]
        if valid:
            cleaned = (answer[:match.start()] + answer[match.end():]).strip()
            return cleaned, valid
    mentioned = [mid for mid in retrieved_ids if mid in answer]
    if mentioned:
        return answer, mentioned
    return answer, retrieved_ids


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
    retrieved_ids = list(dict.fromkeys(c["meeting_id"] for c in chunks))
    answer, citations = extract_citations(british_pass(answer, allowlist).text, retrieved_ids)
    return LibraryAnswer(answer=answer, citations=citations)
