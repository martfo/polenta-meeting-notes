"""[pipeline] tier: the vocabulary initial prompt against real WhisperX.

Confirms the installed WhisperX accepts asr_options={"initial_prompt": ...},
that a prompted transcription still produces a real transcript, and that the
engine reloads when the prompt changes. Phase boundary only; needs the models
present (uv sync --extra pipeline) and the Hugging Face token.
"""

import pytest

pytestmark = pytest.mark.pipeline


def test_ac_x_vocabulary_prompt_is_accepted(fixtures_dir):
    pytest.importorskip("whisperx")
    from meetingnotes.pipeline.runner import PipelineRunner
    from meetingnotes.pipeline.vocabulary import build_initial_prompt
    from meetingnotes.pipeline.whisperx_engine import WhisperXEngine
    from meetingnotes.storage.keychain import read_hf_token

    audio = fixtures_dir / "audio" / "two_speaker_meeting.wav"
    engine = WhisperXEngine(hf_token=read_hf_token())
    runner = PipelineRunner(engine)

    prompt = build_initial_prompt(["Daniel"], ["hydroponics"])
    assert prompt == "Participants: Daniel. Terms: hydroponics."

    result = runner.transcribe(audio, initial_prompt=prompt)

    # asr_options was accepted: a real transcript came back, and the engine
    # recorded the prompt it loaded with.
    assert engine._loaded_prompt == prompt
    assert result.segments
    assert any(seg.text.strip() for seg in result.segments)


def test_ac_x_vocabulary_prompt_change_reloads(fixtures_dir):
    pytest.importorskip("whisperx")
    from meetingnotes.pipeline.whisperx_engine import WhisperXEngine
    from meetingnotes.storage.keychain import read_hf_token

    audio = fixtures_dir / "audio" / "speaker_a_second_clip.wav"
    engine = WhisperXEngine(hf_token=read_hf_token())

    engine.transcribe(audio, language="en", initial_prompt="Terms: hydroponics.")
    assert engine._loaded_prompt == "Terms: hydroponics."
    first_model = engine._asr

    engine.transcribe(audio, language="en", initial_prompt="Terms: aquaponics.")
    assert engine._loaded_prompt == "Terms: aquaponics."
    # A changed prompt reloads the model rather than reusing stale options.
    assert engine._asr is not first_model
