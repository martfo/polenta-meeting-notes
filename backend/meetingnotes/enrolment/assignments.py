"""Speaker naming for a meeting's diarised clusters, in priority order:
voice enrolment, then the attendee list, then manual naming. Corrections
teach the gallery so the same mistake does not recur."""

from __future__ import annotations

import sqlite3

import numpy as np

from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.enrolment.matching import MatchResult, cluster_voiceprint, match_cluster


def record_cluster(
    gallery: Gallery, meeting_id: str, diarised_label: str,
    segment_embeddings: np.ndarray | list,
) -> int:
    """Store the cluster and its voiceprint for a meeting. The voiceprint is
    kept so a later confirmation or correction can reuse it."""
    vp = cluster_voiceprint(np.asarray(segment_embeddings))
    ref = gallery.save_vector(vp)
    cur = gallery.conn.execute(
        """INSERT INTO meeting_speakers(meeting_id, diarised_label, display_name, cluster_embedding_ref)
           VALUES (?, ?, ?, ?)""",
        (meeting_id, diarised_label, diarised_label, ref),
    )
    gallery.conn.commit()
    return cur.lastrowid


def clear_meeting(conn: sqlite3.Connection, meeting_id: str) -> None:
    """Remove a meeting's speaker assignments so its pipeline can run again.

    Reprocessing (a retry over repaired audio, say) diarises fresh clusters
    whose labels the old rows already claim: without clearing, record_cluster
    hits the meeting_id/diarised_label UNIQUE constraint and enrich fails. The
    old rows describe stale clusters anyway. Voiceprints already taught to the
    gallery are kept; only the per-meeting label table is reset."""
    conn.execute("DELETE FROM meeting_speakers WHERE meeting_id = ?", (meeting_id,))
    conn.commit()


def get_assignment(conn: sqlite3.Connection, assignment_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM meeting_speakers WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise KeyError(f"no meeting speaker {assignment_id}")
    return row


def cluster_vector(gallery: Gallery, assignment_id: int) -> np.ndarray:
    return gallery.load_vector(get_assignment(gallery.conn, assignment_id)["cluster_embedding_ref"])


def run_enrolment(
    gallery: Gallery, assignment_id: int,
    threshold: float = 0.75, veto_margin: float = 0.10,
) -> MatchResult | None:
    """Highest-priority naming: match the cluster against the gallery and
    auto-assign on success, recording the provenance."""
    match = match_cluster(cluster_vector(gallery, assignment_id), gallery, threshold, veto_margin)
    if match is None:
        return None
    gallery.conn.execute(
        """UPDATE meeting_speakers
           SET speaker_id = ?, display_name = ?, assigned_by = 'enrolment',
               matched_voiceprint_id = ?, match_score = ?, confirmed = 0
           WHERE id = ?""",
        (match.speaker_id, match.name, match.voiceprint_id, match.score, assignment_id),
    )
    gallery.conn.commit()
    return match


def assign_from_attendee(gallery: Gallery, assignment_id: int, name: str) -> None:
    """Second priority: a name taken from the meeting's attendee list."""
    speaker_id = gallery.ensure_speaker(name)
    gallery.conn.execute(
        """UPDATE meeting_speakers
           SET speaker_id = ?, display_name = ?, assigned_by = 'attendee',
               matched_voiceprint_id = NULL, match_score = NULL, confirmed = 0
           WHERE id = ?""",
        (speaker_id, name, assignment_id),
    )
    gallery.conn.commit()


def confirm(gallery: Gallery, assignment_id: int, add_positive: bool = True) -> None:
    """Confirming a name marks it confirmed and, by default, saves the cluster
    voiceprint as a further positive example under that speaker, so enrolment
    improves over time."""
    row = get_assignment(gallery.conn, assignment_id)
    speaker_id = row["speaker_id"]
    if speaker_id is None:
        raise ValueError("cannot confirm an unassigned cluster")
    if add_positive:
        gallery.add_voiceprint(
            speaker_id, "positive", cluster_vector(gallery, assignment_id),
            source_meeting_id=row["meeting_id"],
        )
    gallery.conn.execute(
        "UPDATE meeting_speakers SET confirmed = 1 WHERE id = ?", (assignment_id,)
    )
    gallery.conn.commit()


def correct(gallery: Gallery, assignment_id: int, new_name: str | None) -> None:
    """Change an assignment away from what it was. A correction away from an
    enrolment match teaches the gallery:

    - the cluster voiceprint becomes a negative example against the wrongly
      matched speaker, so the veto blocks that voice from that name;
    - the positive voiceprint that drove the false match is flagged for
      review;
    - if the cluster is named as someone else, the voiceprint is added as a
      positive example to that correct speaker only.

    With new_name None the cluster is left unlabelled.
    """
    row = get_assignment(gallery.conn, assignment_id)
    vp = cluster_vector(gallery, assignment_id)

    wrongly_matched = row["assigned_by"] == "enrolment" and row["speaker_id"] is not None
    if wrongly_matched and (new_name is None or new_name != gallery.speaker_name(row["speaker_id"])):
        gallery.add_voiceprint(
            row["speaker_id"], "negative", vp, source_meeting_id=row["meeting_id"]
        )
        if row["matched_voiceprint_id"] is not None:
            gallery.flag_voiceprint(row["matched_voiceprint_id"])

    if new_name is None:
        gallery.conn.execute(
            """UPDATE meeting_speakers
               SET speaker_id = NULL, display_name = diarised_label, assigned_by = NULL,
                   matched_voiceprint_id = NULL, match_score = NULL, confirmed = 0
               WHERE id = ?""",
            (assignment_id,),
        )
    else:
        speaker_id = gallery.ensure_speaker(new_name)
        gallery.add_voiceprint(speaker_id, "positive", vp, source_meeting_id=row["meeting_id"])
        gallery.conn.execute(
            """UPDATE meeting_speakers
               SET speaker_id = ?, display_name = ?, assigned_by = 'manual',
                   matched_voiceprint_id = NULL, match_score = NULL, confirmed = 1
               WHERE id = ?""",
            (speaker_id, new_name, assignment_id),
        )
    gallery.conn.commit()


def display_names(conn: sqlite3.Connection, meeting_id: str) -> dict[str, str]:
    """diarised label to shown name, for the transcript renderer."""
    rows = conn.execute(
        "SELECT diarised_label, display_name FROM meeting_speakers WHERE meeting_id = ?",
        (meeting_id,),
    ).fetchall()
    return {r["diarised_label"]: r["display_name"] or r["diarised_label"] for r in rows}
