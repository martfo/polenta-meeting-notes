"""The real speaker embedding model: pyannote/embedding, run per diarised
span. Imported lazily; the fast gate injects controlled vectors instead."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from meetingnotes.enrolment.matching import cluster_voiceprint
from meetingnotes.pipeline.segments import Segment

EMBEDDING_MODEL = "pyannote/embedding"


def _load_waveform(audio_path: Path) -> dict:
    """A WAV as the in-memory dict pyannote accepts: waveform (channel, time)
    plus sample rate."""
    import wave

    import torch

    with wave.open(str(audio_path), "rb") as w:
        assert w.getsampwidth() == 2, "vault audio is 16-bit PCM"
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        channels = w.getnchannels()
        waveform = frames.reshape(-1, channels).T.astype(np.float32) / 32768.0
        return {
            "waveform": torch.from_numpy(waveform.copy()),
            "sample_rate": w.getframerate(),
        }


class PyannoteSpeakerEmbedder:
    def __init__(self, hf_token: str | None = None):
        from pyannote.audio import Model

        from meetingnotes.pipeline.device import pipeline_device

        # pyannote.audio 4 takes token=, not the older use_auth_token=.
        self._model = Model.from_pretrained(EMBEDDING_MODEL, token=hf_token)
        # Runs on the Apple GPU where available, but like alignment and
        # diarisation it falls back to CPU (permanently, for this embedder) if
        # a GPU op fails, so a device quirk never fails a meeting.
        self._device = pipeline_device()
        self._inference = self._build(self._device)

    def _build(self, device: str):
        import torch
        from pyannote.audio import Inference

        return Inference(self._model, window="whole", device=torch.device(device))

    def embed_span(self, audio_path: Path, start: float, end: float) -> np.ndarray:
        from pyannote.core import Segment as Span

        # Audio goes in preloaded, not as a path: pyannote 4's file decoding
        # needs torchcodec and FFmpeg libraries, and our vault WAVs are plain
        # 16 kHz mono PCM that the standard library reads fine.
        audio = _load_waveform(audio_path)
        rate = audio["sample_rate"]
        # pyannote refuses a chunk whose end reaches the file duration, so a
        # whole-file or boundary span is clamped one sample short.
        duration = audio["waveform"].shape[1] / rate
        end = min(end, duration - 1.0 / rate)
        try:
            return np.asarray(self._inference.crop(audio, Span(start, end))).reshape(-1)
        except Exception as exc:
            if self._device == "cpu":
                raise
            import logging
            logging.getLogger("meetingnotes.pipeline").warning(
                "speaker embedding failed on %s (%s); falling back to CPU", self._device, exc)
            self._device = "cpu"
            self._inference = self._build("cpu")
            return np.asarray(self._inference.crop(audio, Span(start, end))).reshape(-1)

    def cluster_voiceprints(
        self, audio_path: Path, segments: list[Segment], min_span_s: float = 0.5,
    ) -> dict[str, np.ndarray]:
        """One voiceprint per diarised label: the mean of its span embeddings,
        L2 normalised."""
        spans: dict[str, list[np.ndarray]] = {}
        for seg in segments:
            if seg.speaker is None or (seg.end - seg.start) < min_span_s:
                continue
            spans.setdefault(seg.speaker, []).append(
                self.embed_span(audio_path, seg.start, seg.end)
            )
        return {label: cluster_voiceprint(vecs) for label, vecs in spans.items() if vecs}
