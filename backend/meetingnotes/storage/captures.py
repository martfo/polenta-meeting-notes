"""The raw captures the app writes on Stop. Once the backend has copied a
recording into its meeting, the capture is a duplicate, so it is removed;
until then it is the only copy and is never touched.

A capture is only ever deleted when a file in a meeting folder is
byte-for-byte identical to it, so nothing that exists once is removed."""

from __future__ import annotations

import filecmp
import logging
from dataclasses import dataclass, field
from pathlib import Path

from meetingnotes.storage.vault import Vault

log = logging.getLogger("meetingnotes.captures")

MEETING_AUDIO_NAMES = ("audio.wav", "mic.wav", "system.wav")


def _in_captures(vault: Vault, path: Path) -> bool:
    try:
        return path.resolve().parent == vault.captures_dir.resolve()
    except OSError:
        return False


def release_capture(vault: Vault, capture: Path | str | None, stored: Path) -> bool:
    """Delete capture when it lies in the vault's captures folder and stored
    (its copy in the meeting) is identical to it. Anything else, an imported
    file from elsewhere or a copy that differs, is left alone. Returns whether
    it was deleted. Never raises: a capture left behind costs only space."""
    if capture is None:
        return False
    capture = Path(capture)
    try:
        if not (_in_captures(vault, capture) and capture.is_file() and stored.is_file()):
            return False
        if capture.stat().st_size != stored.stat().st_size:
            return False
        if not filecmp.cmp(capture, stored, shallow=False):
            return False
        capture.unlink()
        return True
    except OSError:
        log.warning("a capture could not be removed after import", exc_info=True)
        return False


@dataclass
class CaptureSweep:
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    bytes_freed: int = 0


def sweep_captures(vault: Vault) -> CaptureSweep:
    """Remove every capture already copied into a meeting: the duplicates left
    by versions that kept them. A capture with no identical copy (still waiting
    for the backend, or its meeting was deleted) is kept and reported."""
    result = CaptureSweep()
    if not vault.captures_dir.is_dir():
        return result
    by_size: dict[int, list[Path]] = {}
    if vault.meetings_dir.is_dir():
        for meeting_dir in vault.meetings_dir.iterdir():
            for name in MEETING_AUDIO_NAMES:
                f = meeting_dir / name
                if f.is_file():
                    by_size.setdefault(f.stat().st_size, []).append(f)
    for capture in sorted(vault.captures_dir.glob("*.wav")):
        try:
            size = capture.stat().st_size
            match = next((f for f in by_size.get(size, [])
                          if filecmp.cmp(capture, f, shallow=False)), None)
            if match is not None:
                capture.unlink()
                result.removed.append(capture.name)
                result.bytes_freed += size
            else:
                result.kept.append(capture.name)
        except OSError:
            result.kept.append(capture.name)
    return result
