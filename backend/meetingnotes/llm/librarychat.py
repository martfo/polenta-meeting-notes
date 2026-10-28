"""Library-wide chat: find the passages most relevant to the question within
the chosen scope (by meaning and by its words together), widen the best
transcript passages with what was said either side, and send them with the
question to the loaded model, citing which meetings the answer came from.

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
    "You answer questions across a library of meeting transcripts using only "
    "the excerpts provided. The excerpts are the passages retrieved as most "
    "relevant to the question; they are not the whole meetings, so they may be "
    "incomplete.\n\n"
    "Follow these rules:\n"
    "- Base your answer only on the excerpts. Do not use outside knowledge.\n"
    "- Each excerpt names its meeting and speaker; attribute statements to the "
    "right person.\n"
    "- Never state that something was not said or did not happen. The excerpts "
    "are only a partial view, so absence from them does not mean absence from "
    "the meeting. If the excerpts do not contain the answer, say you could not "
    "find it in the retrieved excerpts and suggest rewording the question.\n"
    "- Do not guess or fill gaps; if you are unsure, say what the excerpts do "
    "and do not show.\n"
    "- Only connect an excerpt to the subject of the question when the excerpt "
    "itself makes that connection. An excerpt that does not mention the subject "
    "is not evidence about it, even if it was retrieved alongside one that does.\n"
    "- Speakers often give hypothetical examples (\"say the north region hasn't sent "
    "its figures\"). Report an example as an example, never as something that "
    "happened.\n"
    "- Excerpts are labelled by source. A summary is a condensed account written "
    "after the meeting: use it for what was concluded and agreed. A transcript is "
    "what was said: use it for who said what. Notes are the user's own.\n"
    "- Answer plainly in British English.\n\n"
    "End your reply with a single line in exactly this form, naming only the "
    "meetings your answer actually drew on:\n"
    "Sources: <meeting id>, <meeting id>"
)

_SOURCES_LINE = re.compile(r"^\s*Sources:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def extract_citations(answer: str, retrieved_ids: list[str]) -> tuple[str, list[str]]:
    """The meetings the answer drew on: the model's Sources line, validated
    against what was actually retrieved so nothing can be invented; the ids
    mentioned in the text as the next best; every retrieved meeting as the
    honest fallback. The model's Sources line is always stripped from the
    shown answer, since the app renders its own source links."""
    match = None
    for match in _SOURCES_LINE.finditer(answer):
        pass  # keep the last occurrence

    cleaned = answer
    if match:
        # Match ids as substrings of the line, since the model may reformat
        # them (a "meeting " prefix, say) rather than list them verbatim.
        line = match.group(1)
        listed = [mid for mid in retrieved_ids if mid in line]
        cleaned = (answer[:match.start()] + answer[match.end():]).strip()
        if listed:
            return cleaned, listed

    mentioned = [mid for mid in retrieved_ids if mid in answer]
    if mentioned:
        return cleaned, mentioned
    return cleaned, retrieved_ids


@dataclass
class LibraryAnswer:
    answer: str
    citations: list[str] = field(default_factory=list)  # meeting ids, in rank order


def retrieve(
    store: VectorStore, embedder: TextEmbedder, question: str,
    scope: ChatScope = DEFAULT_SCOPE, folder_id: int | None = None, limit: int = 12,
) -> list[dict]:
    """Passages within the chosen scope only, ranked by meaning and by the
    question's words together. Folder scope requires the folder."""
    if scope is ChatScope.FOLDER and folder_id is None:
        raise ValueError("folder scope needs the current folder")
    query_vector = embedder.embed_texts([question])[0]
    return store.search(
        query_vector, folder_id=folder_id if scope is ChatScope.FOLDER else None,
        limit=limit, query_text=question,
    )


@dataclass
class Excerpt:
    meeting_id: str
    label: str
    text: str


# How many of the best transcript hits are widened with the passage either
# side, and the overall size of what is sent to the model. A hit names the
# subject; the passages around it usually hold what was actually said about
# it. The budget keeps the request well inside a local model's context.
WIDEN_TOP = 4
EXCERPT_BUDGET_WORDS = 4000

