"""Turning a written transcript into segments.

Two shapes of text arrive here. A Granola CSV cell is plain lines. A dropped
markdown file is a document: it may carry YAML front matter, a title heading,
and turns written either as this app's own transcript.md format
(``**[00:01:02] Ben Adams**`` then the words on the following lines) or as the
plain ``Ben Adams: ...`` lines most other tools export.

Both end up as the same Segment list the audio pipeline produces, so an
imported transcript summarises, indexes, and chats exactly like a recording.
Where the text carries no timestamps the turns get monotonic synthetic ones,
so the rendered transcript still reads tidily.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yaml

from meetingnotes.pipeline.segments import Segment

# A leading timestamp and a "Speaker: text" opening, both optional.
_TURN = re.compile(
    r"^\s*(?:\[?(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?"
    r"(?:(?P<speaker>[A-Z][\w .'\-]{0,39}?):\s+)?(?P<text>\S.*)$"
)

# A whole line that is only a bold speaker heading, as this app writes it:
# "**[00:01:02] Ben Adams**", or "**Ben Adams**" / "**Ben Adams:**" from other
# tools. The trailing text group catches "**Ben Adams:** hello" on one line.
_BOLD_HEADING = re.compile(
    r"^\s*\*\*\s*(?:\[?(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?"
    r"(?P<speaker>[^*]+?)\s*:?\s*\*\*\s*:?\s*(?P<text>.*)$"
)

_HEADING = re.compile(r"^\s{0,3}(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
# Bullet, quote, and numbered-list markers stripped from the front of a line.
_MARKER = re.compile(r"^\s*(?:[-*+]\s+|>\s?|\d{1,3}[.)]\s+)")
_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")


def _ts_to_seconds(ts: str) -> float:
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_transcript(text: str) -> list[Segment]:
    """Parse a plain-line transcript into segments. Recognises optional
    leading timestamps and 'Speaker: text' turns; falls back to plain
    paragraphs."""
    if not text or not text.strip():
        return []
    segments: list[Segment] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _TURN.match(line)
        if not match:
            continue
        speaker = (match.group("speaker") or "").strip() or None
        body = match.group("text").strip()
        ts = match.group("ts")
        start = _ts_to_seconds(ts) if ts else float(len(segments))
        if segments and speaker == segments[-1].speaker and ts is None:
            segments[-1] = segments[-1].model_copy(
                update={"text": segments[-1].text + " " + body, "end": start + 1})
        else:
            segments.append(Segment(start=start, end=start + 1, speaker=speaker, text=body))
    return segments


# -- markdown documents ---------------------------------------------------


@dataclass
class ParsedTranscript:
    """What a transcript document yielded: its turns, and the title, date, and
    attendees it named, where it named them."""

    segments: list[Segment] = field(default_factory=list)
    title: str | None = None
    started_at: datetime | None = None
    attendees: list[str] = field(default_factory=list)
    front: dict[str, Any] = field(default_factory=dict)


_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(?P<front>.*?)\n---[ \t]*(?:\n|\Z)(?P<body>.*)\Z",
                           re.DOTALL)


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """YAML front matter and the body after it. Text without front matter, or
    with front matter that is not a mapping or does not parse, is all body:
    a transcript is never rejected over its header."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    match = _FRONT_MATTER.match(text)
    if match is None:
        return {}, text
    try:
        front = yaml.safe_load(match.group("front"))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(front, dict):
        return {}, text
    return front, match.group("body")


# Lowercase words that legitimately sit inside a name.
_NAME_PARTICLES = {"van", "von", "de", "der", "den", "di", "da", "du", "la",
                   "le", "bin", "al", "of", "the"}


def _plausible_speaker(name: str) -> bool:
    """A speaker label, not a sentence that happens to contain a colon.

    Names are short, unpunctuated, and capitalised: "Ben Adams", "Speaker 2",
    "Ben van Dijk". A line opening "One thing to remember: ..." is prose and
    keeps its words.
    """
    name = name.strip()
    words = name.split()
    if not words or len(name) > 40 or len(words) > 4:
        return False
    if any(ch in name for ch in ".!?"):
        return False
    if not any(ch.isalpha() for ch in name):
        return False
    return all(
        word[0].isupper() or word[0].isdigit() or word.lower() in _NAME_PARTICLES
        for word in words
    )


