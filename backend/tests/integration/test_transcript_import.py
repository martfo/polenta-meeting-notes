"""Importing a written transcript (a dropped .md file) as a meeting."""

from datetime import datetime

import pytest

from meetingnotes.jobs import queue as q
from meetingnotes.jobs.transcript_import import (
    import_transcript_file,
    import_transcript_text,
)
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import read_meeting_md

TRANSCRIPT = """---
title: Renewal call
date: 2026-06-01 14:30
attendees:
  - Ben Adams
  - Roger Neel
---

**[00:00:04] Ben Adams**
Shall we talk about the renewal?

**[00:02:10] Roger Neel**
Yes. The terms are the same as last year.
"""


def test_import_creates_a_meeting_with_transcript_and_no_audio(conn, vault):
    meeting_id = import_transcript_text(
        conn, vault, TRANSCRIPT, filename="renewal.md")

    row = m.get_meeting(conn, meeting_id)
    assert row["title"] == "Renewal call"
    assert row["started_at"].startswith("2026-06-01T14:30")
    assert row["source"] == "imported"
    assert row["duration_s"] == 131
    assert row["summary_status"] == "pending"

    meeting_dir = vault.meeting_dir(meeting_id)
    assert not vault.audio_path(meeting_id).exists()
    assert (meeting_dir / "segments.json").exists()

    transcript = vault.transcript_path(meeting_id).read_text()
    assert "**[00:00:04] Ben Adams**" in transcript
    assert "The terms are the same as last year." in transcript

    front, _ = read_meeting_md(vault.meeting_md_path(meeting_id))
    assert front["speakers"] == ["Ben Adams", "Roger Neel"]
    assert front["attendees"] == [{"name": "Ben Adams"}, {"name": "Roger Neel"}]
    assert front["tags"] == ["transcript-import"]
    assert [a["name"] for a in m.list_attendees(conn, meeting_id)] == [
        "Ben Adams", "Roger Neel"]


def test_import_enqueues_the_stages_that_need_no_audio(conn, vault):
    """There is nothing to transcribe or diarise, so the job starts at the
    search index and runs on to the summary."""
    meeting_id = import_transcript_text(conn, vault, TRANSCRIPT, filename="renewal.md")
    jobs = q.jobs_for_meeting(conn, meeting_id)
    assert [j.stage for j in jobs] == ["embed"]


def test_the_worker_indexes_and_summarises_an_imported_transcript(conn, vault, stages):
    """Handed to the real worker wiring, the meeting completes: only embed and
    summarise run, and it ends ready."""
    from meetingnotes.jobs.worker import Worker

    meeting_id = import_transcript_text(conn, vault, TRANSCRIPT, filename="renewal.md")
    worker = Worker(conn, stages)
    assert worker.run_pending() == 1

    assert stages.calls == [("embed", meeting_id), ("summarise", meeting_id)]
    assert m.get_meeting(conn, meeting_id)["processing_status"] == "ready"


def test_title_and_date_come_from_the_filename_when_the_file_is_bare(conn, vault, tmp_path):
    path = tmp_path / "Board review 2026-08-19 14-30.md"
    path.write_text("Ben Adams: We opened with the numbers.\n")

    meeting_id = import_transcript_file(conn, vault, path)
    row = m.get_meeting(conn, meeting_id)
    assert row["title"] == "Board review 2026 08 19 14 30"
    assert row["started_at"].startswith("2026-08-19T14:30")
    # Without timestamps in the text there is no honest duration to report.
    assert row["duration_s"] is None


def test_a_timestamp_only_filename_gets_a_readable_title(conn, vault, tmp_path):
    """A file named only for when it was recorded should not become a meeting
    called "2026 08 19 14 30"."""
    path = tmp_path / "2026-08-19_1430.md"
    path.write_text("Ben Adams: Morning all.\n")

    meeting_id = import_transcript_file(conn, vault, path)
    assert m.get_meeting(conn, meeting_id)["title"] == "Transcript 19 August 2026"


