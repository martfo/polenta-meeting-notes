"""Section 1.6: single-meeting chat. Unit tier against a canned answer."""

from meetingnotes.llm.chat import ask_meeting
from meetingnotes.pipeline.segments import load_segments
from meetingnotes.storage.transcript import render_transcript
from tests.conftest import FIXTURES, FakeLMClient


def resolved_transcript() -> str:
    segments = load_segments(FIXTURES / "segments" / "two_speaker_meeting.json").segments
    return render_transcript(
        segments, {"SPEAKER_00": "Ben Adams", "SPEAKER_01": "Roger Neel"}
    )


def test_ac_1_6_a_question_sent_with_transcript_and_names():
    """The question goes out with the full transcript and resolved speaker
    names, so the model can attribute correctly."""
    client = FakeLMClient("An answer.")
    transcript = resolved_transcript()

    ask_meeting(client, "What did Ben say about the budget?", transcript)

    content = client.requests[0][-1]["content"]
    assert "What did Ben say about the budget?" in content
    assert transcript.strip() in content, "the whole transcript, not a fragment"
    assert "Ben Adams" in content and "Roger Neel" in content
    assert "SPEAKER_00" not in content, "names are resolved before sending"


def test_ac_1_6_b_canned_answer_rendered(fixtures_dir):
    """A canned answer comes back rendered against the meeting, through the
    British English pass."""
    canned = (fixtures_dir / "llm" / "chat_answer.md").read_text()
    client = FakeLMClient(canned)

    answer = ask_meeting(client, "What about the sensors?", resolved_transcript())

    assert "greenhouse sensors" in answer
    assert "—" not in answer
    assert "organised" in answer and "organized" not in answer
