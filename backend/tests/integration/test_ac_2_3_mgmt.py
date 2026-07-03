"""Section 2.3: enrolment management flows across meetings. Integration tier."""

import numpy as np

from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment import management as mgmt
from tests.conftest import make_meeting


def test_ac_2_3_b_rename_reflected_in_future_naming(conn, vault, gallery, vectors):
    """Renaming a speaker changes what future enrolment assigns."""
    first = make_meeting(conn, vault, "2026-07-01_1000_first", "First")
    ben = gallery.ensure_speaker("Ben")
    gallery.add_voiceprint(ben, "positive", vectors["cluster_ben_match"])

    mgmt.rename_speaker(conn, ben, "Benjamin Adams")

    later = make_meeting(conn, vault, "2026-07-02_1000_later", "Later")
    row_id = asg.record_cluster(gallery, later, "SPEAKER_00", [vectors["cluster_ben_second_clip"]])
    match = asg.run_enrolment(gallery, row_id)
    assert match is not None and match.name == "Benjamin Adams"
    assert asg.get_assignment(conn, row_id)["display_name"] == "Benjamin Adams"
    assert first is not None


def test_ac_2_3_c_merge_combines_and_remaps(conn, vault, gallery, vectors):
    """Merging two speakers combines their voiceprints and remaps
    meeting_speakers."""
    meeting_id = make_meeting(conn, vault)
    keep = gallery.ensure_speaker("Ben Adams")
    duplicate = gallery.ensure_speaker("B. Adams")
    gallery.add_voiceprint(keep, "positive", vectors["ben_positive_1"])
    gallery.add_voiceprint(duplicate, "positive", vectors["cluster_ben_match"])
    gallery.add_voiceprint(duplicate, "negative", vectors["cluster_false_match"])
    row_id = asg.record_cluster(gallery, meeting_id, "SPEAKER_00", [vectors["cluster_ben_match"]])
    conn.execute(
        "UPDATE meeting_speakers SET speaker_id = ?, display_name = 'B. Adams' WHERE id = ?",
        (duplicate, row_id),
    )
    conn.commit()

    mgmt.merge_speakers(conn, keep_id=keep, absorb_id=duplicate)

    prints = gallery.voiceprints(keep)
    assert len(prints) == 3, "every voiceprint moved to the kept speaker"
    assert {vp["kind"] for vp in prints} == {"positive", "negative"}
    row = asg.get_assignment(conn, row_id)
    assert row["speaker_id"] == keep and row["display_name"] == "Ben Adams"
    assert conn.execute("SELECT COUNT(*) FROM speakers WHERE id = ?", (duplicate,)).fetchone()[0] == 0


def test_ac_2_3_f_cross_meeting_correction_offered(conn, vault, gallery, vectors):
    """Correcting a false match lists other meetings where the same
    voiceprint drove an auto-assignment and applies the same correction."""
    ben = gallery.ensure_speaker("Ben Adams")
    driving = gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])

    rows = {}
    for meeting_id in ("2026-07-01_1000_first", "2026-07-02_1000_second"):
        make_meeting(conn, vault, meeting_id, meeting_id)
        row_id = asg.record_cluster(gallery, meeting_id, "SPEAKER_00", [vectors["cluster_false_match"]])
        match = asg.run_enrolment(gallery, row_id)
        assert match is not None and match.voiceprint_id == driving
        rows[meeting_id] = row_id

    # The user corrects the first meeting.
    asg.correct(gallery, rows["2026-07-01_1000_first"], "Roger Neel")

    # The app can reach back: the second meeting is offered.
    offered = mgmt.assignments_driven_by(conn, driving)
    offered_ids = {r["id"] for r in offered}
    assert rows["2026-07-02_1000_second"] in offered_ids

    corrected = mgmt.correct_across_meetings(
        gallery, driving, "Roger Neel",
        except_assignment=rows["2026-07-01_1000_first"])
    assert corrected == ["2026-07-02_1000_second"]
    row = asg.get_assignment(conn, rows["2026-07-02_1000_second"])
    assert row["display_name"] == "Roger Neel"

    # Roger holds positives for the voice; Ben holds negatives against it.
    roger = gallery.ensure_speaker("Roger Neel")
    assert all(
        np.allclose(gallery.load_vector(vp["embedding_ref"]), vectors["cluster_false_match"], atol=1e-5)
        for vp in gallery.voiceprints(roger, "positive")
    )
    assert len(gallery.voiceprints(ben, "negative")) == 2
