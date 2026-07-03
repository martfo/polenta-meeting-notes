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
        for piece in _split_on_word_speakers(seg):
            segments.append(
                Segment(
                    start=float(piece["start"]),
                    end=float(piece["end"]),
                    speaker=piece.get("speaker"),
                    text=str(piece.get("text", "")).strip(),
                    words=[
                        {"word": w["word"], "start": w["start"], "end": w["end"]}
                        for w in piece.get("words", [])
                        if "start" in w and "end" in w
                    ],
                )
            )
    return SegmentList(language=LANGUAGE, segments=segments)


def _split_on_word_speakers(seg: dict) -> list[dict]:
    """Split one transcription segment wherever the diarised speaker changes
    at the word level.

    Whisper breaks segments on sentences, not on speakers, so one segment can
    span a speaker handover (or, with no punctuation, a whole conversation).
    assign_word_speakers labels each word; the turn structure lives there.
    """
    words = seg.get("words") or []
    if not any("speaker" in w for w in words):
        return [seg]

    pieces: list[dict] = []
    current: list[dict] = []
    current_speaker: str | None = None
    for word in words:
        speaker = word.get("speaker", current_speaker)
        if current and speaker != current_speaker:
            pieces.append(_piece_from_words(seg, current, current_speaker))
            current = []
        current.append(word)
        current_speaker = speaker
    if current:
        pieces.append(_piece_from_words(seg, current, current_speaker))
    return pieces


def _piece_from_words(seg: dict, words: list[dict], speaker: str | None) -> dict:
    timed = [w for w in words if "start" in w and "end" in w]
    return {
        "start": timed[0]["start"] if timed else seg["start"],
        "end": timed[-1]["end"] if timed else seg["end"],
        "speaker": speaker or seg.get("speaker"),
        "text": " ".join(str(w["word"]).strip() for w in words),
        "words": words,
    }
