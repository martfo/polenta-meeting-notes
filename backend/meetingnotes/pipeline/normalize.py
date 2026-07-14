"""Per-channel loudness normalisation before transcription.

Call audio is often compressed and quiet, and the remote (system) channel in
particular arrives well below the microphone. Once the two channels are
separate streams, each can be lifted on its own so quiet remote speech is not
discarded by the transcriber's voice-activity threshold.

Loudness, not peak. An earlier version scaled by the peak sample, but a single
loud transient (a notification, a click) sits near full scale while the speech
underneath stays quiet, so peak scaling barely moved it. This normalises to a
target speech RMS measured over the *voiced* frames, so long silences and rare
transients do not drag the measure around, then hard-limits the result: the
occasional transient clips harmlessly while the speech is brought up to a level
the voice-activity detector reliably hears.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

# A healthy speech level for the voice-activity detector, about -20 dBFS RMS.
TARGET_RMS = 0.1
# Frames quieter than this are treated as non-speech when measuring loudness.
VOICE_FLOOR = 0.01
# 25 ms at 16 kHz.
FRAME = 400
# Never amplify beyond this: a near-silent channel would only raise its noise.
MAX_GAIN = 12.0
# Below this peak the channel is essentially silent and is left untouched.
MIN_PEAK_TO_NORMALISE = 0.002


def _speech_gain(floats: np.ndarray, target_rms: float) -> float:
    """The gain that brings the voiced speech up to target_rms, clamped so a
    quiet channel is lifted but never attenuated and near-silence is not blown
    up into noise."""
    peak = float(np.max(np.abs(floats)))
    if peak < MIN_PEAK_TO_NORMALISE:
        return 1.0
    usable = (floats.size // FRAME) * FRAME
    if usable == 0:
        return 1.0
    frame_rms = np.sqrt(np.mean(floats[:usable].reshape(-1, FRAME) ** 2, axis=1))
    voiced = frame_rms[frame_rms > VOICE_FLOOR]
    # Fall back to the whole-signal RMS when nothing clears the voice floor, so
    # a uniformly quiet channel is still lifted.
    level = float(np.sqrt(np.mean(voiced ** 2))) if voiced.size else float(
        np.sqrt(np.mean(floats ** 2)))
    if level <= 0:
        return 1.0
    return float(np.clip(target_rms / level, 1.0, MAX_GAIN))


def normalise_wav(source: Path, destination: Path, target_rms: float = TARGET_RMS) -> Path:
    """Write a loudness-normalised copy of a 16-bit mono WAV. Quiet speech is
    brought up to target_rms and transients are hard-limited; an essentially
    silent channel is copied unchanged."""
    with wave.open(str(source), "rb") as w:
        params = w.getparams()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    if samples.size:
        floats = samples.astype(np.float32) / 32768.0
        gain = _speech_gain(floats, target_rms)
        floats = np.clip(floats * gain, -1.0, 1.0)
        samples = (floats * 32767.0).astype(np.int16)

    with wave.open(str(destination), "wb") as out:
        out.setparams(params)
        out.writeframes(samples.tobytes())
    return destination
