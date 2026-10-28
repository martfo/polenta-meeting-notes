"""Enrolment management: view and manage enrolled speakers, merge duplicates,
tune the thresholds, and reach back across past meetings when a false match
is corrected."""

from __future__ import annotations

import sqlite3
from typing import Any

from meetingnotes.config import Config
from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment.gallery import Gallery

THRESHOLD_KEY = "match_threshold"
VETO_KEY = "veto_margin"


def list_speakers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every enrolled speaker with the meetings they appear in and their
    voiceprints, including flagged and negative ones."""
    result = []
    for speaker in conn.execute("SELECT * FROM speakers ORDER BY name").fetchall():
        meetings = [
            r["meeting_id"] for r in conn.execute(
                "SELECT DISTINCT meeting_id FROM meeting_speakers WHERE speaker_id = ? ORDER BY meeting_id",
                (speaker["id"],),
            ).fetchall()
        ]
        voiceprints = [
            dict(v) for v in conn.execute(
                "SELECT * FROM voiceprints WHERE speaker_id = ? ORDER BY id", (speaker["id"],)
            ).fetchall()
        ]
        result.append({
            "id": speaker["id"], "name": speaker["name"],
            "meetings": meetings, "voiceprints": voiceprints,
        })
    return result


def rename_speaker(conn: sqlite3.Connection, speaker_id: int, new_name: str) -> None:
    conn.execute("UPDATE speakers SET name = ? WHERE id = ?", (new_name.strip(), speaker_id))
    conn.execute(
        "UPDATE meeting_speakers SET display_name = ? WHERE speaker_id = ?",
        (new_name.strip(), speaker_id),
    )
    conn.commit()


def merge_speakers(conn: sqlite3.Connection, keep_id: int, absorb_id: int) -> None:
    """Two enrolled speakers that are the same person: the kept speaker
    inherits every voiceprint, and past meetings are remapped."""
    if keep_id == absorb_id:
        raise ValueError("cannot merge a speaker into themselves")
    keep_name = conn.execute("SELECT name FROM speakers WHERE id = ?", (keep_id,)).fetchone()["name"]
    conn.execute("UPDATE voiceprints SET speaker_id = ? WHERE speaker_id = ?", (keep_id, absorb_id))
    conn.execute(
        "UPDATE meeting_speakers SET speaker_id = ?, display_name = ? WHERE speaker_id = ?",
        (keep_id, keep_name, absorb_id),
    )
    conn.execute("DELETE FROM speakers WHERE id = ?", (absorb_id,))
    conn.commit()


def delete_speaker(gallery: Gallery, speaker_id: int) -> None:
    """Remove an enrolment entirely: every voiceprint file and row, and the
    speaker. Past meetings keep their display names but lose the link."""
    for vp in gallery.voiceprints(speaker_id):
        gallery.remove_voiceprint(vp["id"])
    gallery.conn.execute(
        "UPDATE meeting_speakers SET speaker_id = NULL WHERE speaker_id = ?", (speaker_id,)
    )
    gallery.conn.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,))
    gallery.conn.commit()


# -- tunable thresholds ------------------------------------------------------

def get_thresholds(config: Config, conn: sqlite3.Connection) -> tuple[float, float]:
    """match_threshold and veto_margin: config.json values, overridden by the
    settings table when tuned in the management screen."""
    values = {r["key"]: float(r["value"]) for r in conn.execute(
        "SELECT key, value FROM settings WHERE key IN (?, ?)", (THRESHOLD_KEY, VETO_KEY)
    ).fetchall()}
    return (
        values.get(THRESHOLD_KEY, config.match_threshold),
        values.get(VETO_KEY, config.veto_margin),
    )


def set_thresholds(conn: sqlite3.Connection, match_threshold: float | None = None,
                   veto_margin: float | None = None) -> None:
    for key, value in ((THRESHOLD_KEY, match_threshold), (VETO_KEY, veto_margin)):
        if value is not None:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
    conn.commit()


# -- reaching back across meetings -------------------------------------------

def assignments_driven_by(conn: sqlite3.Connection, voiceprint_id: int) -> list[sqlite3.Row]:
    """Auto-assignments whose provenance is this voiceprint: the meetings a
    false match may have poisoned."""
    return conn.execute(
        "SELECT * FROM meeting_speakers WHERE matched_voiceprint_id = ? ORDER BY meeting_id",
        (voiceprint_id,),
    ).fetchall()


def correct_across_meetings(
    gallery: Gallery, voiceprint_id: int, new_name: str | None,
    except_assignment: int | None = None,
) -> list[str]:
    """Apply the same correction to every other meeting where the same
    voiceprint drove the auto-assignment. Returns the meetings corrected."""
    corrected = []
    for row in assignments_driven_by(gallery.conn, voiceprint_id):
        if row["id"] == except_assignment or row["confirmed"]:
            continue
        asg.correct(gallery, row["id"], new_name)
        corrected.append(row["meeting_id"])
    return corrected
