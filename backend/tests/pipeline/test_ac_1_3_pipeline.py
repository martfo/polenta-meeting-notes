"""AC-1.3-e-pipeline: enrolment recognition on real audio. Phase boundary
only. Enrols the British voice from the two-speaker clip, then checks the
second clip of the same voice is auto-assigned."""

import pytest

pytestmark = pytest.mark.pipeline


def test_ac_1_3_e_pipeline_recognition_second_clip(fixtures_dir, vault, conn, gallery):
    pytest.importorskip("pyannote.audio")
    from meetingnotes.enrolment import assignments as asg
    from meetingnotes.enrolment.embedder import PyannoteSpeakerEmbedder
    from meetingnotes.pipeline.segments import load_segments
    from meetingnotes.storage.keychain import read_hf_token
    from tests.conftest import make_meeting

    embedder = PyannoteSpeakerEmbedder(hf_token=read_hf_token())

    # Enrol Daniel from his turns in clip one, using the recorded segment
    # boundaries.
    clip_one = fixtures_dir / "audio" / "two_speaker_meeting.wav"
    segments = load_segments(fixtures_dir / "segments" / "two_speaker_meeting.json").segments
    daniel_spans = [
        embedder.embed_span(clip_one, s.start, s.end)
        for s in segments if s.speaker == "SPEAKER_00"
    ]
    first = make_meeting(conn, vault, "2026-07-01_1000_first", "First")
    row_id = asg.record_cluster(gallery, first, "SPEAKER_00", daniel_spans)
    asg.assign_from_attendee(gallery, row_id, "Daniel")
    asg.confirm(gallery, row_id)

    # The second clip is the same voice, whole file as one cluster.
    clip_two = fixtures_dir / "audio" / "speaker_a_second_clip.wav"
    import wave

    with wave.open(str(clip_two), "rb") as w:
        duration = w.getnframes() / w.getframerate()
    second = make_meeting(conn, vault, "2026-07-02_1000_second", "Second")
    again = asg.record_cluster(
        gallery, second, "SPEAKER_00",
        [embedder.embed_span(clip_two, 0.0, duration)],
    )
    match = asg.run_enrolment(gallery, again)

    assert match is not None and match.name == "Daniel"
