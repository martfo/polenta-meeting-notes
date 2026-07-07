"""Detecting recordings with no speech.

Whisper hallucinates plausible-sounding text from silence, which then becomes
a fabricated summary. So before transcription the audio's energy is measured,
and an essentially silent recording skips the pipeline and is marked as having
no speech rather than being invented into nonsense.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

# Root-mean-square amplitude, normalised to [0, 1]. Real speech sits well
# above this; room tone and a muted or absent microphone sit below it.
DEFAULT_RMS_THRESHOLD = 0.006


def audio_rms(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        frames = w.getnframes()
        if frames == 0 or w.getsampwidth() != 2:
            return 0.0
        samples = np.frombuffer(w.readframes(frames), dtype=np.int16)
    if samples.size == 0:
        return 0.0
    normalised = samples.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(normalised * normalised)))


def is_silent(wav_path: Path, threshold: float = DEFAULT_RMS_THRESHOLD) -> bool:
    """True when the recording carries no meaningful audio."""
    return audio_rms(wav_path) < threshold
