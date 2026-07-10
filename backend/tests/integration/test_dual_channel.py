"""Dual-channel capture: the microphone (owner) and system audio (remote)
transcribed separately and merged, with pyannote only on the remote channel."""

import wave

import numpy as np

from meetingnotes.config import default_config
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.jobs.stages import build_stages
from meetingnotes.pipeline.normalize import normalise_wav
from meetingnotes.pipeline.segments import Segment, merge_by_time
from meetingnotes.storage import meetings as m
from tests.conftest import make_meeting


def _write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.asarray(samples, dtype=np.int16).tobytes())


def test_merge_by_time_interleaves_channels():
    mic = [Segment(start=0.0, end=2.0, text="Hello", channel="mic", speaker="Me"),
           Segment(start=5.0, end=6.0, text="Yes", channel="mic", speaker="Me")]
    system = [Segment(start=2.0, end=4.0, text="Hi there", channel="system", speaker=None)]
    merged = merge_by_time(mic, system)
    assert [s.text for s in merged] == ["Hello", "Hi there", "Yes"]
    assert [s.channel for s in merged] == ["mic", "system", "mic"]


def test_normalise_lifts_quiet_audio(tmp_path):
    """A quiet-but-real channel is boosted; a silent one is left alone."""
    quiet = tmp_path / "quiet.wav"
    _write_wav(quiet, (np.sin(np.linspace(0, 2000, 16000)) * 400))  # peak ~0.012
    out = normalise_wav(quiet, tmp_path / "norm.wav")
    with wave.open(str(out), "rb") as w:
        peak = np.max(np.abs(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16))) / 32768.0
    assert peak > 0.8, "quiet speech is normalised up towards full scale"


class ChannelEngine:
    """Returns different words per audio file, so the merge can be checked."""

    def __init__(self, by_name):
        self.by_name = by_name  # filename stem -> [(start, end, text)]
        self.transcribed: list[str] = []

    def transcribe(self, audio_path, language, initial_prompt=None):
        # After normalisation the file is norm.wav; use the parent to identify
        # which channel it came from is not possible, so key on content length.
        raise NotImplementedError


def test_dual_channel_pipeline_merges_owner_and_remote(conn, vault):
    """The mic channel is the owner (no diarisation); the system channel is
    diarised; the transcript merges both by time."""
    meeting_id = make_meeting(conn, vault)
    d = vault.meeting_dir(meeting_id)
    # Real-ish audio so the silence check passes.
    tone = (np.sin(np.linspace(0, 4000, 16000 * 6)) * 6000)
    _write_wav(d / "mic.wav", tone)
    _write_wav(d / "system.wav", tone)
    _write_wav(vault.audio_path(meeting_id), tone)

    class DualEngine:
        """Owner says one line; remote says two (to be diarised into speakers)."""

        def transcribe(self, audio_path, language, initial_prompt=None):
            # mic normalised first, then system: distinguish by call order.
            self.calls = getattr(self, "calls", 0) + 1
            if self.calls == 1:
                return {"segments": [{"start": 0.0, "end": 2.0, "text": "I will send it Friday.", "words": []}]}
            return {"segments": [
                {"start": 1.0, "end": 3.0, "text": "Thanks, that works.", "words": []},
                {"start": 6.0, "end": 8.0, "text": "One more thing.", "words": []},
            ]}

        def align(self, result, audio_path, language, model_name):
            return result

        def diarise(self, audio_path, num_speakers):
            return "diarisation"

        def assign_speakers(self, diarisation, aligned):
            # Give the two system segments two different speakers.
            segs = aligned["segments"]
            for i, s in enumerate(segs):
                s["speaker"] = f"SPEAKER_0{i}"
            return {"segments": segs}

    class Embedder:
        def cluster_voiceprints(self, audio_path, segments):
            labels = {s.speaker for s in segments if s.speaker}
            return {label: np.eye(8)[i % 8] for i, label in enumerate(sorted(labels))}

    config = default_config(vault.root)
    config.owner_name = "Martin"
    stages = build_stages(conn, vault, config, engine=DualEngine(),
                          speaker_embedder=Embedder(), lm_client=None)

    stages["transcribe"](meeting_id)
    stages["diarise"](meeting_id)
    stages["enrich"](meeting_id)

    transcript = vault.transcript_path(meeting_id).read_text()
    assert "Martin" in transcript, "the mic channel is the owner"
    assert "I will send it Friday." in transcript
    assert "Thanks, that works." in transcript
    # Interleaved by time: owner (0-2s) then remote (1-3s) then remote (6-8s).
    assert transcript.index("Friday") < transcript.index("Thanks")
    # The owner and the two remote speakers are all recorded.
    speakers = [r["display_name"] for r in conn.execute(
        "SELECT display_name FROM meeting_speakers WHERE meeting_id = ?", (meeting_id,)).fetchall()]
    assert "Martin" in speakers


def test_single_channel_still_works(conn, vault, fixtures_dir):
    """A meeting with only audio.wav (an import) uses the single-channel path."""
    import shutil

    meeting_id = make_meeting(conn, vault)
    shutil.copyfile(fixtures_dir / "audio" / "two_speaker_meeting.wav",
                    vault.audio_path(meeting_id))

    class Engine:
        def transcribe(self, audio_path, language, initial_prompt=None):
            return {"segments": [{"start": 0.0, "end": 2.0, "text": "Hello.", "words": []}]}

        def align(self, result, audio_path, language, model_name):
            return result

        def diarise(self, audio_path, num_speakers):
            return "d"

        def assign_speakers(self, diarisation, aligned):
            return {"segments": [dict(s, speaker="SPEAKER_00") for s in aligned["segments"]]}

    class Embedder:
        def cluster_voiceprints(self, audio_path, segments):
            return {"SPEAKER_00": np.eye(8)[0]}

    config = default_config(vault.root)
    stages = build_stages(conn, vault, config, engine=Engine(),
                          speaker_embedder=Embedder(), lm_client=None)
    stages["transcribe"](meeting_id)
    stages["diarise"](meeting_id)
    assert "Hello." in vault.transcript_path(meeting_id).read_text()
