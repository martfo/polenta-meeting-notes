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
    names, so the model can attribute correctly. Follow-up turns keep the
    same context."""
    client = FakeLMClient("An answer.")
    transcript = resolved_transcript()

    ask_meeting(client, "What did Ben say about the budget?", transcript)

    sent = client.requests[0]
    everything = "\n".join(message["content"] for message in sent)
    assert sent[-1]["content"] == "What did Ben say about the budget?"
    assert transcript.strip() in everything, "the whole transcript, not a fragment"
    assert "Ben Adams" in everything and "Roger Neel" in everything
    assert "SPEAKER_00" not in everything, "names are resolved before sending"

    # A follow-up carries the history and still has the full transcript.
    ask_meeting(client, "And what about Roger?", transcript,
                history=[{"question": "What did Ben say about the budget?",
                          "answer": "He covered the sensors."}])
    followup = client.requests[1]
    assert transcript.strip() in followup[0]["content"]
    assert [m["role"] for m in followup] == ["system", "user", "assistant", "user"]
    assert followup[-1]["content"] == "And what about Roger?"


def test_ac_1_6_b_canned_answer_rendered(fixtures_dir):
    """A canned answer comes back rendered against the meeting, through the
    British English pass."""
    canned = (fixtures_dir / "llm" / "chat_answer.md").read_text()
    client = FakeLMClient(canned)

    answer = ask_meeting(client, "What about the sensors?", resolved_transcript())

    assert "greenhouse sensors" in answer
    assert "—" not in answer
    assert "organised" in answer and "organized" not in answer
