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


class SegmentList(BaseModel):
    language: str = "en"
    segments: list[Segment]


def load_segments(path: Path) -> SegmentList:
    return SegmentList.model_validate(json.loads(Path(path).read_text()))


def save_segments(segments: SegmentList, path: Path) -> None:
    Path(path).write_text(segments.model_dump_json(indent=2) + "\n")