def _parse_date(value: Any) -> datetime | None:
    """A date from front matter, as a local, timezone-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    if hasattr(value, "year") and hasattr(value, "month") and not isinstance(value, str):
        return datetime(value.year, value.month, value.day).astimezone()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.astimezone()
    return None


def _attendees(front: dict[str, Any]) -> list[str]:
    for key in ("attendees", "participants", "people", "speakers"):
        value = front.get(key)
        if isinstance(value, str):
            return [p.strip() for p in re.split(r"[;,\n]", value) if p.strip()]
        if isinstance(value, list):
            names = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
                elif isinstance(item, dict) and str(item.get("name", "")).strip():
                    names.append(str(item["name"]).strip())
            if names:
                return names
    return []


class _TurnBuilder:
    """Accumulates turns, joining continuation lines onto the open one."""

    def __init__(self) -> None:
        self.segments: list[Segment] = []

    def _next_start(self) -> float:
        return self.segments[-1].end if self.segments else 0.0

    def open(self, speaker: str | None, ts: str | None, text: str) -> None:
        start = _ts_to_seconds(ts) if ts else self._next_start()
        # A run of lines from the same untimed speaker is one turn, exactly as
        # the audio pipeline groups consecutive segments.
        if (self.segments and ts is None and speaker is not None
                and speaker == self.segments[-1].speaker):
            self.append(text)
            return
        self.segments.append(Segment(start=start, end=start + 1, speaker=speaker, text=text))

    def append(self, text: str) -> None:
        if not self.segments:
            self.open(None, None, text)
            return
        last = self.segments[-1]
        self.segments[-1] = last.model_copy(update={"text": f"{last.text} {text}".strip()})


def parse_markdown_transcript(text: str) -> ParsedTranscript:
    """Parse a written transcript document into segments plus whatever title,
    date, and attendees it declared.

    Understood, in order of preference: YAML front matter; a level-one heading
    as the title; this app's ``**[00:01:02] Name**`` turn headings; plain
    ``Name: text`` (with an optional leading timestamp) lines; and, failing all
    of that, the prose itself as a single unattributed turn. Bullets, block
    quotes, and horizontal rules are stripped; other headings are dropped."""
    front, body = split_front_matter(text)
    result = ParsedTranscript(front=front)

    for key in ("title", "name", "subject", "meeting"):
        value = front.get(key)
        if isinstance(value, str) and value.strip():
            result.title = value.strip()
            break
    for key in ("date", "started_at", "start_time", "created", "datetime"):
        if key in front:
            parsed = _parse_date(front[key])
            if parsed:
                result.started_at = parsed
                break
    result.attendees = _attendees(front)

    builder = _TurnBuilder()
    # An explicitly headed transcript section (## Transcript) means the prose
    # before it is preamble, not speech, so the turns collected so far are
    # dropped and only the section is read.
    in_transcript_section = False
    saw_transcript_section = False

    for raw_line in body.split("\n"):
        line = raw_line.rstrip()
        if not line.strip() or _RULE.match(line):
            continue

        heading = _HEADING.match(line)
        if heading:
            heading_text = heading.group("text").strip()
            if re.fullmatch(r"(?:full )?transcript", heading_text, re.IGNORECASE):
                in_transcript_section = True
                saw_transcript_section = True
                builder = _TurnBuilder()
                continue
            if saw_transcript_section:
                in_transcript_section = False
            if len(heading.group("hashes")) == 1 and result.title is None:
                result.title = heading_text
            continue
        if saw_transcript_section and not in_transcript_section:
            continue

        bold = _BOLD_HEADING.match(line)
        if bold and _plausible_speaker(bold.group("speaker")):
            builder.open(bold.group("speaker").strip(), bold.group("ts"),
                         bold.group("text").strip())
            continue

        stripped = _MARKER.sub("", line).strip()
        if not stripped:
            continue
        turn = _TURN.match(stripped)
        if turn is None:
            builder.append(stripped)
            continue
        speaker = (turn.group("speaker") or "").strip() or None
        if speaker is not None and not _plausible_speaker(speaker):
            speaker, ts = None, turn.group("ts")
            builder.append(stripped if ts is None else turn.group("text").strip())
            continue
        body_text = turn.group("text").strip()
        if speaker is None and turn.group("ts") is None:
            builder.append(body_text)
        else:
            builder.open(speaker, turn.group("ts"), body_text)

    # A turn that opened with no text of its own (a speaker heading at the end
    # of the file) carries nothing.
    result.segments = [s for s in builder.segments if s.text.strip()]
    return result


def transcript_duration_s(segments: list[Segment]) -> int | None:
    """The last turn's end, where the text carried real timestamps. Synthetic
    ones say nothing about how long the meeting was, so they give no duration."""
    if not segments:
        return None
    last = segments[-1]
    # Synthetic starts step by one second a turn; a real transcript's last turn
    # is far beyond that.
    if last.end <= len(segments) + 1:
        return None
    return int(last.end)
