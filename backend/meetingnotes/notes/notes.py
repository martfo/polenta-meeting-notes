"""The notes pane's storage: notes.md beside the transcript, pasted images in
the meeting's assets folder with relative links. Typed notes feed the summary
and are never rewritten by the British English pass."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from meetingnotes.storage.vault import Vault

IMAGE_LINK = re.compile(r"!\[[^\]]*\]\((assets/[^)]+)\)")


def read_notes(vault: Vault, meeting_id: str) -> str:
    path = vault.notes_path(meeting_id)
    return path.read_text() if path.exists() else ""


def write_notes(vault: Vault, meeting_id: str, text: str) -> None:
    vault.meeting_dir(meeting_id).mkdir(parents=True, exist_ok=True)
    vault.notes_path(meeting_id).write_text(text)


def paste_image(vault: Vault, meeting_id: str, image_bytes: bytes,
                suffix: str = "png", append: bool = True) -> str:
    """Save a pasted image into assets/ and, with `append`, add a relative
    link to the end of notes.md. The app shows images inline where they were
    pasted, so it places the link itself and passes append=False. Returns the
    relative path."""
    assets = vault.assets_dir(meeting_id)
    assets.mkdir(parents=True, exist_ok=True)
    name = f"pasted-{uuid.uuid4().hex[:12]}.{suffix}"
    (assets / name).write_bytes(image_bytes)
    relative = f"assets/{name}"
    if not append:
        return relative

    notes = read_notes(vault, meeting_id)
    if notes and not notes.endswith("\n"):
        notes += "\n"
    notes += f"![pasted image]({relative})\n"
    write_notes(vault, meeting_id, notes)
    return relative


# The display width the app keeps in an image's alt text, Obsidian style:
# ![pasted image|320](assets/x.png).
_IMAGE_WIDTH = re.compile(r"(!\[[^\]]*?)\|\d+(?:x\d+)?(\]\(assets/)")


def without_image_sizes(text: str) -> str:
    """The notes with image display widths taken out, so a change that only
    resizes an image can be told apart from a change to what was written."""
    return _IMAGE_WIDTH.sub(r"\1\2", text)


def linked_images(vault: Vault, meeting_id: str) -> list[Path]:
    """The pasted images referenced from notes.md, resolved to files."""
    meeting_dir = vault.meeting_dir(meeting_id)
    paths = []
    for match in IMAGE_LINK.finditer(read_notes(vault, meeting_id)):
        path = meeting_dir / match.group(1)
        if path.exists():
            paths.append(path)
    return paths
