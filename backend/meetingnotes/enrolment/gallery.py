"""The enrolment gallery: speakers and their positive and negative
voiceprints. Vectors live as JSON files under the vault's speakers folder;
the voiceprints table holds the reference and the provenance."""

from __future__ import annotations

import json
import sqlite3
import uuid

import numpy as np

from meetingnotes.enrolment.matching import SpeakerVoiceprints, l2_normalise
from meetingnotes.storage.db import utcnow
from meetingnotes.storage.vault import Vault


class Gallery:
    def __init__(self, conn: sqlite3.Connection, vault: Vault):
        self.conn = conn
        self.vault = vault

    # -- vector files --------------------------------------------------------

    def save_vector(self, vector: np.ndarray) -> str:
        ref = f"vp_{uuid.uuid4().hex}.json"
        path = self.vault.speakers_dir / ref
        path.write_text(json.dumps([float(x) for x in l2_normalise(np.asarray(vector, float))]))
        return ref

    def load_vector(self, ref: str) -> np.ndarray:
        return np.array(json.loads((self.vault.speakers_dir / ref).read_text()))

    # -- speakers ------------------------------------------------------------

    def ensure_speaker(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM speakers WHERE name = ?", (name,)).fetchone()
        if row is not None:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO speakers(name, created_at) VALUES (?, ?)", (name, utcnow())
        )
        self.conn.commit()
        return cur.lastrowid

    def speaker_name(self, speaker_id: int) -> str:
        return self.conn.execute(
            "SELECT name FROM speakers WHERE id = ?", (speaker_id,)
        ).fetchone()["name"]

    # -- voiceprints ---------------------------------------------------------

    def add_voiceprint(
        self, speaker_id: int, kind: str, vector: np.ndarray,
        source_meeting_id: str | None = None,
    ) -> int:
        assert kind in ("positive", "negative"), kind
        ref = self.save_vector(vector)
        cur = self.conn.execute(
            """INSERT INTO voiceprints(speaker_id, kind, embedding_ref, source_meeting_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (speaker_id, kind, ref, source_meeting_id, utcnow()),
        )
        self.conn.commit()
        return cur.lastrowid

    def voiceprints(self, speaker_id: int, kind: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM voiceprints WHERE speaker_id = ?"
        params: list = [speaker_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        return self.conn.execute(sql + " ORDER BY id", params).fetchall()

    def flag_voiceprint(self, voiceprint_id: int) -> None:
        """Surface a stored voiceprint for review after it drove a false
        match. Removing it fixes the cause rather than the symptom."""
        self.conn.execute("UPDATE voiceprints SET flagged = 1 WHERE id = ?", (voiceprint_id,))
        self.conn.commit()

    def flagged_voiceprints(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM voiceprints WHERE flagged = 1 ORDER BY id"
        ).fetchall()

    def remove_voiceprint(self, voiceprint_id: int) -> None:
        """Delete a voiceprint and its vector file. The speaker's profile is
        simply the set of remaining voiceprints, so removal recomputes it."""
        row = self.conn.execute(
            "SELECT embedding_ref FROM voiceprints WHERE id = ?", (voiceprint_id,)
        ).fetchone()
        if row is None:
            return
        (self.vault.speakers_dir / row["embedding_ref"]).unlink(missing_ok=True)
        self.conn.execute("DELETE FROM voiceprints WHERE id = ?", (voiceprint_id,))
        self.conn.commit()

    # -- the matcher's view --------------------------------------------------

    def speaker_voiceprints(self) -> list[SpeakerVoiceprints]:
        result = []
        for speaker in self.conn.execute("SELECT * FROM speakers ORDER BY id").fetchall():
            positives, negatives = [], []
            for vp in self.voiceprints(speaker["id"]):
                entry = (vp["id"], self.load_vector(vp["embedding_ref"]))
                (positives if vp["kind"] == "positive" else negatives).append(entry)
            result.append(
                SpeakerVoiceprints(
                    speaker_id=speaker["id"], name=speaker["name"],
                    positives=positives, negatives=negatives,
                )
            )
        return result
