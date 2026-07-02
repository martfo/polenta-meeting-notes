from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from meetingnotes.storage.db import open_db
from meetingnotes.storage.vault import Vault

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "MeetingVault").ensure()


@pytest.fixture
def conn(vault: Vault):
    connection = open_db(vault.db_path)
    yield connection
    connection.close()


class RecordingStages(dict):
    """A fake fast pipeline: every stage records its call and succeeds.

    Individual stages can be replaced to raise, block, or record more.
    """

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, str]] = []
        from meetingnotes.jobs.queue import STAGES
        for stage in STAGES:
            self[stage] = self._make(stage)

    def _make(self, stage: str):
        def run(meeting_id: str) -> None:
            self.calls.append((stage, meeting_id))
        return run


@pytest.fixture
def stages() -> RecordingStages:
    return RecordingStages()
