"""The engine's GPU-to-CPU fallback: a device quirk slows a meeting, never
fails it."""

from __future__ import annotations

import pytest

from meetingnotes.pipeline.whisperx_engine import WhisperXEngine

fallback = WhisperXEngine._with_cpu_fallback


def test_success_on_gpu_keeps_the_device():
    calls = []
    device, out = fallback("alignment", "mps", lambda d: calls.append(d) or "ok", lambda: None)
    assert (device, out) == ("mps", "ok")
    assert calls == ["mps"]  # never retried


def test_failure_on_gpu_falls_back_to_cpu_and_resets():
    seen = []
    reset_called = []

    def run(device):
        seen.append(device)
        if device != "cpu":
            raise RuntimeError("Cannot copy out of meta tensor; no data!")
        return "recovered"

    device, out = fallback("alignment", "mps", run, lambda: reset_called.append(True))
    assert (device, out) == ("cpu", "recovered")
    assert seen == ["mps", "cpu"]  # tried the GPU once, then CPU
    assert reset_called == [True]  # the GPU-built model was dropped before retry


def test_failure_on_cpu_is_not_swallowed():
    def run(device):
        raise RuntimeError("genuine failure")

    with pytest.raises(RuntimeError, match="genuine failure"):
        fallback("diarisation", "cpu", run, lambda: None)
