"""The meeting vault on disk. Paths only; no policy.

Everything the app stores lives under one vault folder. FileVault provides
encryption at rest, so nothing is written outside the vault.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "meeting"


class Vault:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @property
    def db_path(self) -> Path:
        return self.root / "index.sqlite"

    @property
    def lancedb_dir(self) -> Path:
        return self.root / "lancedb"

    @property
    def speakers_dir(self) -> Path:
        return self.root / "speakers"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def settings_dir(self) -> Path:
        return self.root / "settings"

    @property
    def meetings_dir(self) -> Path:
        return self.root / "meetings"

    @property
    def config_path(self) -> Path:
        return self.settings_dir / "config.json"

    @property
    def summary_prompt_path(self) -> Path:
        return self.settings_dir / "summary_prompt.md"

    def ensure(self) -> "Vault":
        for d in (self.root, self.lancedb_dir, self.speakers_dir, self.logs_dir,
                  self.settings_dir, self.meetings_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def meeting_dir(self, meeting_id: str) -> Path:
        return self.meetings_dir / meeting_id

    def audio_path(self, meeting_id: str) -> Path:
        return self.meeting_dir(meeting_id) / "audio.wav"

    def transcript_path(self, meeting_id: str) -> Path:
        return self.meeting_dir(meeting_id) / "transcript.md"

    def meeting_md_path(self, meeting_id: str) -> Path:
        return self.meeting_dir(meeting_id) / "meeting.md"

    def notes_path(self, meeting_id: str) -> Path:
        return self.meeting_dir(meeting_id) / "notes.md"

    def assets_dir(self, meeting_id: str) -> Path:
        return self.meeting_dir(meeting_id) / "assets"

    def new_meeting_id(self, started_at: datetime, title: str) -> str:
        base = f"{started_at:%Y-%m-%d_%H%M}_{slugify(title)}"
        candidate, n = base, 2
        while self.meeting_dir(candidate).exists():
            candidate = f"{base}-{n}"
            n += 1
        return candidate
