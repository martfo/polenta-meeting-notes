"""Section 2.3: enrolment management. Unit tier."""

from meetingnotes.config import default_config
from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment import management as mgmt
from meetingnotes.enrolment.matching import match_cluster
from meetingnotes.storage.db import open_db
from tests.conftest import make_meeting


def test_ac_2_3_a_speakers_listed_with_meetings(conn, vault, gallery, vectors):
    """Speakers are listed with the meetings they appear in."""
    first = make_meeting(conn, vault, "2026-07-01_1000_first", "First")
    second = make_meeting(conn, vault, "2026-07-02_1000_second", "Second")
    ben = gallery.ensure_speaker("Ben Adams")
    gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])
    for meeting_id in (first, second):
        row_id = asg.record_cluster(gallery, meeting_id, "SPEAKER_00", [vectors["cluster_ben_match"]])
        asg.run_enrolment(gallery, row_id)
    gallery.ensure_speaker("Nobody Yet")

    listing = {s["name"]: s for s in mgmt.list_speakers(conn)}
    assert listing["Ben Adams"]["meetings"] == [first, second]
    assert listing["Nobody Yet"]["meetings"] == []
    assert len(listing["Ben Adams"]["voiceprints"]) == 1


def test_ac_2_3_d_delete_enrolment(conn, vault, gallery, vectors):
    """Deleting an enrolment removes it from the gallery, files included."""
    ben = gallery.ensure_speaker("Ben Adams")
    gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])
    refs = [vp["embedding_ref"] for vp in gallery.voiceprints(ben)]

    mgmt.delete_speaker(gallery, ben)

    assert mgmt.list_speakers(conn) == []
    assert all(not (vault.speakers_dir / ref).exists() for ref in refs)
    assert match_cluster(vectors["cluster_ben_match"], gallery) is None


def test_ac_2_3_e_thresholds_tunable(conn, gallery, vectors):
    """The match threshold and veto margin are tunable, and the same pair
    matches at a low threshold but not a high one."""
    ben = gallery.ensure_speaker("Ben Adams")
    gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])
    cluster = vectors["cluster_ben_match"]  # cosine 0.9 to Ben

    assert match_cluster(cluster, gallery, threshold=0.6) is not None
    assert match_cluster(cluster, gallery, threshold=0.95) is None

    # Tuning is persisted in settings and overrides config.json.
    config = default_config("/tmp/vault")
    assert mgmt.get_thresholds(config, conn) == (0.75, 0.10)
    mgmt.set_thresholds(conn, match_threshold=0.85, veto_margin=0.2)
    assert mgmt.get_thresholds(config, conn) == (0.85, 0.2)


def test_ac_2_3_g_negatives_and_removals_persist(conn, vault, gallery, vectors):
    """Negative examples and the flag on a reviewed voiceprint survive a
    reload and are shown in the management listing."""
    meeting_id = make_meeting(conn, vault)
    ben = gallery.ensure_speaker("Ben Adams")
    gallery.add_voiceprint(ben, "positive", vectors["ben_positive_1"])
    row_id = asg.record_cluster(gallery, meeting_id, "SPEAKER_00", [vectors["cluster_false_match"]])
    asg.run_enrolment(gallery, row_id)
    asg.correct(gallery, row_id, "Roger Neel")

    fresh = open_db(vault.db_path)
    try:
        listing = {s["name"]: s for s in mgmt.list_speakers(fresh)}
        ben_prints = listing["Ben Adams"]["voiceprints"]
        assert any(vp["kind"] == "negative" for vp in ben_prints)
        assert any(vp["flagged"] for vp in ben_prints), "the reviewed one stays visible"
    finally:
        fresh.close()
