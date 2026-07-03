"""Em dashes are removed from generated text before it is saved or shown."""

from __future__ import annotations

import re

EM_DASH = "—"

_BETWEEN_WORDS = re.compile(rf"(?<=[\w.,!?)\"'])[ \t]*{EM_DASH}+[ \t]*(?=[\w(\"'])")
_LINE_START = re.compile(rf"^[ \t]*{EM_DASH}+[ \t]*", re.MULTILINE)
_LEFTOVER = re.compile(rf"[ \t]*{EM_DASH}+[ \t]*")


def strip_em_dashes(text: str) -> str:
    """Deterministic removal: an em dash between words becomes a comma and a
    space, one opening a line becomes a plain list dash, and any leftover is
    dropped with its surrounding spaces collapsed."""
    text = _BETWEEN_WORDS.sub(", ", text)
    text = _LINE_START.sub("- ", text)
    text = _LEFTOVER.sub(" ", text)
    return text
