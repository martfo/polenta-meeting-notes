"""The real speaker embedding model: pyannote/embedding, run per diarised
span. Imported lazily; the fast gate injects controlled vectors instead."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from meetingnotes.enrolment.matching import cluster_voiceprint
from meetingnotes.pipeline.segments import Segment

EMBEDDING_MODEL = "pyannote/embedding"


class PyannoteSpeakerEmbedder:
    def __init__(self, hf_token: str | None = None):
        from pyannote.audio import Inference, Model

        model = Model.from_pretrained(EMBEDDING_MODEL, use_auth_token=hf_token)
        self._inference = Inference(model, window="whole")

    def embed_span(self, audio_path: Path, start: float, end: float) -> np.ndarray:
        from pyannote.core import Segment as Span

        return np.asarray(self._inference.crop(str(audio_path), Span(start, end))).reshape(-1)

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
