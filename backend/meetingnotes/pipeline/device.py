"""Choosing the compute device for the PyTorch pipeline stages.

Transcription is deliberately excluded: it runs on faster-whisper, whose
CTranslate2 backend supports only CPU and CUDA, so it stays on CPU on Apple
Silicon whatever the hardware. The PyTorch stages, though -- pyannote
diarisation and embedding, and the wav2vec2 alignment -- do run on the Apple
GPU through Metal (MPS), where diarisation measured about twenty times faster
than CPU on real audio with identical speaker output.

Any op pyannote uses that the MPS backend has not implemented falls back to
CPU (PYTORCH_ENABLE_MPS_FALLBACK) rather than crashing, so enabling the GPU is
safe. Set MEETINGNOTES_FORCE_CPU=1 to force everything back onto the CPU.
"""

from __future__ import annotations

import os

# Read by the MPS backend when it meets an unimplemented op; set at import,
# before any pipeline op runs, so the fallback is always in effect.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def pipeline_device() -> str:
    """'mps' on Apple Silicon (unless forced off), else 'cpu'."""
    if os.environ.get("MEETINGNOTES_FORCE_CPU") == "1":
        return "cpu"
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"
