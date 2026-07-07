"""Silent recordings must not be transcribed or summarised into nonsense."""

import wave

import numpy as np

from meetingnotes.llm.summary import (
    MIN_SPEECH_WORDS,
    NO_SPEECH_BODY,
    summarise_meeting,
    transcript_word_count,
)
from meetingnotes.pipeline.silence import audio_rms, is_silent
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import read_meeting_md
from tests.conftest import FakeLMClient, make_meeting


def _write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.asarray(samples, dtype=np.int16).tobytes())


def test_silence_detection(tmp_path):
    """A quiet recording is silent; a loud one is not."""
    quiet = tmp_path / "quiet.wav"
    _write_wav(quiet, np.zeros(16000))
    assert is_silent(quiet)
    assert audio_rms(quiet) == 0.0

    # Faint room tone, still below the threshold.
    faint = tmp_path / "faint.wav"
    _write_wav(faint, (np.random.default_rng(0).normal(0, 20, 16000)))
    assert is_silent(faint)

    # Speech-level amplitude is not silent.
    loud = tmp_path / "loud.wav"
    _write_wav(loud, (np.sin(np.linspace(0, 2000, 16000)) * 8000))
    assert not is_silent(loud)


def test_transcript_word_count_ignores_headers():
    transcript = (
        "# Transcript\n\n"
        "**[00:00:04] Ben Adams**\n"
        "We reviewed the hydroponics budget today.\n"
    )
    assert transcript_word_count(transcript) == 6
    assert transcript_word_count("# Transcript\n") == 0


def test_empty_transcript_is_not_summarised(conn, vault):
    """A recording with no speech gets a plain note, and the model is never
    called, so it cannot invent a summary."""
    meeting_id = make_meeting(conn, vault)
    client = FakeLMClient("A fabricated summary the model should never write.")

    result = summarise_meeting(conn, vault, client, meeting_id, "# Transcript\n", notes="")

    assert result.body == NO_SPEECH_BODY
    assert client.requests == [], "the model was not asked"
    front, body = read_meeting_md(vault.meeting_md_path(meeting_id))
    assert body == NO_SPEECH_BODY
    assert m.get_meeting(conn, meeting_id)["summary_status"] == "ready"


def test_notes_alone_still_summarise(conn, vault):
    """If there is no speech but the user typed notes, those are worth
    summarising, so the model is used."""
    meeting_id = make_meeting(conn, vault)
    vault.summary_prompt_path.write_text("prompt")
    client = FakeLMClient("## Core items discussed\n\nFrom notes.\n\n## Next Steps\n\n- Do it.")

    result = summarise_meeting(conn, vault, client, meeting_id, "# Transcript\n",
                               notes="Important typed note about the budget decision.")

    assert result.body != NO_SPEECH_BODY
    assert client.requests, "the model was asked because there were notes"


def test_real_transcript_is_summarised(conn, vault):
    """A transcript with real speech goes to the model as normal."""
    meeting_id = make_meeting(conn, vault)
    vault.summary_prompt_path.write_text("prompt")
    client = FakeLMClient("## Core items discussed\n\nX.\n\n## Next Steps\n\n- Y.")
    transcript = ("# Transcript\n\n**[00:00:01] Ben**\n"
                  + "We discussed the budget and the timeline and the plan in detail today.\n")
    assert transcript_word_count(transcript) >= MIN_SPEECH_WORDS

    result = summarise_meeting(conn, vault, client, meeting_id, transcript)
    assert result.body != NO_SPEECH_BODY
    assert client.requests
