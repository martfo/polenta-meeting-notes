"""The real WhisperX engine: distilled Whisper large-v3 on the faster-whisper
CPU backend, English wav2vec2 alignment, and pyannote diarisation.

Imported lazily so the fast gate never needs the heavy dependencies. Models
are downloaded once during first-run setup and cached; after that everything
here runs offline. pyannote needs the Hugging Face token from the Keychain
for that first download only.

The transcription model is distil-large-v3, an English-only distillation of
large-v3 that runs about twice as fast on CPU for a negligible accuracy cost
on English speech. faster-whisper's CTranslate2 backend has no Apple-GPU
(Metal) support, only CPU and CUDA, so on this Mac transcription is CPU-bound
whatever the hardware; the model choice is where the CPU speed is won. A later
change can move transcription to an Apple-GPU engine (MLX) for a larger win.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from meetingnotes.pipeline.audio_io import load_audio_16k_mono
from meetingnotes.pipeline.device import pipeline_device

_log = logging.getLogger("meetingnotes.pipeline")

# distil-large-v3 -> Systran/faster-distil-whisper-large-v3 (English only).
WHISPER_MODEL = "distil-large-v3"
DIARISATION_MODEL = "pyannote/speaker-diarization-community-1"
# Transcription (CTranslate2) has no Metal backend, so it stays on CPU; the
# PyTorch stages below run on the Apple GPU where available (see device.py).
TRANSCRIBE_DEVICE = "cpu"
COMPUTE_TYPE = "int8"


class WhisperXEngine:
    def __init__(self, hf_token: str | None = None, batch_size: int = 8):
        import whisperx  # heavy import, deferred on purpose

        self._whisperx = whisperx
        self._hf_token = hf_token
        self._batch_size = batch_size
        # Alignment and diarisation prefer the GPU but fall back to CPU on any
        # failure, independently and permanently for this engine. Moving a model
        # to MPS can fail deep in torch (a "meta tensor" copy error, say) in ways
        # that are environment-specific and hard to predict, so rather than
        # trust it, we try and recover: a GPU quirk slows a meeting down, it
        # never fails it. Each stage remembers its working device so the failure
        # is paid at most once.
        self._align_device = pipeline_device()
        self._diarise_device = pipeline_device()
        self._asr = None
        self._loaded_prompt: str | None = None
        self._align_model = None
        self._align_metadata = None
        self._diarise_pipeline = None

    def transcribe(
        self, audio_path: Path, language: str, initial_prompt: str | None = None
    ) -> dict:
        # WhisperX bakes decoding options in at load time, so the initial prompt
        # is applied there and the model is reloaded only when the prompt changes
        # (participant names differ per meeting; a shared glossary usually does
        # not). The prompt biases Whisper towards the meeting's own vocabulary.
        if self._asr is None or initial_prompt != self._loaded_prompt:
            asr_options = {"initial_prompt": initial_prompt} if initial_prompt else None
            self._asr = self._whisperx.load_model(
                WHISPER_MODEL, TRANSCRIBE_DEVICE, compute_type=COMPUTE_TYPE,
                language=language, asr_options=asr_options,
            )
            self._loaded_prompt = initial_prompt
        audio = load_audio_16k_mono(audio_path)
        return self._asr.transcribe(audio, batch_size=self._batch_size, language=language)

    def align(self, result: dict, audio_path: Path, language: str, model_name: str) -> dict:
        audio = load_audio_16k_mono(audio_path)

        def run(device: str) -> dict:
            if self._align_model is None:
                self._align_model, self._align_metadata = self._whisperx.load_align_model(
                    language_code=language, device=device, model_name=model_name
                )
            return self._whisperx.align(
                result["segments"], self._align_model, self._align_metadata, audio,
                device, return_char_alignments=False,
            )

        def reset() -> None:
            self._align_model = None
            self._align_metadata = None

        self._align_device, out = self._with_cpu_fallback("alignment", self._align_device, run, reset)
        return out

    def diarise(self, audio_path: Path, num_speakers: int | None) -> Any:
        kwargs = {}
        if num_speakers is not None:
            kwargs["min_speakers"] = kwargs["max_speakers"] = num_speakers
        # Pass a preloaded array, not a path: WhisperX's DiarizationPipeline
        # only shells out to ffmpeg when handed a filename, and pyannote 4's
        # own file decoding needs torchcodec/FFmpeg libraries we avoid.
        audio = load_audio_16k_mono(audio_path)

        def run(device: str) -> Any:
            if self._diarise_pipeline is None:
                from whisperx.diarize import DiarizationPipeline

                self._diarise_pipeline = DiarizationPipeline(
                    model_name=DIARISATION_MODEL, token=self._hf_token, device=device
                )
            return self._diarise_pipeline(audio, **kwargs)

        def reset() -> None:
            self._diarise_pipeline = None

        self._diarise_device, out = self._with_cpu_fallback(
            "diarisation", self._diarise_device, run, reset)
        return out

    @staticmethod
    def _with_cpu_fallback(name, device, run, reset):
        """Run `run(device)`; if it fails on a GPU device, drop the models built
        there and retry once on CPU. Returns the device that worked and the
        result, so the caller sticks to CPU from then on."""
        try:
            return device, run(device)
        except Exception as exc:
            if device == "cpu":
                raise
            _log.warning("%s failed on %s (%s); falling back to CPU", name, device, exc)
            reset()
            return "cpu", run("cpu")

    def assign_speakers(self, diarisation: Any, aligned: dict) -> dict:
        from whisperx.diarize import assign_word_speakers

        return assign_word_speakers(diarisation, aligned)
