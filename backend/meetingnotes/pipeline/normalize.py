"""Per-channel gain normalisation before transcription.

Call audio is often compressed and quiet. Once the microphone and system
audio are separate streams, each can be lifted to a healthy level on its own,
so quiet remote speech is not discarded by the transcriber's voice-activity
threshold. Normalisation writes a new WAV and leaves the original untouched.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

# Leave headroom below full scale to avoid clipping artefacts.
TARGET_PEAK = 0.89
# Do not amplify essentially silent audio (it would only raise noise).
MIN_PEAK_TO_NORMALISE = 0.002


def normalise_wav(source: Path, destination: Path, target_peak: float = TARGET_PEAK) -> Path:
    """Write a peak-normalised copy of a 16-bit mono WAV. If the audio is
    essentially silent, the copy is unchanged."""
    with wave.open(str(source), "rb") as w:
        params = w.getparams()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    if samples.size:
        floats = samples.astype(np.float32) / 32768.0
        peak = float(np.max(np.abs(floats)))
        if peak >= MIN_PEAK_TO_NORMALISE:
            floats = np.clip(floats * (target_peak / peak), -1.0, 1.0)
        samples = (floats * 32767.0).astype(np.int16)

    with wave.open(str(destination), "wb") as out:
        out.setparams(params)
        out.writeframes(samples.tobytes())
    return destination
