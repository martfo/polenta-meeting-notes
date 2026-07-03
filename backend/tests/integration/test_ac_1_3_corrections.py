"""Section 1.3: enrolment over time and false-attribution correction.
Integration tier with injected vectors: a false positive is forced, corrected,
and then proven impossible to repeat."""

import numpy as np
import pytest

from meetingnotes.enrolment import assignments as asg
from meetingnotes.storage.db import open_db
from tests.conftest import make_meeting


@pytest.fixture
def meeting(conn, vault):
    return make_meeting(conn, vault, "2026-07-01_1000_first", "First meeting")


@pytest.fixture
def second_meeting(conn, vault):
    return make_meeting(conn, vault, "2026-07-02_1000_second", "Second meeting")


def test_naming_refreshes_transcript_and_front_matter(gallery, vectors, meeting, conn, vault, fixtures_dir):
    """Naming a speaker after processing rewrites transcript.md and the
    meeting.md speakers list with the resolved name."""
    import shutil

    from meetingnotes.storage.frontmatter import read_meeting_md, write_meeting_md
    from meetingnotes.storage.refresh import refresh_meeting_files

    shutil.copyfile(
        fixtures_dir / "segments" / "two_speaker_meeting.json",
        vault.meeting_dir(meeting) / "segments.json",
    )
    write_meeting_md(vault.meeting_md_path(meeting), {"id": meeting}, "## Core items discussed\n\nBody.")
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["ben_positive_1"]])

    asg.correct(gallery, row_id, "Martin")
    refresh_meeting_files(conn, vault, meeting)

    transcript = vault.transcript_path(meeting).read_text()
    assert "**[00:00:00] Martin**" in transcript
    assert "SPEAKER_00" not in transcript
    front, body = read_meeting_md(vault.meeting_md_path(meeting))
    assert "Martin" in front["speakers"]
    assert body.startswith("## Core items discussed"), "the summary body is untouched"


def test_ac_1_3_d_confirm_writes_positive(gallery, vectors, meeting):
    """Confirming a name writes the cluster voiceprint as a positive example
    under that name."""
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])
    asg.assign_from_attendee(gallery, row_id, "Ben Adams")

    asg.confirm(gallery, row_id)

    ben = gallery.ensure_speaker("Ben Adams")
    positives = gallery.voiceprints(ben, "positive")
    assert len(positives) == 1
    assert positives[0]["source_meeting_id"] == meeting
    saved = gallery.load_vector(positives[0]["embedding_ref"])
    assert np.allclose(saved, vectors["cluster_ben_match"], atol=1e-5)
    assert asg.get_assignment(gallery.conn, row_id)["confirmed"] == 1


def test_ac_1_3_e_fast_enrol_then_recognise(gallery, vectors, meeting, second_meeting):
    """A speaker enrolled from one clip is recognised on a second matching
    voiceprint from another meeting."""
    first = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])
    asg.assign_from_attendee(gallery, first, "Ben Adams")
    asg.confirm(gallery, first)

    second = asg.record_cluster(
        gallery, second_meeting, "SPEAKER_01", [vectors["cluster_ben_second_clip"]]
    )
    match = asg.run_enrolment(gallery, second)

    assert match is not None and match.name == "Ben Adams"
    assert asg.get_assignment(gallery.conn, second)["assigned_by"] == "enrolment"


def _force_false_match(gallery, vectors, meeting):
    """Ben is enrolled from e0; the cluster is actually Roger's voice but
    sits at cosine 0.85 to Ben's positive, so enrolment wrongly picks Ben."""
    ben = gallery.ensure_speaker("Ben Adams")
    driving_vp = gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_false_match"]])
    match = asg.run_enrolment(gallery, row_id)
    assert match is not None and match.name == "Ben Adams", "the forced false match"
    return ben, driving_vp, row_id


def test_ac_1_3_j_correction_writes_negative(gallery, vectors, meeting):
    """Correcting a wrong auto-assignment records the cluster voiceprint as a
    negative example against the wrongly matched speaker."""
    ben, _, row_id = _force_false_match(gallery, vectors, meeting)

    asg.correct(gallery, row_id, "Roger Neel")

    negatives = gallery.voiceprints(ben, "negative")
    assert len(negatives) == 1
    assert np.allclose(
        gallery.load_vector(negatives[0]["embedding_ref"]),
        vectors["cluster_false_match"], atol=1e-5,
    )


def test_ac_1_3_k_positive_only_under_correct_speaker(gallery, vectors, meeting):
    """The corrected voice is added as a positive example only to the speaker
    it actually is, never to the wrongly matched one."""
    ben, _, row_id = _force_false_match(gallery, vectors, meeting)

    asg.correct(gallery, row_id, "Roger Neel")

    roger = gallery.ensure_speaker("Roger Neel")
    roger_positives = gallery.voiceprints(roger, "positive")
    assert len(roger_positives) == 1
    assert np.allclose(
        gallery.load_vector(roger_positives[0]["embedding_ref"]),
        vectors["cluster_false_match"], atol=1e-5,
    )
    # Ben keeps only his original positive: the corrected voice never lands
    # under the wrongly matched name.
    ben_positives = gallery.voiceprints(ben, "positive")
    assert len(ben_positives) == 1
    assert np.allclose(gallery.load_vector(ben_positives[0]["embedding_ref"]),
                       vectors["ben_positive_1"], atol=1e-5)


def test_ac_1_3_m_recurrence(gallery, vectors, meeting, second_meeting):
    """The recurrence test: after one correction, the same wrongly-matched
    voice is never assigned to the corrected-away name again."""
    _, _, row_id = _force_false_match(gallery, vectors, meeting)
    asg.correct(gallery, row_id, "Roger Neel")

    # The same voice turns up in the next meeting.
    again = asg.record_cluster(
        gallery, second_meeting, "SPEAKER_00", [vectors["cluster_false_match"]]
    )
    match = asg.run_enrolment(gallery, again)

    row = asg.get_assignment(gallery.conn, again)
    assert row["display_name"] != "Ben Adams"
    if match is not None:
        assert match.name == "Roger Neel", "the correction taught the right name"


def test_ac_1_3_o_remove_flagged_recompute(gallery, vectors, meeting, second_meeting, vault):
    """A flagged voiceprint can be removed, and the speaker's profile without
    it no longer matches the voice that exposed it."""
    ben, driving_vp, row_id = _force_false_match(gallery, vectors, meeting)
    asg.correct(gallery, row_id, "Roger Neel")

    flagged = gallery.flagged_voiceprints()
    assert [vp["id"] for vp in flagged] == [driving_vp]
    ref = flagged[0]["embedding_ref"]
    gallery.remove_voiceprint(driving_vp)

    assert not (vault.speakers_dir / ref).exists(), "the vector file went too"
    again = asg.record_cluster(
        gallery, second_meeting, "SPEAKER_01", [vectors["cluster_false_match"]]
    )
    match = asg.run_enrolment(gallery, again)
    assert match is None or match.name != "Ben Adams"

    # And the removal survives a reload.
    fresh = open_db(vault.db_path)
    try:
        assert fresh.execute(
            "SELECT COUNT(*) FROM voiceprints WHERE id = ?", (driving_vp,)
        ).fetchone()[0] == 0
    finally:
        fresh.close()
