"""The British English pass for generated text, in the pinned order: the em
dash strip, then the automatic American-to-British conversion, then the
dictionary flag. Generated summary and chat text goes through this before it
is saved or shown. The user's own typed notes are never touched."""

from __future__ import annotations

from dataclasses import dataclass

from meetingnotes.language.british import convert_to_british
from meetingnotes.language.emdash import strip_em_dashes
from meetingnotes.language.flag import flag_unknown_words


@dataclass
class PassResult:
    text: str
    flags: list[str]


def british_pass(text: str, allowlist: set[str] | None = None) -> PassResult:
    text = strip_em_dashes(text)
    text = convert_to_british(text)
    return PassResult(text=text, flags=flag_unknown_words(text, allowlist))
