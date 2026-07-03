"""transcript.md in the fixed format pinned in DESIGN.md.

One turn per consecutive run of segments by the same speaker, a bold
[hh:mm:ss] timestamp and display name, the turn's text joined into one
paragraph, and one blank line between turns. The display name is the resolved
name where known, otherwise the diarised label.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from meetingnotes.pipeline.segments import Segment


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"[{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}]"


def group_turns(segments: Sequence[Segment]) -> list[tuple[float, str | None, str]]:
    turns: list[tuple[float, str | None, str]] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if turns and turns[-1][1] == seg.speaker:
            start, speaker, sofar = turns[-1]
            turns[-1] = (start, speaker, f"{sofar} {text}")
        else:
            turns.append((seg.start, seg.speaker, text))
    return turns


def render_transcript(
    segments: Sequence[Segment],
    display_names: Mapping[str, str] | None = None,
) -> str:
    names = display_names or {}
    lines = ["# Transcript", ""]
    for start, speaker, text in group_turns(segments):
        label = speaker or "Unknown speaker"
        shown = names.get(label, label)
        lines.append(f"**{format_timestamp(start)} {shown}**")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
