"""AC-X-a: the offline guarantee. With all non-loopback network blocked, the
full Phase 1 flow (import, transcribe, diarise, enrich, embed, summarise,
notes with OCR) completes on fixtures, and any attempted outside connection
fails the test."""

import json
import socket

import httpx
import pytest

from meetingnotes.config import default_config
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.jobs.importer import import_wav
from meetingnotes.jobs.stages import build_stages
from meetingnotes.jobs.worker import Worker
from meetingnotes.llm.client import LMStudioClient
from meetingnotes.notes.notes import paste_image, write_notes
from meetingnotes.notes.ocr import VisionOcr
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import read_meeting_md

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def network_guard(monkeypatch):
    """Every connect to a non-loopback address is recorded and refused."""
    attempts: list[str] = []
    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in LOOPBACK:
            attempts.append(host)
            raise OSError(f"blocked outbound connection to {host}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    return attempts


class FixtureEngine:
    """The recorded pipeline output instead of a WhisperX run."""

    def __init__(self, segments_file):
        self.data = json.loads(segments_file.read_text())

    def transcribe(self, audio_path, language, initial_prompt=None):
        return {"segments": [dict(s, speaker=None) for s in self.data["segments"]]}

    def align(self, result, audio_path, language, model_name):
        return result

    def diarise(self, audio_path, num_speakers):
        return "diarisation"

    def assign_speakers(self, diarisation, aligned):
        return {"segments": self.data["segments"]}


class FixtureSpeakerEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors

    def cluster_voiceprints(self, audio_path, segments):
        return {
            "SPEAKER_00": self.vectors["ben_positive_1"],
            "SPEAKER_01": self.vectors["roger_positive_1"],
        }


def test_ac_x_a_offline_guarantee(network_guard, conn, vault, vectors, fixtures_dir):
    summary_fixture = (fixtures_dir / "llm" / "summary_ok.md").read_text()

    def local_lmstudio(request):
        assert request.url.host == "127.0.0.1"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": summary_fixture}}]
        })

    lm_client = LMStudioClient(http=httpx.Client(transport=httpx.MockTransport(local_lmstudio)))

    config = default_config(vault.root)
    gallery = Gallery(conn, vault)
    ben = gallery.ensure_speaker("Ben Adams")
    gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])

    stages = build_stages(
        conn, vault, config,
        engine=FixtureEngine(fixtures_dir / "segments" / "two_speaker_meeting.json"),
        speaker_embedder=FixtureSpeakerEmbedder(vectors),
        lm_client=lm_client,
        ocr_engine=VisionOcr(),
    )

    meeting_id = import_wav(
        conn, vault, fixtures_dir / "audio" / "two_speaker_meeting.wav",
        title="Offline meeting",
    )
    write_notes(vault, meeting_id, "My own note about the budget.\n")
    paste_image(vault, meeting_id, (fixtures_dir / "images" / "ocr_sample.png").read_bytes())

    Worker(conn, stages).run_pending()

    row = m.get_meeting(conn, meeting_id)
    assert row["processing_status"] == "ready"
    assert row["summary_status"] == "ready"

    transcript = vault.transcript_path(meeting_id).read_text()
    assert "Ben Adams" in transcript, "enrolment resolved the known voice"
    assert "SPEAKER_01" in transcript, "the unknown voice keeps its label"

    front, body = read_meeting_md(vault.meeting_md_path(meeting_id))
    assert front["id"] == meeting_id
    assert "## Core items discussed" in body and "—" not in body

    assert network_guard == [], f"outbound connections attempted: {network_guard}"
