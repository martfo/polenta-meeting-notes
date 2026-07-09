"""Transcript segments: the pipeline's output and the renderer's input.

A segment is one diarised stretch of speech with start, end, speaker label,
text, and optional word-level timings. Gated tests load a recorded segment
list from the fixtures instead of running WhisperX.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class Word(BaseModel):
    word: str
    start: float
    end: float


class Segment(BaseModel):
    start: float
    end: float
    speaker: str | None = None
    text: str
    words: list[Word] = []
    # "mic" (the owner) or "system" (remote participants) when the recording
    # was captured as two channels; None for a single mixed stream.
    channel: str | None = None


class SegmentList(BaseModel):
    language: str = "en"
    segments: list[Segment]


def merge_by_time(*segment_lists: list[Segment]) -> list[Segment]:
    """Interleave segments from several channels into one timeline, ordered by
    start time. This is how the separately transcribed microphone and system
    channels become a single 'me versus them' transcript."""
    merged: list[Segment] = []
    for segments in segment_lists:
        merged.extend(segments)
    merged.sort(key=lambda s: (s.start, s.end))
    return merged


def load_segments(path: Path) -> SegmentList:
    return SegmentList.model_validate(json.loads(Path(path).read_text()))


def save_segments(segments: SegmentList, path: Path) -> None:
    Path(path).write_text(segments.model_dump_json(indent=2) + "\n")
