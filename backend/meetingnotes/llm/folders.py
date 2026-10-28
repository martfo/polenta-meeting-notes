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
    "folder from the list below: choose the one whose already-filed meeting "
    "titles are most like this meeting, matching on the client, project, team, "
    "or topic. When in doubt, pick the closest existing folder rather than "
    "inventing a new one. Only propose a new folder if the meeting clearly "
    "belongs to a specific client, project, or team that is not already listed, "
    "and then name it after that client, project, or team (not the meeting's "
    "title). Never invent a generic catch-all folder such as General, "
    "Miscellaneous, Other, Uncategorized, Meetings, or Notes. "
    "Reply with strict JSON and nothing else, in exactly this shape: "
    '{{"folder": "<name>", "is_new": <true or false>}}\n\n'
    "Existing folders and example titles already filed in each:\n{folders}\n\n"
    "Meeting:\n{context}"
)

# Generic catch-all names never make a useful new folder; if the model proposes
# one anyway it is dropped rather than offered. An existing folder with such a
# name is still fine to suggest.
_GENERIC_NEW_FOLDERS = {
    "general", "miscellaneous", "misc", "other", "others", "uncategorized",
    "uncategorised", "meetings", "meeting", "notes", "various", "unsorted",
    "inbox", "default", "untitled",
}


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
    if is_new and folder.lower() not in _GENERIC_NEW_FOLDERS:
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
