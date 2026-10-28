"""meeting.md: YAML front matter in the pinned key order, then the summary
body. Front matter round-trips through write and read."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

KEY_ORDER = [
    "id", "title", "date", "start_time", "duration_s", "source", "folder",
    "attendees", "speakers", "tags", "processing_status", "summary_status",
]


def render_meeting_md(front: dict[str, Any], body: str) -> str:
    ordered = {key: front[key] for key in KEY_ORDER if key in front}
    ordered.update({k: v for k, v in front.items() if k not in ordered})
    yaml_text = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True,
                               default_flow_style=False).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def write_meeting_md(path: Path, front: dict[str, Any], body: str) -> None:
    path.write_text(render_meeting_md(front, body))


def read_meeting_md(path: Path) -> tuple[dict[str, Any], str]:
    text = Path(path).read_text()
    if not text.startswith("---\n"):
        return {}, text
    _, front_text, body = text.split("---\n", 2)
    return yaml.safe_load(front_text) or {}, body.strip()
