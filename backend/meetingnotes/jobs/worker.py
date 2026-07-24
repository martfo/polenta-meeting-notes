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
import time
from typing import Any, Callable, Mapping

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
    def __init__(
        self, conn: sqlite3.Connection, stages: Mapping[str, StageFn],
        on_idle: Callable[[], int] | None = None, idle_interval: float = 60.0,
    ):
        self.conn = conn
        self.stages = stages
        # Called when the queue drains, at most every idle_interval seconds, to
        # pick up work that no job represents -- summaries left pending while LM
        # Studio was down, which should resume on their own once it returns. It
        # returns how many jobs it enqueued so the worker wakes to run them.
        self._on_idle = on_idle
        self._idle_interval = idle_interval
        self._last_idle = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()

    # -- synchronous core, used directly by tests ---------------------------

    def run_job(self, job: q.Job) -> None:
        conn = self.conn
        start = q.STAGES.index(job.stage)
        for stage in q.STAGES[start:]:
            m.set_processing_status(conn, job.meeting_id, STAGE_STATUS[stage])
            log.info("stage started", extra={"meeting_id": job.meeting_id, "stage": stage})
            try:
                self.stages[stage](job.meeting_id)
            except LMStudioUnavailable:
                # Partial completion: everything before the summary is done and
                # usable. The summary stays pending until LM Studio returns.
                log.warning(
                    "LM Studio unreachable, summary left pending",
                    extra={"meeting_id": job.meeting_id, "stage": stage},
                )
                m.set_summary_status(conn, job.meeting_id, "pending")
                m.set_processing_status(conn, job.meeting_id, "ready")
                q.mark_done(conn, job.id)
                return
            except Exception as exc:
                message = f"{stage} failed: {exc}"
                log.error("stage failed", extra={"meeting_id": job.meeting_id, "stage": stage})
                m.record_failure(conn, job.meeting_id, stage, message)
                q.mark_failed(conn, job.id, message)
                return
        summary = m.get_meeting(conn, job.meeting_id)["summary_status"]
        m.set_processing_status(
            conn, job.meeting_id,
            "needs_attention" if summary == "needs_attention" else "ready",
        )
        q.mark_done(conn, job.id)
        log.info("processed", extra={"meeting_id": job.meeting_id})

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
                self._sweep_idle()
                self._wake.wait(timeout=1.0)
                self._wake.clear()

    def _sweep_idle(self) -> None:
        """When the queue is empty, occasionally look for work no job
        represents. Throttled, and never fatal to the worker."""
        if self._on_idle is None:
            return
        now = time.monotonic()
        if now - self._last_idle < self._idle_interval:
            return
        self._last_idle = now
        try:
            if self._on_idle():
                self.notify()
        except Exception:
            log.warning("idle sweep failed", exc_info=True)


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


def enqueue_pending_summaries(conn: sqlite3.Connection, lm_client: Any) -> int:
    """Re-enqueue the summarise stage for every meeting left with its summary
    pending, once LM Studio is reachable again. This makes the "retried later"
    promise real: a summary skipped because LM Studio was down resumes on its
    own when it returns, with no user action.

    Guarded so it is safe to call on a timer: it does nothing while LM Studio is
    unreachable (so a down server is not hammered, and nothing loops), and skips
    a meeting that already has a job queued or running. Returns the count
    enqueued."""
    try:
        if lm_client.status() != "ready":
            return 0
    except Exception:
        return 0
    rows = conn.execute(
        "SELECT id FROM meetings WHERE summary_status = 'pending' "
        "AND processing_status = 'ready'"
    ).fetchall()
    count = 0
    for row in rows:
        busy = conn.execute(
            "SELECT 1 FROM processing_jobs WHERE meeting_id = ? "
            "AND status IN ('queued', 'running')", (row["id"],)
        ).fetchone()
        if busy:
            continue
        retry_meeting(conn, row["id"])
        count += 1
    return count
