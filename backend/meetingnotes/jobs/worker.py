"""The single background worker.

One job at a time, first in, first out, through the stages transcribe,
diarise, enrich, embed, summarise. The stage implementations are injected as
a mapping of stage name to callable, so queue and concurrency tests run
against a fake fast pipeline and the real pipeline plugs in unchanged.

A job's stage is the stage to start from, which is how Retry re-enqueues from
a failed stage. Stage failures are recorded on the job and the meeting and the
worker moves on to the next job rather than crashing. If LM Studio is
unavailable at the summarise stage the meeting is still complete up to that
point: it is marked ready with summary pending and retried later.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Callable, Mapping

from meetingnotes.jobs import queue as q
from meetingnotes.llm.errors import LMStudioUnavailable
from meetingnotes.storage import meetings as m

log = logging.getLogger("meetingnotes.worker")

# The library shows one in-progress word per stage. embed keeps 'enriching'
# because the pinned status set has no embedding entry.
STAGE_STATUS = {
    "transcribe": "transcribing",
    "diarise": "diarising",
    "enrich": "enriching",
    "embed": "enriching",
    "summarise": "summarising",
}

StageFn = Callable[[str], None]


class Worker:
    def __init__(self, conn: sqlite3.Connection, stages: Mapping[str, StageFn]):
        self.conn = conn
        self.stages = stages
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()

    # -- synchronous core, used directly by tests ---------------------------

    def run_job(self, job: q.Job) -> None:
        conn = self.conn
        start = q.STAGES.index(job.stage)
        for stage in q.STAGES[start:]:
            m.set_processing_status(conn, job.meeting_id, STAGE_STATUS[stage])
            log.info("meeting %s stage %s started", job.meeting_id, stage)
            try:
                self.stages[stage](job.meeting_id)
            except LMStudioUnavailable:
                # Partial completion: everything before the summary is done and
                # usable. The summary stays pending until LM Studio returns.
                log.warning(
                    "meeting %s stage %s: LM Studio unreachable, summary left pending",
                    job.meeting_id, stage,
                )
                m.set_summary_status(conn, job.meeting_id, "pending")
                m.set_processing_status(conn, job.meeting_id, "ready")
                q.mark_done(conn, job.id)
                return
            except Exception as exc:
                message = f"{stage} failed: {exc}"
                log.error("meeting %s stage %s failed", job.meeting_id, stage)
                m.record_failure(conn, job.meeting_id, stage, message)
                q.mark_failed(conn, job.id, message)
                return
        summary = m.get_meeting(conn, job.meeting_id)["summary_status"]
        m.set_processing_status(
            conn, job.meeting_id,
            "needs_attention" if summary == "needs_attention" else "ready",
        )
        q.mark_done(conn, job.id)
        log.info("meeting %s processed", job.meeting_id)

    def run_pending(self) -> int:
        """Process queued jobs until the queue is empty. Returns the count."""
        done = 0
        while (job := q.claim_next(self.conn)) is not None:
            self.run_job(job)
            done += 1
        return done

    # -- background thread, used by the running service ---------------------

    def notify(self) -> None:
        self._wake.set()

    def start(self) -> None:
        q.reset_interrupted(self.conn)
        self._thread = threading.Thread(target=self._loop, name="worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.run_pending() == 0:
                self._wake.wait(timeout=1.0)
                self._wake.clear()


def retry_meeting(conn: sqlite3.Connection, meeting_id: str) -> int:
    """Re-enqueue a meeting from its failed stage, or from the summary when
    only the summary is pending. Clears the stored error."""
    row = m.get_meeting(conn, meeting_id)
    stage = row["failed_stage"]
    if stage is None:
        stage = "summarise" if row["summary_status"] != "ready" else "transcribe"
    m.clear_failure(conn, meeting_id)
    m.set_processing_status(conn, meeting_id, "queued")
    return q.enqueue(conn, meeting_id, stage=stage)
