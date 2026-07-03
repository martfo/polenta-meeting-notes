"""The transcription and diarisation runner.

The engine is injected, so gated tests supply a recording fake and the
[pipeline] tier plugs in the real WhisperX engine. This build targets English
only: the runner fixes the language to en and names the English wav2vec2
alignment model explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from meetingnotes.pipeline.segments import Segment, SegmentList

LANGUAGE = "en"
ENGLISH_ALIGNMENT_MODEL = "WAV2VEC2_ASR_LARGE_LV60K_960H"


class TranscriptionEngine(Protocol):
    def transcribe(self, audio_path: Path, language: str) -> dict: ...

    def align(self, result: dict, audio_path: Path, language: str, model_name: str) -> dict: ...

    def diarise(self, audio_path: Path, num_speakers: int | None) -> Any: ...

    def assign_speakers(self, diarisation: Any, aligned: dict) -> dict: ...


class PipelineRunner:
    def __init__(self, engine: TranscriptionEngine):
        self.engine = engine

    def transcribe(self, audio_path: Path) -> SegmentList:
        """Whisper transcription plus English word-level alignment."""
        raw = self.engine.transcribe(audio_path, language=LANGUAGE)
        aligned = self.engine.align(
            raw, audio_path, language=LANGUAGE, model_name=ENGLISH_ALIGNMENT_MODEL
        )
        return _to_segment_list(aligned)

    def diarise(self, audio_path: Path, aligned: SegmentList,
                expected_speakers: int | None = None) -> SegmentList:
        """pyannote diarisation, with the optional expected speaker count
        passed straight through, then speaker labels assigned to segments."""
        diarisation = self.engine.diarise(audio_path, num_speakers=expected_speakers)
        with_speakers = self.engine.assign_speakers(
            diarisation, {"segments": [s.model_dump() for s in aligned.segments]}
        )
        return _to_segment_list(with_speakers)


def _to_segment_list(result: dict) -> SegmentList:
    segments = []
    for seg in result["segments"]:
        segments.append(
            Segment(
                start=float(seg["start"]),
                end=float(seg["end"]),
                speaker=seg.get("speaker"),
                text=str(seg.get("text", "")).strip(),
                words=[
                    {"word": w["word"], "start": w["start"], "end": w["end"]}
                    for w in seg.get("words", [])
                    if "start" in w and "end" in w
                ],
            )
        )
    return SegmentList(language=LANGUAGE, segments=segments)
