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


@pytest.fixture
def vectors():
    """The controlled embedding vectors for the enrolment tests."""
    import json

    import numpy as np

    raw = json.loads((FIXTURES / "embeddings" / "controlled_vectors.json").read_text())
    return {name: np.array(values) for name, values in raw.items()}


@pytest.fixture
def gallery(conn, vault):
    from meetingnotes.enrolment.gallery import Gallery

    return Gallery(conn, vault)


def make_meeting(conn, vault, meeting_id="2026-07-02_1400_client-review", title="Client review"):
    """A bare meeting row plus its folder on disk, for tests that need one."""
    from meetingnotes.storage import meetings as m

    vault.meeting_dir(meeting_id).mkdir(parents=True, exist_ok=True)
    m.create_meeting(
        conn, meeting_id, title=title, started_at="2026-07-02T14:00:00+01:00",
        vault_path=str(vault.meeting_dir(meeting_id)),
    )
    return meeting_id
