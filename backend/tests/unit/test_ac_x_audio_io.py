"""The ffmpeg-free audio loader that feeds WhisperX and pyannote.

Vault audio is 16 kHz mono 16-bit PCM and is read straight through; anything
off that (more channels, a different rate, another container) is converted
with afconvert, which ships with macOS. No ffmpeg, so the shipped app needs
no manual install.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import numpy as np

from meetingnotes.pipeline.audio_io import TARGET_RATE, load_audio_16k_mono


def _write_wav(path: Path, rate: int, channels: list[list[int]]) -> None:
    frames = bytearray()
    for i in range(len(channels[0])):
        for ch in channels:
            frames += struct.pack("<h", ch[i])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def _tone(rate: int, seconds: float, hz: float, amp: float = 0.5) -> list[int]:
    return [int(amp * math.sin(2 * math.pi * hz * (i / rate)) * 32767)
            for i in range(int(rate * seconds))]


def test_16k_mono_pcm_is_read_directly(fixtures_dir: Path) -> None:
    audio = load_audio_16k_mono(fixtures_dir / "audio" / "two_speaker_meeting.wav")
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    with wave.open(str(fixtures_dir / "audio" / "two_speaker_meeting.wav")) as w:
        assert audio.shape[0] == w.getnframes()
    assert float(np.max(np.abs(audio))) <= 1.0


def test_empty_recording_yields_empty_array(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    _write_wav(path, TARGET_RATE, [[]])
    audio = load_audio_16k_mono(path)
    assert audio.dtype == np.float32
    assert audio.shape[0] == 0


def test_stereo_16k_is_downmixed_to_mono_without_conversion(tmp_path: Path) -> None:
    path = tmp_path / "stereo16k.wav"
    left = _tone(TARGET_RATE, 0.25, 440)
    right = _tone(TARGET_RATE, 0.25, 880)
    _write_wav(path, TARGET_RATE, [left, right])
    audio = load_audio_16k_mono(path)
    assert audio.ndim == 1
    assert audio.shape[0] == len(left)  # one mono sample per frame
    expected_first = (left[1] / 32768.0 + right[1] / 32768.0) / 2
    assert audio[1] == np.float32(expected_first)


def test_offrate_multichannel_is_converted_via_afconvert(tmp_path: Path) -> None:
    path = tmp_path / "stereo48k.wav"
    left = _tone(48000, 0.5, 440)
    right = _tone(48000, 0.5, 880)
    _write_wav(path, 48000, [left, right])
    audio = load_audio_16k_mono(path)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    # 0.5 s resampled to 16 kHz is ~8000 samples; allow afconvert's edge slack.
    assert abs(audio.shape[0] - 8000) <= 64
    assert float(np.max(np.abs(audio))) <= 1.0
