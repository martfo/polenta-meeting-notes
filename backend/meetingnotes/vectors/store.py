"""The LanceDB store behind library search: one row per passage, scoped by
folder so retrieval can search one folder or the whole vault.

Search is hybrid. Meaning-based (vector) search alone gave a name like
"Brightwater" no special weight, and keyword search alone favours very short
passages, so both run and their rankings are fused (reciprocal rank fusion):
a passage near the top of either list rises, one near the top of both rises
furthest.

The table is "chunks_v2" (passages of runs of turns, plus summary and notes
passages, with a full-text index). The first version's "chunks" table (one
row per speaker turn, no keyword index) is still searched, vector-only, until
the one-off rebuild of every meeting into the new table has finished, so
library search never goes blank while the rebuild runs; then it is dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

TABLE = "chunks_v2"
LEGACY_TABLE = "chunks"
READY_MARKER = "chunks_v2.ready"
TEXT_INDEX = "chunk_text_idx"
# How many unindexed rows the keyword index tolerates before it is rebuilt.
# Unindexed rows are still searched (by scanning), so this is about speed.
REINDEX_AFTER_ROWS = 500
# Reciprocal rank fusion constant: the standard 60 keeps one list's top hit
# from swamping a passage that ranks well in both.
RRF_K = 60
# The best keyword matches always make the cut, whatever the fused ranking
# says: a passage naming exactly what was asked about ("Brightwater", "HELIX") must
# never be crowded out by passages that are merely similar in meaning.
KEYWORD_SLOTS = 3


class VectorStore:
    def __init__(self, lancedb_dir: Path):
        import lancedb

        self._dir = Path(lancedb_dir)
        self._db = lancedb.connect(str(lancedb_dir))

    # -- tables ---------------------------------------------------------------

    def _names(self) -> list[str]:
        return list(self._db.table_names())

    def _table(self, name: str = TABLE):
        return self._db.open_table(name) if name in self._names() else None

    @property
    def ready(self) -> bool:
        """The new table holds every meeting: either the rebuild finished, or
        there was never an old table to rebuild from."""
        return (self._dir / READY_MARKER).exists() or LEGACY_TABLE not in self._names()

    def mark_ready(self) -> None:
        """The rebuild is complete: search the new table from now on, bring
        its keyword index fully up to date, and drop the old table."""
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / READY_MARKER).write_text("1\n")
        table = self._table()
        if table is not None:
            self._build_text_index(table)
        if LEGACY_TABLE in self._names():
            self._db.drop_table(LEGACY_TABLE)

    def indexed_meeting_ids(self) -> set[str]:
        table = self._table()
        if table is None:
            return set()
        rows = table.search().select(["meeting_id"]).limit(10_000_000).to_arrow()
        return set(rows.column("meeting_id").to_pylist())

    # -- writing --------------------------------------------------------------

    def replace_meeting(
        self, meeting_id: str, folder_id: int | None,
        chunks: list, vectors: np.ndarray,
    ) -> int:
        """Replace a meeting's passages (a re-save drops the old rows first)."""
        rows = [
            {
                "meeting_id": meeting_id,
                "folder_id": -1 if folder_id is None else int(folder_id),
                "source": chunk.source,
                "seq": int(chunk.seq),
                "chunk_text": chunk.text,
                "speaker": chunk.speaker,
                "start_s": float(chunk.start_s),
                "end_s": float(chunk.end_s),
                "vector": [float(x) for x in vectors[i]],
            }
            for i, chunk in enumerate(chunks)
        ]
        table = self._table()
        if table is not None:
            table.delete(f"meeting_id = '{_quote(meeting_id)}'")
        if not rows:
            return 0
        if table is None:
            table = self._db.create_table(TABLE, data=rows)
            self._build_text_index(table)
        else:
            table.add(rows)
            self._refresh_text_index(table)
        return len(rows)

    def delete_meeting(self, meeting_id: str) -> None:
        for name in (TABLE, LEGACY_TABLE):
            table = self._table(name)
            if table is not None:
                table.delete(f"meeting_id = '{_quote(meeting_id)}'")

    def set_meeting_folder(self, meeting_id: str, folder_id: int | None) -> None:
        """Update the folder stored on a meeting's passages when it is
        refiled, so folder-scoped retrieval follows the move. No re-embedding:
        only the folder column changes."""
        for name in (TABLE, LEGACY_TABLE):
            table = self._table(name)
            if table is not None:
                table.update(
                    where=f"meeting_id = '{_quote(meeting_id)}'",
                    values={"folder_id": -1 if folder_id is None else int(folder_id)},
                )

    def _build_text_index(self, table) -> None:
        # English stemming ("uploads" finds "upload") and stop words removed,
        # so a question's "what are the" carries no weight and its names do.
        table.create_fts_index(
            "chunk_text", replace=True, stem=True, remove_stop_words=True,
            language="English")

    def _refresh_text_index(self, table) -> None:
        try:
            stats = table.index_stats(TEXT_INDEX)
        except Exception:
            stats = None
        if stats is None or stats.num_unindexed_rows > REINDEX_AFTER_ROWS:
            self._build_text_index(table)

    # -- reading --------------------------------------------------------------

    def search(
        self, query_vector: np.ndarray, folder_id: int | None = None, limit: int = 8,
        query_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """The best passages, optionally scoped to one folder (None means the
        whole vault). With query_text, keyword matches are fused with the
        vector ranking; without it, the vector ranking alone."""
        if not self.ready:
            return self._legacy_search(query_vector, folder_id, limit)
        table = self._table()
        if table is None:
            return []
        where = None if folder_id is None else f"folder_id = {int(folder_id)}"
        pool = limit * 3

        vector_query = table.search([float(x) for x in query_vector]).limit(pool)
        if where:
            vector_query = vector_query.where(where, prefilter=True)
        by_vector = vector_query.to_list()
        if not query_text:
            return by_vector[:limit]

        try:
            text_query = table.search(query_text, query_type="fts").limit(pool)
            if where:
                text_query = text_query.where(where, prefilter=True)
            by_text = text_query.to_list()
        except Exception:
            by_text = []  # a question the keyword parser rejects still gets an answer
        return keep_top_keyword_hits(fuse_rankings([by_vector, by_text], limit), by_text, limit)

    def neighbours(self, meeting_id: str, source: str, seqs: list[int]) -> list[dict[str, Any]]:
        """Specific passages of one meeting by order, for widening a hit."""
        table = self._table()
        if table is None or not seqs or not self.ready:
            return []
        wanted = ", ".join(str(int(s)) for s in sorted(set(seqs)))
        return (table.search()
                .where(f"meeting_id = '{_quote(meeting_id)}' AND source = '{_quote(source)}' "
                       f"AND seq IN ({wanted})")
                .limit(len(seqs) + 5).to_list())

    def rows_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        table = self._table()
        if table is None:
            return []
        return (table.search().where(f"meeting_id = '{_quote(meeting_id)}'")
                .limit(10_000).to_list())

    def _legacy_search(self, query_vector, folder_id, limit) -> list[dict[str, Any]]:
        table = self._table(LEGACY_TABLE)
        if table is None:
            return []
        query = table.search([float(x) for x in query_vector]).limit(limit)
        if folder_id is not None:
            query = query.where(f"folder_id = {int(folder_id)}", prefilter=True)
        return query.to_list()


def passage_key(row: dict[str, Any]) -> tuple:
    return (row["meeting_id"], row.get("source", "transcript"), row.get("seq", row.get("start_s")))


def fuse_rankings(rankings: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    """Reciprocal rank fusion: each passage scores the sum of 1 / (k + rank)
    over the lists it appears in. Best first; the fused score is kept on the
    row as _fused."""
    scores: dict[tuple, float] = {}
    rows: dict[tuple, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            key = passage_key(row)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            rows.setdefault(key, row)
    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)[:limit]
    return [{**rows[key], "_fused": scores[key]} for key in ordered]


def keep_top_keyword_hits(fused: list[dict[str, Any]], by_text: list[dict[str, Any]],
                          limit: int, slots: int = KEYWORD_SLOTS) -> list[dict[str, Any]]:
    """Make sure the top keyword matches are in the result, replacing the
    weakest fused passages if they were squeezed out."""
    result = list(fused)
    present = {passage_key(row) for row in result}
    for row in by_text[:slots]:
        if passage_key(row) in present:
            continue
        if len(result) >= limit:
            # Drop the weakest passage that is not itself a guaranteed one.
            guaranteed = {passage_key(r) for r in by_text[:slots]}
            for i in range(len(result) - 1, -1, -1):
                if passage_key(result[i]) not in guaranteed:
                    present.discard(passage_key(result.pop(i)))
                    break
            else:
                break
        result.append(row)
        present.add(passage_key(row))
    return result


def _quote(value: str) -> str:
    return value.replace("'", "''")
