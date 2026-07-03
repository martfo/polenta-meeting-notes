"""Section 1.3: speaker matching and assignment records. Unit tier, driven by
the controlled vectors fixture so every outcome is forced exactly."""

import numpy as np
import pytest

from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment.matching import cluster_voiceprint, cosine, match_cluster
from meetingnotes.storage.db import open_db
from tests.conftest import make_meeting


@pytest.fixture
def meeting(conn, vault):
    return make_meeting(conn, vault)


def enrol_ben(gallery, vectors, vector_name="ben_positive_1"):
    ben = gallery.ensure_speaker("Ben Adams")
    vp_id = gallery.add_voiceprint(ben, "positive", vectors[vector_name])
    return ben, vp_id


def test_ac_1_3_a_cluster_voiceprint_mean_l2(vectors):
    """The cluster voiceprint is the mean of its segment embeddings, L2
    normalised."""
    vp = cluster_voiceprint([vectors["segment_a"], vectors["segment_b"]])
    expected = np.zeros(8)
    expected[0] = expected[1] = 1 / np.sqrt(2)
    assert np.allclose(vp, expected)
    assert np.isclose(np.linalg.norm(vp), 1.0)


def test_ac_1_3_b_auto_assign_above_threshold(gallery, vectors, meeting):
    """Positive similarity at or above 0.75, clear of negatives: assigned."""
    enrol_ben(gallery, vectors)
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])

    match = asg.run_enrolment(gallery, row_id)

    assert match is not None and match.name == "Ben Adams"
    assert match.score == pytest.approx(0.9, abs=1e-6)
    row = asg.get_assignment(gallery.conn, row_id)
    assert row["display_name"] == "Ben Adams"


def test_ac_1_3_c_below_threshold_left_unassigned(gallery, vectors, meeting):
    """Below the threshold the cluster is left for attendee or manual naming."""
    enrol_ben(gallery, vectors)
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_low_similarity"]])

    assert asg.run_enrolment(gallery, row_id) is None
    row = asg.get_assignment(gallery.conn, row_id)
    assert row["speaker_id"] is None and row["assigned_by"] is None
    assert row["display_name"] == "SPEAKER_00", "the diarised label still shows"


def test_ac_1_3_f_label_mapping_persisted(gallery, vectors, meeting, vault, conn):
    """The diarised-label to speaker mapping survives a reload from disk."""
    enrol_ben(gallery, vectors)
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])
    asg.run_enrolment(gallery, row_id)

    fresh = open_db(vault.db_path)
    try:
        assert asg.display_names(fresh, meeting) == {"SPEAKER_00": "Ben Adams"}
        row = fresh.execute(
            "SELECT * FROM meeting_speakers WHERE meeting_id = ? AND diarised_label = 'SPEAKER_00'",
            (meeting,),
        ).fetchone()
        assert row["speaker_id"] is not None
    finally:
        fresh.close()


def test_ac_1_3_g_auto_assign_marked_and_correctable(gallery, vectors, meeting):
    """Auto-assigned names are marked as enrolment and can be corrected, and
    the correction updates the gallery."""
    ben_id, _ = enrol_ben(gallery, vectors)
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])
    asg.run_enrolment(gallery, row_id)

    assert asg.get_assignment(gallery.conn, row_id)["assigned_by"] == "enrolment"

    asg.correct(gallery, row_id, "Roger Neel")

    row = asg.get_assignment(gallery.conn, row_id)
    assert row["display_name"] == "Roger Neel" and row["assigned_by"] == "manual"
    # The gallery learnt from it: a negative example now sits against Ben.
    assert any(vp["kind"] == "negative" for vp in gallery.voiceprints(ben_id))


def test_ac_1_3_h_provenance_recorded(gallery, vectors, meeting):
    """An auto-assignment records the matched speaker, the match score, and
    the voiceprint that drove the match."""
    ben_id, vp_id = enrol_ben(gallery, vectors)
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])
    asg.run_enrolment(gallery, row_id)

    row = asg.get_assignment(gallery.conn, row_id)
    assert row["speaker_id"] == ben_id
    assert row["matched_voiceprint_id"] == vp_id
    assert row["match_score"] == pytest.approx(0.9, abs=1e-6)


def test_ac_1_3_i_reassign_existing_new_or_unlabelled(gallery, vectors, meeting):
    """An auto-assigned speaker can move to a different existing speaker, a
    new speaker, or back to unlabelled."""
    enrol_ben(gallery, vectors)
    existing = gallery.ensure_speaker("Delia Hart")
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_ben_match"]])
    asg.run_enrolment(gallery, row_id)

    asg.correct(gallery, row_id, "Delia Hart")
    row = asg.get_assignment(gallery.conn, row_id)
    assert row["speaker_id"] == existing and row["display_name"] == "Delia Hart"

    asg.correct(gallery, row_id, "Brand New Person")
    row = asg.get_assignment(gallery.conn, row_id)
    assert row["display_name"] == "Brand New Person"
    assert gallery.speaker_name(row["speaker_id"]) == "Brand New Person"

    asg.correct(gallery, row_id, None)
    row = asg.get_assignment(gallery.conn, row_id)
    assert row["speaker_id"] is None and row["assigned_by"] is None
    assert row["display_name"] == "SPEAKER_00"


def test_ac_1_3_l_veto_margin_blocks_near_negative(gallery, vectors, meeting):
    """Positive similarity above the threshold, but a stored negative example
    sits within the veto margin: no auto-assignment."""
    ben_id, _ = enrol_ben(gallery, vectors)
    gallery.add_voiceprint(ben_id, "negative", vectors["ben_negative_close"])
    cluster = vectors["cluster_near_negative"]

    # The positive side alone would clear the threshold.
    assert cosine(cluster, vectors["ben_positive_1"]) >= 0.75
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [cluster])

    assert asg.run_enrolment(gallery, row_id) is None
    assert asg.get_assignment(gallery.conn, row_id)["speaker_id"] is None


def test_ac_1_3_n_driving_voiceprint_flagged(gallery, vectors, meeting):
    """After a correction, the stored positive voiceprint that drove the
    false match is surfaced for review."""
    _, vp_id = enrol_ben(gallery, vectors)
    row_id = asg.record_cluster(gallery, meeting, "SPEAKER_00", [vectors["cluster_false_match"]])
    asg.run_enrolment(gallery, row_id)

    asg.correct(gallery, row_id, "Roger Neel")

    flagged = [vp["id"] for vp in gallery.flagged_voiceprints()]
    assert flagged == [vp_id]
