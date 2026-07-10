"""Loading audio for the transcriber without shelling out to ffmpeg.

WhisperX's own ``load_audio`` runs ffmpeg, which made ffmpeg a per-Mac
prerequisite for the shipped app. But everything the pipeline transcribes is
already a 16 kHz mono 16-bit PCM WAV (the capture mixer writes exactly that,
and the normalisation step keeps it), so the standard library reads it
directly into the float32 array WhisperX and pyannote want. Anything that is
not already 16 kHz mono PCM — a different rate, more channels, or another
container from an import — is converted first with ``afconvert``, which ships
with macOS. No ffmpeg, and no new Python dependency: this mirrors the
preloaded-waveform path already used for pyannote embeddings in
``enrolment/embedder.py``.
"""

from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

TARGET_RATE = 16000
AFCONVERT = "/usr/bin/afconvert"


def load_audio_16k_mono(path: Path | str) -> np.ndarray:
    """Return the audio as a float32 mono waveform at 16 kHz, in [-1, 1].

    A drop-in replacement for ``whisperx.load_audio`` that needs no ffmpeg.
    """
    path = Path(path)
    samples = _read_pcm16_mono_16k(path)
    if samples is not None:
        return samples
    with tempfile.TemporaryDirectory() as tmp:
        converted = Path(tmp) / "audio16k.wav"
        _afconvert_to_16k_mono(path, converted)
        samples = _read_pcm16_mono_16k(converted)
    if samples is None:
        raise RuntimeError(f"could not decode audio: {path}")
    return samples


def _read_pcm16_mono_16k(path: Path) -> np.ndarray | None:
    """Read a 16 kHz 16-bit PCM WAV into a float32 mono array, or return None
    if the file is not 16-bit PCM at 16 kHz, so the caller converts it first.
    Multi-channel 16 kHz audio is downmixed to mono here rather than converted.
    """
    try:
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2 or w.getframerate() != TARGET_RATE:
                return None
            channels = w.getnchannels()
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    except (wave.Error, EOFError):
        return None
    if frames.size == 0:
        return np.zeros(0, dtype=np.float32)
    floats = frames.astype(np.float32) / 32768.0
    if channels > 1:
        floats = floats.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(floats, dtype=np.float32)


def _afconvert_to_16k_mono(source: Path, destination: Path) -> None:
    """Convert any audio afconvert can read into a 16 kHz mono 16-bit PCM WAV."""
    subprocess.run(
        [AFCONVERT, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
         str(source), str(destination)],
        check=True, capture_output=True,
    )