_SOURCE_LABELS = {"summary": "Summary", "notes": "Your notes", "image": "Pasted image"}


def build_excerpts(store: VectorStore, hits: list[dict],
                   widen_top: int = WIDEN_TOP,
                   budget_words: int = EXCERPT_BUDGET_WORDS) -> list[Excerpt]:
    """Turn ranked passages into excerpts for the model, best first.

    The top transcript hits gain the passages either side of them, and
    passages that end up adjacent in one meeting are merged into one excerpt,
    so the model reads a stretch of conversation rather than fragments. Stops
    adding excerpts once the word budget is spent (the best one always goes)."""
    # (meeting, source) -> {seq: best rank}; rows by key for the text.
    wanted: dict[tuple[str, str], dict[int, int]] = {}
    rows: dict[tuple[str, str, int], dict] = {}
    singles: list[tuple[int, dict]] = []  # rows without an order (the old table)
    widened = 0
    for rank, hit in enumerate(hits):
        source = hit.get("source", "transcript")
        seq = hit.get("seq")
        if seq is None:
            singles.append((rank, hit))
            continue
        group = wanted.setdefault((hit["meeting_id"], source), {})
        group[seq] = min(group.get(seq, rank), rank)
        rows[(hit["meeting_id"], source, seq)] = hit
        if source == "transcript" and widened < widen_top:
            widened += 1
            for neighbour in (seq - 1, seq + 1):
                if neighbour >= 0:
                    group.setdefault(neighbour, rank)

    for (meeting_id, source), group in wanted.items():
        missing = [seq for seq in group if (meeting_id, source, seq) not in rows]
        for row in store.neighbours(meeting_id, source, missing):
            rows[(meeting_id, source, row["seq"])] = row

    ranked: list[tuple[int, Excerpt]] = []
    for (meeting_id, source), group in wanted.items():
        present = sorted(seq for seq in group if (meeting_id, source, seq) in rows)
        run: list[int] = []
        for seq in present + [None]:
            if seq is not None and (not run or seq == run[-1] + 1):
                run.append(seq)
                continue
            if run:
                parts = [rows[(meeting_id, source, s)] for s in run]
                label = _SOURCE_LABELS.get(source) or f"Transcript from {_clock(parts[0]['start_s'])}"
                ranked.append((min(group[s] for s in run), Excerpt(
                    meeting_id, label, "\n".join(p["chunk_text"] for p in parts))))
            run = [seq] if seq is not None else []
    for rank, hit in singles:
        ranked.append((rank, Excerpt(
            hit["meeting_id"], f"{hit['speaker']} at {_clock(hit['start_s'])}", hit["chunk_text"])))

    ranked.sort(key=lambda item: item[0])
    excerpts: list[Excerpt] = []
    words = 0
    for _, excerpt in ranked:
        size = len(excerpt.text.split())
        if excerpts and words + size > budget_words:
            continue
        excerpts.append(excerpt)
        words += size
    return excerpts


def _clock(seconds: float) -> str:
    total = int(seconds or 0)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def assemble_library_messages(question: str, excerpts: list[Excerpt]) -> list[dict[str, str]]:
    blocks = [f"[meeting {e.meeting_id}] {e.label}:\n{e.text}" for e in excerpts]
    content = "# Excerpts\n\n" + "\n\n".join(blocks) + "\n\n# Question\n\n" + question
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

    # A folder-scoped search that finds nothing widens to the whole vault
    # rather than dead-ending, and the answer says it looked more broadly.
    widened = False
    if not chunks and scope is ChatScope.FOLDER:
        chunks = retrieve(store, embedder, question, ChatScope.ALL)
        widened = True

    if not chunks:
        return LibraryAnswer(
            answer="Nothing in your meetings matches that question yet.", citations=[])

    excerpts = build_excerpts(store, chunks)
    answer = client.chat(assemble_library_messages(question, excerpts))
    retrieved_ids = list(dict.fromkeys(e.meeting_id for e in excerpts))
    answer, citations = extract_citations(british_pass(answer, allowlist).text, retrieved_ids)
    if widened:
        answer = ("Nothing matched in the selected folder, so I searched every "
                  "folder:\n\n") + answer
    return LibraryAnswer(answer=answer, citations=citations)
