"""The dictionary flag: the bundled en_GB Hunspell dictionary, read through
spylls, reports words it does not recognise without changing anything.

Flagging skips code spans, capitalised likely-names, and the technical
allowlist, so it does not nag about product names or jargon. Flags are shown
quietly and never block saving.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from meetingnotes.language.british import CODE_SPAN

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
DICTIONARY_PATH = RESOURCES / "dict" / "en_GB"
ALLOWLIST_PATH = RESOURCES / "technical_allowlist.txt"

WORD = re.compile(r"[A-Za-z][A-Za-z']*")


@cache
def _dictionary():
    from spylls.hunspell import Dictionary

    return Dictionary.from_files(str(DICTIONARY_PATH))


@cache
def default_allowlist() -> frozenset[str]:
    words = set()
    if ALLOWLIST_PATH.exists():
        for line in ALLOWLIST_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.add(line.lower())
    return frozenset(words)


def flag_unknown_words(text: str, allowlist: frozenset[str] | set[str] | None = None) -> list[str]:
    """Unknown words, in order of first appearance, unaltered."""
    allowed = default_allowlist() | {w.lower() for w in (allowlist or set())}
    dictionary = _dictionary()
    flags: list[str] = []
    seen: set[str] = set()
    for part in CODE_SPAN.split(text):
        if part.startswith("`"):
            continue
        for match in WORD.finditer(part):
            word = match.group(0)
            if word[0].isupper():
                continue  # a likely name
            key = word.lower()
            if key in allowed or key in seen:
                continue
            if not dictionary.lookup(word):
                flags.append(word)
            seen.add(key)
    return flags
