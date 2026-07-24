"""Pending summaries resume on their own once LM Studio is reachable again."""

from __future__ import annotations

from meetingnotes.jobs.worker import enqueue_pending_summaries
from meetingnotes.storage import meetings as m
from tests.conftest import make_meeting


class StubLM:
    def __init__(self, status: str):
        self._status = status

    def status(self) -> str:
        return self._status


def _pending_meeting(conn, vault, meeting_id="2026-07-24_1000_m"):
    mid = make_meeting(conn, vault, meeting_id)
    m.set_processing_status(conn, mid, "ready")
    m.set_summary_status(conn, mid, "pending")
    return mid


def test_nothing_happens_while_lmstudio_is_down(conn, vault):
    mid = _pending_meeting(conn, vault)
    assert enqueue_pending_summaries(conn, StubLM("unreachable")) == 0
    assert enqueue_pending_summaries(conn, StubLM("no_model_loaded")) == 0
    assert m.get_meeting(conn, mid)["summary_status"] == "pending"


def test_pending_summary_is_reenqueued_when_ready(conn, vault):
    mid = _pending_meeting(conn, vault)
    assert enqueue_pending_summaries(conn, StubLM("ready")) == 1
    job = conn.execute(
        "SELECT stage, status FROM processing_jobs WHERE meeting_id = ?", (mid,)
    ).fetchone()
    assert job["stage"] == "summarise"  # resumes at the summary, not the top
    assert m.get_meeting(conn, mid)["processing_status"] == "queued"


def test_a_meeting_already_queued_is_not_enqueued_twice(conn, vault):
    _pending_meeting(conn, vault)
    assert enqueue_pending_summaries(conn, StubLM("ready")) == 1
    # A second sweep before the job runs must not pile on a duplicate.
    assert enqueue_pending_summaries(conn, StubLM("ready")) == 0


def test_a_ready_summary_is_left_alone(conn, vault):
    mid = make_meeting(conn, vault, "2026-07-24_1100_done")
    m.set_processing_status(conn, mid, "ready")
    m.set_summary_status(conn, mid, "ready")
    assert enqueue_pending_summaries(conn, StubLM("ready")) == 0
