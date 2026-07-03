"""Section 1.2: transcription and diarisation. Unit tier: pass-through of the
settings that matter and the fixed transcript.md format."""

from pathlib import Path

from meetingnotes.pipeline.runner import ENGLISH_ALIGNMENT_MODEL, PipelineRunner
from meetingnotes.pipeline.segments import load_segments
from meetingnotes.storage.transcript import render_transcript

FIXTURE_SEGMENTS = Path(__file__).resolve().parents[3] / "fixtures" / "segments" / "two_speaker_meeting.json"


class RecordingEngine:
    """Records every call; returns minimal well-shaped results."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._segments = [
            {"start": 0.5, "end": 2.0, "text": "Hello there.", "words": []},
        ]

    def transcribe(self, audio_path, language):
        self.calls.append(("transcribe", language))
        return {"segments": self._segments, "language": language}

    def align(self, result, audio_path, language, model_name):
        self.calls.append(("align", language, model_name))
        return result

    def diarise(self, audio_path, num_speakers):
        self.calls.append(("diarise", num_speakers))
        return "diarisation"

    def assign_speakers(self, diarisation, aligned):
        self.calls.append(("assign_speakers", diarisation))
        return {"segments": [dict(s, speaker="SPEAKER_00") for s in aligned["segments"]]}


def test_ac_1_2_e_expected_speaker_count_passed_through(tmp_path):
    """The optional expected speaker count reaches the diarisation call."""
    engine = RecordingEngine()
    runner = PipelineRunner(engine)
    aligned = runner.transcribe(tmp_path / "audio.wav")

    runner.diarise(tmp_path / "audio.wav", aligned, expected_speakers=3)
    assert ("diarise", 3) in engine.calls

    runner.diarise(tmp_path / "audio.wav", aligned)
    assert ("diarise", None) in engine.calls


def test_ac_1_2_f_transcript_md_fixed_format():
    """transcript.md renders from the recorded fixture segment list in the
    pinned format: bold [hh:mm:ss] and name, one paragraph per turn, one blank
    line between turns, resolved names where known and labels elsewhere."""
    segments = load_segments(FIXTURE_SEGMENTS).segments
    text = render_transcript(segments, {"SPEAKER_00": "Ben Adams"})

    lines = text.splitlines()
    assert lines[0] == "# Transcript"
    assert lines[1] == ""
    assert lines[2] == "**[00:00:00] Ben Adams**"
    assert lines[3].startswith("Good afternoon everyone.")
    assert lines[4] == ""
    # The second speaker has no resolved name, so the diarised label shows.
    assert lines[5].startswith("**[00:00:0") and lines[5].endswith("SPEAKER_01**")
    assert lines[6].startswith("Thanks Daniel.")
    # Four turns in the fixture: alternating speakers, never merged.
    headers = [l for l in lines if l.startswith("**[")]
    assert len(headers) == 4
    assert text.endswith("\n") and "\n\n\n" not in text


def test_ac_1_2_g_english_language_and_alignment(tmp_path):
    """Transcription is requested in English and alignment uses the English
    wav2vec2 model."""
    engine = RecordingEngine()
    PipelineRunner(engine).transcribe(tmp_path / "audio.wav")

    assert ("transcribe", "en") in engine.calls
    assert ("align", "en", ENGLISH_ALIGNMENT_MODEL) in engine.calls
    assert ENGLISH_ALIGNMENT_MODEL == "WAV2VEC2_ASR_LARGE_LV60K_960H"
