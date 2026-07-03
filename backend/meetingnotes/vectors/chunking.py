"""Transcript chunking for retrieval: one chunk per speaker turn, long turns
split on a word budget, each chunk carrying its speaker and timestamps so
retrieval can cite where an answer came from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from meetingnotes.pipeline.segments import Segment
from meetingnotes.storage.transcript import group_turns

MAX_WORDS = 120


@dataclass
class Chunk:
    text: str
    speaker: str
    start_s: float
    end_s: float


def chunk_segments(segments: Sequence[Segment],
                   display_names: dict[str, str] | None = None) -> list[Chunk]:
    names = display_names or {}
    chunks: list[Chunk] = []
    turn_spans = _turn_spans(segments)
    for (start, speaker, text), end in zip(group_turns(segments), turn_spans):
        label = speaker or "Unknown speaker"
        shown = names.get(label, label)
        words = text.split()
        for offset in range(0, len(words), MAX_WORDS):
            piece = " ".join(words[offset:offset + MAX_WORDS])
            chunks.append(Chunk(text=piece, speaker=shown, start_s=start, end_s=end))
    return chunks


def _turn_spans(segments: Sequence[Segment]) -> list[float]:
    """End time of each turn, in the same order group_turns yields them."""
    ends: list[float] = []
    last_speaker: object = object()
    for seg in segments:
        if not seg.text.strip():
            continue
        if seg.speaker == last_speaker and ends:
            ends[-1] = seg.end
        else:
            ends.append(seg.end)
            last_speaker = seg.speaker
    return ends
