"""The speaker matching algorithm, exactly as pinned in DESIGN.md.

The embedding function and the gallery are injected inputs, so tests supply
controlled vectors and force exact match and non-match outcomes without
depending on real acoustic behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np


def l2_normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise ValueError("cannot normalise a zero vector")
    return vector / norm


def cluster_voiceprint(segment_embeddings: Sequence[np.ndarray] | np.ndarray) -> np.ndarray:
    """The cluster voiceprint is the mean of its segment embeddings, L2
    normalised."""
    stacked = np.asarray(segment_embeddings, dtype=float)
    if stacked.ndim != 2 or len(stacked) == 0:
        raise ValueError("expected a non-empty list of embedding vectors")
    return l2_normalise(stacked.mean(axis=0))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(l2_normalise(a), l2_normalise(b)))


class GalleryReader(Protocol):
    """What the matcher needs from the gallery: every speaker with their
    positive and negative voiceprint vectors and ids."""

    def speaker_voiceprints(self) -> list["SpeakerVoiceprints"]: ...


@dataclass
class SpeakerVoiceprints:
    speaker_id: int
    name: str
    positives: list[tuple[int, np.ndarray]]
    negatives: list[tuple[int, np.ndarray]]


@dataclass
class MatchResult:
    speaker_id: int
    name: str
    score: float
    voiceprint_id: int  # the nearest positive voiceprint: the provenance


def match_cluster(
    cluster_vp: np.ndarray,
    gallery: GalleryReader,
    threshold: float = 0.75,
    veto_margin: float = 0.10,
) -> MatchResult | None:
    """Auto-assign the best candidate only if pos clears the threshold and
    pos minus neg clears the veto margin. Otherwise leave the cluster for
    attendee or manual naming."""
    best: MatchResult | None = None
    best_neg = -1.0
    for speaker in gallery.speaker_voiceprints():
        if not speaker.positives:
            continue
        vp_id, pos = max(
            ((vp_id, cosine(cluster_vp, vec)) for vp_id, vec in speaker.positives),
            key=lambda item: item[1],
        )
        if best is None or pos > best.score:
            neg = max(
                (cosine(cluster_vp, vec) for _, vec in speaker.negatives),
                default=-1.0,
            )
            best = MatchResult(speaker.speaker_id, speaker.name, pos, vp_id)
            best_neg = neg
    if best is None:
        return None
    if best.score < threshold:
        return None
    if best.score - best_neg < veto_margin:
        return None
    return best
