"""[live-smoke]: short runs against a real loaded model. On demand only:
make live-smoke. Each test skips itself when the real dependency is absent."""

import pytest

from meetingnotes.llm.client import LMStudioClient
from meetingnotes.pipeline.segments import load_segments
from meetingnotes.storage.transcript import render_transcript

pytestmark = pytest.mark.live_smoke


@pytest.fixture(scope="module")
def live_client():
    client = LMStudioClient()
    if client.status() != "ready":
        pytest.skip("LM Studio is not running with a loaded model")
    return client


@pytest.fixture(scope="module")
def transcript(fixtures_dir=None):
    from tests.conftest import FIXTURES

    segments = load_segments(FIXTURES / "segments" / "two_speaker_meeting.json").segments
    return render_transcript(
        segments, {"SPEAKER_00": "Ben Adams", "SPEAKER_01": "Roger Neel"}
    )


def test_ac_1_5_f_live_summary(live_client, transcript, repo_root):
    """A real loaded model produces a summary with the mandatory sections."""
    from meetingnotes.llm.summary import generate_summary_text

    prompt = (repo_root / "backend" / "meetingnotes" / "resources" / "summary_prompt.md").read_text()
    result = generate_summary_text(live_client, prompt, transcript, notes="")
    assert result.status == "ready", "both mandatory sections present"
    assert "—" not in result.body


def test_ac_1_6_c_live_chat_attribution(live_client, transcript):
    """A question about a named speaker is answered with the correct
    attribution."""
    from meetingnotes.llm.chat import ask_meeting

    answer = ask_meeting(
        live_client, "Who said the greenhouse sensors arrived, Ben or Roger?",
        transcript,
    )
    assert "Roger" in answer


def test_ac_x_c_live_model_download():
    """The one-time model download works: loading the Whisper model pulls and
    caches the weights. Needs the pipeline extra installed and network."""
    whisperx = pytest.importorskip("whisperx")
    model = whisperx.load_model("large-v3", "cpu", compute_type="int8", language="en")
    assert model is not None
