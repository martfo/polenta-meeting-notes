"""AC-X-c: bootstrap. The app launches and health-checks the backend, and
the backend reports LM Studio reachable or gives a clear state when it is
not. The health-check logic runs here against fakes; the real model download
is a live-smoke."""

import httpx
from fastapi.testclient import TestClient

from meetingnotes.api.app import AppState, create_app
from meetingnotes.config import default_config
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.jobs.worker import Worker
from meetingnotes.llm.client import LMStudioClient


def make_app(conn, vault, stages, lm_handler):
    lm_client = LMStudioClient(http=httpx.Client(transport=httpx.MockTransport(lm_handler)))
    state = AppState(
        conn=conn, vault=vault, config=default_config(vault.root),
        worker=Worker(conn, stages), lm_client=lm_client,
        gallery=Gallery(conn, vault),
    )
    return create_app(state)


def test_ac_x_c_bootstrap_healthcheck(conn, vault, stages):
    """The health endpoint the supervisor polls: backend up, LM Studio state
    reported plainly for each case."""

    def lm_ready(request):
        return httpx.Response(200, json={"data": [{"id": "qwen", "state": "loaded"}]})

    def lm_down(request):
        raise httpx.ConnectError("connection refused")

    with TestClient(make_app(conn, vault, stages, lm_ready)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["lmstudio"] == "ready"
        assert body["queued_jobs"] == 0

    with TestClient(make_app(conn, vault, stages, lm_down)) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok", "the backend itself is healthy"
        assert body["lmstudio"] == "unreachable", "a clear message, not a crash"


def test_meeting_rename_and_speaker_naming_refresh(conn, vault, stages, fixtures_dir):
    """Renaming a meeting updates the row and front matter. Naming a speaker
    patches the name into the summary body in place, keeping the user's
    edits, and never queues a regeneration."""
    import shutil

    import httpx

    from meetingnotes.enrolment import assignments as asg
    from meetingnotes.enrolment.gallery import Gallery
    from meetingnotes.storage import meetings as m
    from meetingnotes.storage.frontmatter import read_meeting_md, write_meeting_md
    from tests.conftest import make_meeting

    def lm_ready(request):
        return httpx.Response(200, json={"data": [{"id": "qwen", "state": "loaded"}]})

    meeting_id = make_meeting(conn, vault)
    shutil.copyfile(
        fixtures_dir / "segments" / "two_speaker_meeting.json",
        vault.meeting_dir(meeting_id) / "segments.json",
    )
    write_meeting_md(
        vault.meeting_md_path(meeting_id), {"id": meeting_id},
        "## Core items discussed\n\nSPEAKER_00 explained the budget. MY OWN EDIT.\n",
    )
    gallery = Gallery(conn, vault)
    first = asg.record_cluster(gallery, meeting_id, "SPEAKER_00", [[1.0] + [0.0] * 7])
    second = asg.record_cluster(gallery, meeting_id, "SPEAKER_01", [[0.0, 1.0] + [0.0] * 6])

    with TestClient(make_app(conn, vault, stages, lm_ready)) as client:
        response = client.put(f"/meetings/{meeting_id}/title", json={"name": "Talking to myself"})
        assert response.status_code == 200
        assert m.get_meeting(conn, meeting_id)["title"] == "Talking to myself"
        front, _ = read_meeting_md(vault.meeting_md_path(meeting_id))
        assert front["title"] == "Talking to myself"

        client.post(f"/speaker-assignments/{first}/correct", json={"name": "Martin"})
        client.post(f"/speaker-assignments/{second}/correct", json={"name": "Echo"})

        # Editing the summary body persists it under fresh front matter.
        client.put(f"/meetings/{meeting_id}/summary",
                   json={"body": read_meeting_md(vault.meeting_md_path(meeting_id))[1] + "\nAPPENDED."})

    assert "Martin" in vault.transcript_path(meeting_id).read_text()
    front, body = read_meeting_md(vault.meeting_md_path(meeting_id))
    assert "Martin explained the budget." in body, "the name is patched in place"
    assert "SPEAKER_00" not in body
    assert "MY OWN EDIT." in body and "APPENDED." in body, "edits survive naming"
    assert "Martin" in front["speakers"] and "Echo" in front["speakers"]
    # Never a regeneration behind the user's back.
    queued = conn.execute(
        "SELECT COUNT(*) FROM processing_jobs WHERE meeting_id = ? AND status = 'queued'",
        (meeting_id,),
    ).fetchone()[0]
    assert queued == 0


def test_notes_change_summary_regeneration_rules(conn, vault, stages, fixtures_dir):
    """A notes change regenerates a machine summary on its own; an edited
    summary is the user's document, so the app is told to ask first."""
    import httpx

    from meetingnotes.storage.frontmatter import write_meeting_md
    from tests.conftest import make_meeting

    def lm_ready(request):
        return httpx.Response(200, json={"data": [{"id": "qwen", "state": "loaded"}]})

    meeting_id = make_meeting(conn, vault)

    def queued_summarise():
        return conn.execute(
            "SELECT COUNT(*) FROM processing_jobs WHERE meeting_id = ? "
            "AND stage = 'summarise' AND status = 'queued'", (meeting_id,),
        ).fetchone()[0]

    with TestClient(make_app(conn, vault, stages, lm_ready)) as client:
        # No summary yet: a notes change triggers nothing.
        response = client.put(f"/meetings/{meeting_id}/notes", json={"text": "early note"})
        assert response.json()["summary_action"] == "none"
        assert queued_summarise() == 0

        # A machine summary follows the notes automatically, deduped.
        write_meeting_md(vault.meeting_md_path(meeting_id), {"id": meeting_id}, "Machine summary.")
        for text in ("first change", "second change"):
            response = client.put(f"/meetings/{meeting_id}/notes", json={"text": text})
            assert response.json()["summary_action"] == "regenerating"
        assert queued_summarise() == 1

        # The user edits the summary: from then on, ask first.
        client.put(f"/meetings/{meeting_id}/summary", json={"body": "My edited summary."})
        response = client.put(f"/meetings/{meeting_id}/notes", json={"text": "third change"})
        assert response.json()["summary_action"] == "prompt"
        assert queued_summarise() == 1, "nothing new queued behind the user's back"

        # The user confirms: the edit flag clears and a regeneration queues.
        client.post(f"/meetings/{meeting_id}/regenerate-summary")

    from meetingnotes.storage import meetings as m

    assert m.get_meeting(conn, meeting_id)["summary_edited"] == 0
    # Still one job: the earlier queued regeneration serves this too, so the
    # dedupe holds across the whole flow.
    assert queued_summarise() == 1


def test_attendee_prefill_endpoint(conn, vault, stages):
    """Attendees from a calendar invite land on the meeting, marked as from
    the calendar, deduplicated, and visible in the detail the app reads."""
    import httpx

    from tests.conftest import make_meeting

    def lm_ready(request):
        return httpx.Response(200, json={"data": [{"id": "qwen", "state": "loaded"}]})

    meeting_id = make_meeting(conn, vault)
    payload = {"attendees": [
        {"name": "Ben Adams", "email": "ben@example.com"},
        {"name": "Roger Neel", "email": None},
    ]}

    with TestClient(make_app(conn, vault, stages, lm_ready)) as client:
        assert client.post(f"/meetings/{meeting_id}/attendees", json=payload).json() == {"added": 2}
        # The same invite offered again adds nothing.
        assert client.post(f"/meetings/{meeting_id}/attendees", json=payload).json() == {"added": 0}

        detail = client.get(f"/meetings/{meeting_id}").json()
        assert [(a["name"], a["from_calendar"]) for a in detail["attendees"]] == [
            ("Ben Adams", 1), ("Roger Neel", 1),
        ]
