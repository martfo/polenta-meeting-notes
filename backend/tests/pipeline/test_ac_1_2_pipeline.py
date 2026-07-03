"""Section 1.2 [pipeline] tier: the real WhisperX and pyannote pipeline
against the fixture audio. Runs at phase boundaries, needs the models present
(uv sync --extra pipeline) and the Hugging Face token for the first download.
"""

import pytest

pytestmark = pytest.mark.pipeline


@pytest.fixture(scope="module")
def result(fixtures_dir):
    whisperx = pytest.importorskip("whisperx")  # noqa: F841
    from meetingnotes.pipeline.runner import PipelineRunner
    from meetingnotes.pipeline.whisperx_engine import WhisperXEngine
    from meetingnotes.storage.keychain import read_hf_token

    audio = fixtures_dir / "audio" / "two_speaker_meeting.wav"
    runner = PipelineRunner(WhisperXEngine(hf_token=read_hf_token()))
    aligned = runner.transcribe(audio)
    return runner.diarise(audio, aligned, expected_speakers=2)


def test_ac_1_2_a_segment_shape(result):
    """Segments each have start below end and non-empty text."""
    assert len(result.segments) >= 2
    for seg in result.segments:
        assert seg.start < seg.end
        assert seg.text.strip()


def test_ac_1_2_b_word_timestamps_monotonic(result):
    """Word-level timestamps are present and increase in order within each
    segment."""
    assert any(seg.words for seg in result.segments)
    for seg in result.segments:
        for earlier, later in zip(seg.words, seg.words[1:]):
            assert earlier.start <= later.start
            assert earlier.start <= earlier.end


def test_ac_1_2_c_two_speaker_labels(result):
    """At least two distinct speaker labels for the two-speaker fixture."""
    labels = {seg.speaker for seg in result.segments if seg.speaker}
    assert len(labels) >= 2


def test_ac_1_2_d_keyword_present(result):
    """A known keyword from the fixture transcript appears in the output.
    No exact transcript match."""
    text = " ".join(seg.text for seg in result.segments).lower()
    assert "hydroponics" in text