def test_an_explicit_title_wins(conn, vault, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Ignored heading\n\nBen Adams: Hello.\n")
    meeting_id = import_transcript_file(conn, vault, path, title="Chosen name")
    assert m.get_meeting(conn, meeting_id)["title"] == "Chosen name"


def test_a_file_with_no_turns_is_refused_and_leaves_nothing_behind(conn, vault, tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("---\ntitle: Nothing at all\n---\n")

    with pytest.raises(ValueError):
        import_transcript_file(conn, vault, path)

    assert m.library_listing(conn) == []
    assert list(vault.meetings_dir.iterdir()) == []


def test_a_missing_file_is_refused(conn, vault, tmp_path):
    with pytest.raises(ValueError):
        import_transcript_file(conn, vault, tmp_path / "nope.md")


def test_two_imports_of_the_same_file_are_separate_meetings(conn, vault, tmp_path):
    """Unlike the Granola export there is no stable document id, so a second
    drop is a second meeting rather than a silent overwrite."""
    path = tmp_path / "sync.md"
    path.write_text("Ben Adams: Hello.\n")
    first = import_transcript_file(conn, vault, path,
                                   started_at=datetime(2026, 6, 1, 9, 0).astimezone())
    second = import_transcript_file(conn, vault, path,
                                    started_at=datetime(2026, 6, 1, 9, 0).astimezone())
    assert first != second
    assert vault.meeting_dir(first).exists() and vault.meeting_dir(second).exists()


def _api(conn, vault, stages):
    """The real API surface over fakes, as the app talks to it."""
    import httpx
    from fastapi.testclient import TestClient

    from meetingnotes.api.app import AppState, create_app
    from meetingnotes.config import default_config
    from meetingnotes.enrolment.gallery import Gallery
    from meetingnotes.jobs.worker import Worker
    from meetingnotes.llm.client import LMStudioClient

    def lm_ready(request):
        return httpx.Response(200, json={"data": [{"id": "qwen", "state": "loaded"}]})

    state = AppState(
        conn=conn, vault=vault, config=default_config(vault.root),
        worker=Worker(conn, stages),
        lm_client=LMStudioClient(http=httpx.Client(transport=httpx.MockTransport(lm_ready))),
        gallery=Gallery(conn, vault),
    )
    return TestClient(create_app(state))


def test_the_endpoint_imports_a_dropped_file(conn, vault, stages, tmp_path):
    path = tmp_path / "renewal.md"
    path.write_text(TRANSCRIPT)

    with _api(conn, vault, stages) as client:
        response = client.post("/meetings/import-transcript", json={"path": str(path)})
        assert response.status_code == 200
        meeting_id = response.json()["meeting_id"]
        listing = client.get("/meetings").json()

    assert m.get_meeting(conn, meeting_id)["title"] == "Renewal call"
    assert [row["id"] for group in listing for row in group["meetings"]] == [meeting_id]


def test_the_endpoint_reports_a_missing_or_unusable_file(conn, vault, stages, tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("\n")

    with _api(conn, vault, stages) as client:
        assert client.post(
            "/meetings/import-transcript",
            json={"path": str(tmp_path / "nope.md")}).status_code == 404
        refused = client.post("/meetings/import-transcript", json={"path": str(empty)})
        assert refused.status_code == 400
        assert "empty" in refused.json()["detail"]


def test_the_speakers_the_text_names_become_the_meetings_speakers(conn, vault):
    """They show in the Speakers tab and can be renamed, but nothing is taught
    to the voice gallery: no voice was heard."""
    from meetingnotes.enrolment import assignments as asg
    from meetingnotes.enrolment.gallery import Gallery

    meeting_id = import_transcript_text(conn, vault, TRANSCRIPT, filename="renewal.md")
    rows = conn.execute(
        "SELECT * FROM meeting_speakers WHERE meeting_id = ? ORDER BY id", (meeting_id,)
    ).fetchall()
    assert [r["display_name"] for r in rows] == ["Ben Adams", "Roger Neel"]
    assert all(r["cluster_embedding_ref"] is None for r in rows)
    assert asg.display_names(conn, meeting_id) == {
        "Ben Adams": "Ben Adams", "Roger Neel": "Roger Neel"}

    # Renaming one works without a voiceprint and teaches the gallery nothing.
    gallery = Gallery(conn, vault)
    asg.correct(gallery, rows[1]["id"], "Roger O'Neel")
    assert asg.display_names(conn, meeting_id)["Roger Neel"] == "Roger O'Neel"
    assert conn.execute("SELECT COUNT(*) FROM voiceprints").fetchone()[0] == 0


def test_speaker_names_survive_a_reimport_of_the_rendered_transcript(conn, vault):
    """A transcript exported from the app and dropped back in keeps its
    speakers, so the round trip loses nothing."""
    first = import_transcript_text(conn, vault, TRANSCRIPT, filename="renewal.md")
    rendered = vault.transcript_path(first).read_text()

    second = import_transcript_text(conn, vault, rendered, filename="renewal-again.md")
    assert vault.transcript_path(second).read_text() == rendered
