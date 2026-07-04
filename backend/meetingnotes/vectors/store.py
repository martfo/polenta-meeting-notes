"""The LanceDB vector store: one row per transcript chunk, scoped by folder
so retrieval can search one folder or the whole vault."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

TABLE = "chunks"


class VectorStore:
    def __init__(self, lancedb_dir: Path):
        import lancedb

        self._db = lancedb.connect(str(lancedb_dir))

    def _table(self):
        return self._db.open_table(TABLE) if TABLE in self._db.table_names() else None

    def replace_meeting(
        self, meeting_id: str, folder_id: int | None,
        chunks: list, vectors: np.ndarray,
    ) -> int:
        """Replace a meeting's chunks (a re-save drops the old rows first)."""
        rows = [
            {
                "meeting_id": meeting_id,
                "folder_id": -1 if folder_id is None else int(folder_id),
                "chunk_text": chunk.text,
                "speaker": chunk.speaker,
                "start_s": float(chunk.start_s),
                "end_s": float(chunk.end_s),
                "vector": [float(x) for x in vectors[i]],
            }
            for i, chunk in enumerate(chunks)
        ]
        if not rows:
            return 0
        table = self._table()
        if table is None:
            self._db.create_table(TABLE, data=rows)
        else:
            table.delete(f"meeting_id = '{meeting_id}'")
            table.add(rows)
        return len(rows)

    def search(
        self, query_vector: np.ndarray, folder_id: int | None = None, limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Nearest chunks, optionally scoped to one folder. folder_id None
        means the whole vault."""
        table = self._table()
        if table is None:
            return []
        query = table.search([float(x) for x in query_vector]).limit(limit)
        if folder_id is not None:
            query = query.where(f"folder_id = {int(folder_id)}")
        return query.to_list()

    def delete_meeting(self, meeting_id: str) -> None:
        table = self._table()
        if table is not None:
            table.delete(f"meeting_id = '{meeting_id}'")

    def set_meeting_folder(self, meeting_id: str, folder_id: int | None) -> None:
        """Update the folder stored on a meeting's chunks when it is refiled,
        so folder-scoped retrieval follows the move. No re-embedding: only the
        folder column changes."""
        table = self._table()
        if table is None:
            return
        table.update(
            where=f"meeting_id = '{meeting_id}'",
            values={"folder_id": -1 if folder_id is None else int(folder_id)},
        )

    def rows_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        table = self._table()
        if table is None:
            return []
        return table.search().where(f"meeting_id = '{meeting_id}'").limit(10_000).to_list()
