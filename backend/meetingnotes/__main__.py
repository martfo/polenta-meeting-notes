"""The backend service: python -m meetingnotes <path-to-config.json>.

Launched and supervised by the Swift app, never by hand. The heavy models are
constructed lazily on first use so the service comes up fast and health
checks answer at once."""

from __future__ import annotations

import sys
from pathlib import Path


class _Lazy:
    """Defers construction to the first attribute access."""

    def __init__(self, factory):
        self._factory = factory
        self._obj = None

    def __getattr__(self, name):
        if self._obj is None:
            self._obj = self._factory()
        return getattr(self._obj, name)


def _exit_with_parent() -> None:
    """The backend is a supervised child of the app and must never outlive
    it: an orphan keeps the port and answers the next app version with stale
    code. When the parent dies we are reparented to launchd (pid 1)."""
    import os
    import threading
    import time

    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(2.0)
            if parent != 1 and os.getppid() == 1:
                os._exit(0)

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


def main(config_path: str) -> None:
    import uvicorn

    from meetingnotes.api.app import AppState, create_app
    from meetingnotes.config import load_config
    from meetingnotes.enrolment.gallery import Gallery
    from meetingnotes.jobs.stages import build_stages
    from meetingnotes.jobs.worker import Worker
    from meetingnotes.llm.client import LMStudioClient
    from meetingnotes.logging.setup import configure_logging
    from meetingnotes.notes.ocr import VisionOcr
    from meetingnotes.storage.db import open_db
    from meetingnotes.storage.keychain import read_hf_token
    from meetingnotes.storage.vault import Vault

    _exit_with_parent()
    config = load_config(Path(config_path))
    vault = Vault(config.vault_path).ensure()
    configure_logging(vault.logs_dir, config.log_level)
    conn = open_db(vault.db_path)

    from meetingnotes.storage.cleanup import purge_empty_recordings

    purged = purge_empty_recordings(conn, vault)
    if purged:
        import logging

        logging.getLogger("meetingnotes").info(
            "removed %d empty-recording meetings at startup", len(purged))

    lm_client = LMStudioClient(config.lmstudio_base_url)
    gallery = Gallery(conn, vault)

    def make_engine():
        from meetingnotes.pipeline.whisperx_engine import WhisperXEngine

        return WhisperXEngine(hf_token=read_hf_token())

    def make_embedder():
        from meetingnotes.enrolment.embedder import PyannoteSpeakerEmbedder

        return PyannoteSpeakerEmbedder(hf_token=read_hf_token())

    from meetingnotes.vectors.indexer import BgeM3Embedder, index_meeting
    from meetingnotes.vectors.store import VectorStore

    store = VectorStore(vault.lancedb_dir)
    text_embedder = _Lazy(lambda: BgeM3Embedder(config.embedding_model))

    def chunk_indexer(meeting_id: str) -> None:
        import logging

        try:
            index_meeting(conn, vault, store, text_embedder, meeting_id)
        except ModuleNotFoundError:
            logging.getLogger("meetingnotes").warning(
                "embedding model not installed; library search skipped",
                extra={"meeting_id": meeting_id, "stage": "embed"},
            )

    stages = build_stages(
        conn, vault, config,
        engine=_Lazy(make_engine),
        speaker_embedder=_Lazy(make_embedder),
        lm_client=lm_client,
        ocr_engine=VisionOcr(),
        chunk_indexer=chunk_indexer,
    )
    worker = Worker(conn, stages)
    worker.start()

    app = create_app(AppState(
        conn=conn, vault=vault, config=config, worker=worker,
        lm_client=lm_client, gallery=gallery,
        vector_store=store, text_embedder=text_embedder,
    ))
    try:
        uvicorn.run(app, host="127.0.0.1", port=config.backend_port, log_config=None)
    finally:
        worker.stop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m meetingnotes <path-to-config.json>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
