"""The real WhisperX engine: Whisper large-v3 on the faster-whisper CPU
backend, English wav2vec2 alignment, and pyannote diarisation.

Imported lazily so the fast gate never needs the heavy dependencies. Models
are downloaded once during first-run setup and cached; after that everything
here runs offline. pyannote needs the Hugging Face token from the Keychain
for that first download only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WHISPER_MODEL = "large-v3"
DIARISATION_MODEL = "pyannote/speaker-diarization-community-1"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"


class WhisperXEngine:
    def __init__(self, hf_token: str | None = None, batch_size: int = 8):
        import whisperx  # heavy import, deferred on purpose

        self._whisperx = whisperx
        self._hf_token = hf_token
        self._batch_size = batch_size
        self._asr = None
        self._align_model = None
        self._align_metadata = None
        self._diarise_pipeline = None

    def transcribe(self, audio_path: Path, language: str) -> dict:
        if self._asr is None:
            self._asr = self._whisperx.load_model(
                WHISPER_MODEL, DEVICE, compute_type=COMPUTE_TYPE, language=language
            )
        audio = self._whisperx.load_audio(str(audio_path))
        return self._asr.transcribe(audio, batch_size=self._batch_size, language=language)

    def align(self, result: dict, audio_path: Path, language: str, model_name: str) -> dict:
        if self._align_model is None:
            self._align_model, self._align_metadata = self._whisperx.load_align_model(
                language_code=language, device=DEVICE, model_name=model_name
            )
        audio = self._whisperx.load_audio(str(audio_path))
        return self._whisperx.align(
            result["segments"], self._align_model, self._align_metadata, audio, DEVICE,
            return_char_alignments=False,
        )

    def diarise(self, audio_path: Path, num_speakers: int | None) -> Any:
        if self._diarise_pipeline is None:
            from whisperx.diarize import DiarizationPipeline

            self._diarise_pipeline = DiarizationPipeline(
                model_name=DIARISATION_MODEL, use_auth_token=self._hf_token, device=DEVICE
            )
        kwargs = {}
        if num_speakers is not None:
            kwargs["min_speakers"] = kwargs["max_speakers"] = num_speakers
        return self._diarise_pipeline(str(audio_path), **kwargs)

    def assign_speakers(self, diarisation: Any, aligned: dict) -> dict:
        from whisperx.diarize import assign_word_speakers

        return assign_word_speakers(diarisation, aligned)
