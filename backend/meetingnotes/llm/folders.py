"""The folder suggestion. The model must reply with strict JSON and nothing
else; the reply is parsed defensively and a malformed one falls back to no
suggestion. It never blocks saving."""

from __future__ import annotations

import json
from dataclasses import dataclass

from meetingnotes.llm.client import LMStudioClient
from meetingnotes.llm.errors import LMStudioUnavailable

SUGGESTION_PROMPT = (
    "Suggest which folder this meeting belongs in. Strongly prefer an existing "
    "folder from the list: choose one whenever the meeting plausibly fits it, "
    "matching on the client, project, team, or topic. To decide, look at how "
    "meetings have already been filed: each folder below lists example titles "
    "of meetings already in it, so match this meeting to the folder whose "
    "existing titles are most like it. Only propose a new folder when none of "
    "the existing ones fit, and then give it a short, general name (a client, "
    "project, or team name), not the meeting's title. "
    "Reply with strict JSON and nothing else, in exactly this shape: "
    '{{"folder": "<name>", "is_new": <true or false>}}\n\n'
    "Existing folders and example titles already filed in each:\n{folders}\n\n"
    "Meeting:\n{context}"
)


def _format_folders(existing_folders: list[str], examples: dict[str, list[str]]) -> str:
    """Each folder on its own line with the example titles already filed in it,
    so the model can match on the pattern of past filing, not just the name."""
    lines = []
    for name in existing_folders:
        titles = examples.get(name) or []
        if titles:
            lines.append(f"- {name}: " + "; ".join(titles))
        else:
            lines.append(f"- {name}: (no meetings filed yet)")
    return "\n".join(lines) if lines else "(none yet)"


@dataclass
class FolderSuggestion:
    folder: str
    is_new: bool


def parse_suggestion(reply: str, existing_folders: list[str]) -> FolderSuggestion | None:
    """A suggestion is only usable if it parses and names either an existing
    folder or a new one marked as new."""
    try:
        data = json.loads(reply.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    folder = data.get("folder")
    is_new = data.get("is_new")
    if not isinstance(folder, str) or not folder.strip() or not isinstance(is_new, bool):
        return None
    folder = folder.strip()
    if folder in existing_folders:
        return FolderSuggestion(folder=folder, is_new=False)
    if is_new:
        return FolderSuggestion(folder=folder, is_new=True)
    return None


def suggest_folder(
    client: LMStudioClient, existing_folders: list[str], meeting_context: str,
    folder_examples: dict[str, list[str]] | None = None,
) -> FolderSuggestion | None:
    prompt = SUGGESTION_PROMPT.format(
        folders=_format_folders(existing_folders, folder_examples or {}),
        context=meeting_context,
    )
    try:
        reply = client.chat([{"role": "user", "content": prompt}])
    except LMStudioUnavailable:
        return None  # no suggestion; saving must never block on this
    return parse_suggestion(reply, existing_folders)
