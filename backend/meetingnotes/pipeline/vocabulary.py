"""Biasing Whisper towards the words a meeting actually contains.

Whisper leans on an optional initial prompt: text it treats as the transcript
so far, which nudges it towards that vocabulary. Feeding it the participant
names and a domain glossary rescues exactly the words a general model guesses
wrong on poor audio, turning "instructor" back into a name and "Misha" into
the person who was really speaking.
"""

from __future__ import annotations


def build_initial_prompt(names: list[str], glossary: list[str]) -> str | None:
    """A short prompt listing the meeting's people and domain terms, or None
    when there is nothing to bias towards. Order is preserved and duplicates
    (case-insensitively) are dropped so a name in the glossary is not repeated.
    """
    people = _clean(names)
    terms = [t for t in _clean(glossary) if t.casefold() not in {p.casefold() for p in people}]
    if not people and not terms:
        return None
    parts: list[str] = []
    if people:
        parts.append("Participants: " + ", ".join(people) + ".")
    if terms:
        parts.append("Terms: " + ", ".join(terms) + ".")
    return " ".join(parts)


def _clean(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        term = value.strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            cleaned.append(term)
    return cleaned
