"""Device selection for the PyTorch pipeline stages."""

from __future__ import annotations

import importlib

import pytest


def _fresh_module():
    import meetingnotes.pipeline.device as device
    return importlib.reload(device)


def test_force_cpu_env_wins(monkeypatch):
    monkeypatch.setenv("MEETINGNOTES_FORCE_CPU", "1")
    device = _fresh_module()
    assert device.pipeline_device() == "cpu"


def test_device_is_cpu_or_mps(monkeypatch):
    monkeypatch.delenv("MEETINGNOTES_FORCE_CPU", raising=False)
    device = _fresh_module()
    assert device.pipeline_device() in {"cpu", "mps"}


def test_mps_fallback_is_enabled_on_import(monkeypatch):
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)
    _fresh_module()
    import os
    # Importing the module sets the fallback so an unimplemented MPS op runs on
    # CPU rather than crashing pyannote.
    assert os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"
