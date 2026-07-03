"""The folder suggestion. The model must reply with strict JSON and nothing
else; the reply is parsed defensively and a malformed one falls back to no
suggestion. It never blocks saving."""

from __future__ import annotations

import json
from dataclasses import dataclass

from meetingnotes.llm.client import LMStudioClient
from meetingnotes.llm.errors import LMStudioUnavailable

SUGGESTION_PROMPT = (
    "Choose the best folder for this meeting from the existing list, or "
    "propose one new folder name if none fits. Reply with strict JSON and "
    'nothing else, in exactly this shape: {{"folder": "<name>", "is_new": '
    "<true or false>}}\n\nExisting folders: {folders}\n\nMeeting:\n{context}"
)


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
) -> FolderSuggestion | None:
    prompt = SUGGESTION_PROMPT.format(
        folders=json.dumps(existing_folders), context=meeting_context
    )
    try:
        reply = client.chat([{"role": "user", "content": prompt}])
    except LMStudioUnavailable:
        return None  # no suggestion; saving must never block on this
    return parse_suggestion(reply, existing_folders)
