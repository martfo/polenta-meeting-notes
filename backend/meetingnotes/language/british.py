"""The automatic American-to-British conversion.

Word-boundary, case-preserving, and it only ever changes words that are in
the bundled VarCon-derived map, so names, technical terms, and anything
inside a code span are left alone.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[1] / "resources" / "american_to_british.json"

# Inline code and fenced blocks are never rewritten.
CODE_SPAN = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)
WORD = re.compile(r"[A-Za-z]+")


@cache
def conversion_map() -> dict[str, str]:
    return json.loads(MAP_PATH.read_text())


def _match_case(replacement: str, original: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def convert_to_british(text: str) -> str:
    mapping = conversion_map()

    def convert_word(match: re.Match[str]) -> str:
        word = match.group(0)
        replacement = mapping.get(word.lower())
        return _match_case(replacement, word) if replacement else word

    parts = CODE_SPAN.split(text)
    for i, part in enumerate(parts):
        if not part.startswith("`"):
            parts[i] = WORD.sub(convert_word, part)
    return "".join(parts)
