"""Cutting a meeting into passages for library search.

A passage has to carry enough context to answer a question on its own. The
first version stored one passage per speaker turn, which averaged about 20
words: a turn that only named the subject of a question was retrieved first but
said nothing about what was asked, and one-word turns ("issue.", "problem.")
crowded out the rest. Now:

- the transcript is cut into runs of consecutive turns of about 150 words,
  never splitting a turn unless it alone is too long, with each speaker named
  inline so the passage still says who said what;
- the summary is searchable too, one passage per section, because it states
  outcomes and actions in a sentence where the transcript spreads them over
  minutes;
- the user's notes are searchable, cut on paragraphs.

Each passage carries its source and its order within that source, so a hit
can be widened with the passages either side of it when answering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from meetingnotes.pipeline.segments import Segment
from meetingnotes.storage.transcript import group_turns

# A run of turns closes once it reaches the target; a single turn longer than
# the maximum is split on its own. Around 150 words is a minute of speech:
# enough to hold one exchange, small enough to stay on one topic.
TARGET_WORDS = 150
MAX_WORDS = 220
# A run of turns shorter than this is filler ("Yeah.", "Okay, thanks."): it is
# merged into the passage beside it rather than indexed on its own. Summary and
# notes passages this short are not indexed.
MIN_WORDS = 8

SOURCE_TRANSCRIPT = "transcript"
SOURCE_SUMMARY = "summary"
SOURCE_NOTES = "notes"
SOURCE_IMAGE = "image"


@dataclass
class Chunk:
    text: str
    speaker: str
    start_s: float
    end_s: float
    source: str = SOURCE_TRANSCRIPT
    # Order within its source in this meeting, for widening a hit with its
    # neighbours.
    seq: int = 0


def chunk_segments(segments: Sequence[Segment],
                   display_names: dict[str, str] | None = None) -> list[Chunk]:
    """The transcript as runs of consecutive turns."""
    names = display_names or {}
    turns = []
    for (start, speaker, text), end in zip(group_turns(segments), _turn_spans(segments)):
        label = speaker or "Unknown speaker"
        turns.extend(_split_long_turn(names.get(label, label), text, start, end))

    chunks: list[Chunk] = []
    run: list[tuple[str, str, float, float]] = []
    words = 0

    def close() -> None:
        nonlocal run, words
        if run:
            speakers = list(dict.fromkeys(speaker for speaker, _, _, _ in run))
            chunks.append(Chunk(
                text="\n".join(f"{speaker}: {text}" for speaker, text, _, _ in run),
                speaker=", ".join(speakers),
                start_s=run[0][2],
                end_s=run[-1][3],
                seq=len(chunks),
            ))
        run, words = [], 0

    for speaker, text, start, end in turns:
        count = len(text.split())
        # Close before a turn that would overflow the run, unless the run is
        # still filler-sized: then the turn joins it, so no passage is ever
        # just "Yeah." on its own.
        if run and words + count > MAX_WORDS and words >= MIN_WORDS:
            close()
        run.append((speaker, text, start, end))
        words += count
        if words >= TARGET_WORDS:
            close()
    if run:
        if words < MIN_WORDS and chunks:
            # A short last exchange belongs with what came before it.
            last = chunks.pop()
            tail = "\n".join(f"{speaker}: {text}" for speaker, text, _, _ in run)
            speakers = list(dict.fromkeys(
                last.speaker.split(", ") + [speaker for speaker, _, _, _ in run]))
            chunks.append(Chunk(text=f"{last.text}\n{tail}", speaker=", ".join(speakers),
                                start_s=last.start_s, end_s=run[-1][3], seq=last.seq))
            run = []
        else:
            close()  # also a meeting that is short as a whole: one passage
    return chunks


def _split_long_turn(speaker: str, text: str, start: float, end: float):
    words = text.split()
    if len(words) <= MAX_WORDS:
        return [(speaker, text, start, end)]
    pieces = []
    step = TARGET_WORDS
    for offset in range(0, len(words), step):
        # Spread the turn's time evenly over its pieces; close enough for a
        # citation's timestamp.
        fraction = offset / len(words)
        piece_start = start + (end - start) * fraction
        pieces.append((speaker, " ".join(words[offset:offset + step]), piece_start, end))
    return pieces


def _turn_spans(segments: Sequence[Segment]) -> list[float]:
    """End time of each turn, in the same order group_turns yields them."""
    ends: list[float] = []
    last_speaker: object = object()
    for seg in segments:
        if not seg.text.strip():
            continue
        if seg.speaker == last_speaker and ends:
            ends[-1] = seg.end
        else:
            ends.append(seg.end)
            last_speaker = seg.speaker
    return ends


_SECTION = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)


def chunk_summary(body: str, title: str = "") -> list[Chunk]:
    """The summary, one passage per section (a long section split on its
    paragraphs and bullets). Each passage is prefixed with the meeting title
    and section heading, so a passage read alone still says what it is about.

    A placeholder body (an italic line such as "_Imported transcript; the
    summary is being written._") or one too short to hold anything is not
    indexed."""
    body = body.strip()
    if not body or len(body.split()) < MIN_WORDS or _is_placeholder(body):
        return []
    heads = list(_SECTION.finditer(body))
    sections: list[tuple[str, str]] = []
    if not heads:
        sections.append(("", body))
    else:
        if body[:heads[0].start()].strip():
            sections.append(("", body[:heads[0].start()]))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            sections.append((head.group(1).strip(), body[head.end():end]))

    chunks: list[Chunk] = []
    for heading, text in sections:
        for piece in _pack_paragraphs(text):
            label = " - ".join(part for part in (title, heading) if part)
            prefix = f"Summary ({label}):\n" if label else "Summary:\n"
            chunks.append(Chunk(text=prefix + piece, speaker="Summary",
                                start_s=0.0, end_s=0.0, source=SOURCE_SUMMARY,
                                seq=len(chunks)))
    return chunks


def chunk_notes(text: str) -> list[Chunk]:
    """The user's own notes, packed on paragraphs into passages."""
    return [
        Chunk(text=piece, speaker="Your notes", start_s=0.0, end_s=0.0,
              source=SOURCE_NOTES, seq=i)
        for i, piece in enumerate(_pack_paragraphs(text))
    ]


def _is_placeholder(body: str) -> bool:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return len(lines) == 1 and lines[0].startswith("_") and lines[0].endswith("_")


def _pack_paragraphs(text: str) -> list[str]:
    """Paragraphs and bullet lines packed into passages of up to about
    TARGET_WORDS, never splitting a line; a passage under MIN_WORDS is
    dropped unless it is all there is."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    units: list[str] = []
    paragraph: list[str] = []
    for line in lines + [""]:
        bullet = re.match(r"^\s*([-*+]|\d+[.)])\s+", line)
        if not line.strip() or bullet:
            if paragraph:
                units.append(" ".join(paragraph))
                paragraph = []
            if bullet:
                units.append(line.strip())
            continue
        paragraph.append(line.strip())

    pieces: list[str] = []
    current: list[str] = []
    words = 0
    for unit in units:
        count = len(unit.split())
        if current and words + count > TARGET_WORDS:
            pieces.append("\n".join(current))
            current, words = [], 0
        current.append(unit)
        words += count
    if current:
        pieces.append("\n".join(current))
    kept = [p for p in pieces if len(p.split()) >= MIN_WORDS]
    return kept or ([pieces[0]] if pieces and len(pieces[0].split()) >= 3 else [])
