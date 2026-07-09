"""The FastAPI surface the Swift app talks to, on 127.0.0.1:8765.

Everything stateful is injected through AppState so tests run the same app
against fakes and a temporary vault."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from meetingnotes.config import Config
from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.jobs import queue as q
from meetingnotes.jobs.importer import import_wav
from meetingnotes.jobs.worker import Worker, retry_meeting
from meetingnotes.llm.chat import ask_meeting
from meetingnotes.llm.folders import suggest_folder
from meetingnotes.notes.notes import paste_image, read_notes, write_notes
from meetingnotes.storage import folders as fol
from meetingnotes.storage import meetings as m
from meetingnotes.storage.vault import Vault


@dataclass
class AppState:
    conn: Any
    vault: Vault
    config: Config
    worker: Worker
    lm_client: Any
    gallery: Gallery
    vector_store: Any = None
    text_embedder: Any = None
    ocr_engine: Any = None


class ImportRequest(BaseModel):
    path: str
    title: str | None = None
    source: str = "online"
    expected_speakers: int | None = None
    mic_path: str | None = None
    system_path: str | None = None


class ChatTurn(BaseModel):
    question: str
    answer: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatTurn] = []


class SummaryRequest(BaseModel):
    body: str


class GranolaImportRequest(BaseModel):
    csv_text: str


class FolderRequest(BaseModel):
    name: str


class CorrectionRequest(BaseModel):
    name: str | None = None


class NotesRequest(BaseModel):
    text: str


class LibraryChatRequest(BaseModel):
    question: str
    scope: str = "folder"
    folder: str | None = None


class AttendeeIn(BaseModel):
    name: str
    email: str | None = None


class AttendeesRequest(BaseModel):
    attendees: list[AttendeeIn]
    from_calendar: bool = True


class ImageRequest(BaseModel):
    data_base64: str
    suffix: str = "png"


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="MeetingNotes backend")
    conn, vault = state.conn, state.vault

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "lmstudio": state.lm_client.status(),
            "queued_jobs": conn.execute(
                "SELECT COUNT(*) FROM processing_jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0],
        }

    @app.post("/meetings/import")
    def import_meeting(request: ImportRequest) -> dict:
        source_path = Path(request.path)
        if not source_path.exists():
            raise HTTPException(404, f"no file at {request.path}")
        meeting_id = import_wav(
            conn, vault, source_path, title=request.title,
            source=request.source, expected_speakers=request.expected_speakers,
            mic_path=request.mic_path, system_path=request.system_path,
        )
        state.worker.notify()
        return {"meeting_id": meeting_id}

    @app.get("/meetings")
    def library() -> list:
        return m.library_listing(conn)

    @app.get("/meetings/{meeting_id}")
    def meeting_detail(meeting_id: str) -> dict:
        try:
            row = m.get_meeting(conn, meeting_id)
        except KeyError:
            raise HTTPException(404, "no such meeting")
        transcript_path = vault.transcript_path(meeting_id)
        meeting_md = vault.meeting_md_path(meeting_id)
        folder = None
        if row["folder_id"] is not None:
            folder_row = conn.execute(
                "SELECT name FROM folders WHERE id = ?", (row["folder_id"],)
            ).fetchone()
            folder = folder_row["name"] if folder_row else None
        return {
            **dict(row),
            "folder": folder,
            "attendees": [dict(a) for a in m.list_attendees(conn, meeting_id)],
            "transcript": transcript_path.read_text() if transcript_path.exists() else None,
            "summary": meeting_md.read_text() if meeting_md.exists() else None,
            "notes": read_notes(vault, meeting_id),
            "reveal_path": str(vault.meeting_dir(meeting_id)),
        }

    @app.delete("/meetings/{meeting_id}")
    def delete_meeting(meeting_id: str) -> dict:
        """Remove the meeting entirely: the database rows (cascading to
        attendees, speakers-in-meeting, and jobs), the search chunks, and the
        meeting's folder in the vault. Enrolled voices stay in the gallery."""
        import shutil

        try:
            m.get_meeting(conn, meeting_id)
        except KeyError:
            raise HTTPException(404, "no such meeting")
        if state.vector_store is not None:
            try:
                state.vector_store.delete_meeting(meeting_id)
            except Exception:
                pass  # the index row is derived data; the delete must not block
        conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        conn.commit()
        shutil.rmtree(vault.meeting_dir(meeting_id), ignore_errors=True)
        return {"deleted": True}

    @app.post("/meetings/{meeting_id}/retry")
    def retry(meeting_id: str) -> dict:
        job_id = retry_meeting(conn, meeting_id)
        state.worker.notify()
        return {"job_id": job_id}

    @app.post("/meetings/{meeting_id}/chat")
    def chat(meeting_id: str, request: ChatRequest) -> dict:
        transcript_path = vault.transcript_path(meeting_id)
        if not transcript_path.exists():
            raise HTTPException(409, "this meeting has no transcript yet")
        from meetingnotes.notes.ocr import read_ocr_texts

        answer = ask_meeting(
            state.lm_client, request.question,
            transcript_path.read_text(), read_notes(vault, meeting_id),
            ocr_texts=read_ocr_texts(vault, meeting_id) if state.config.ocr_enabled else [],
            history=[{"question": t.question, "answer": t.answer} for t in request.history],
        )
        return {"answer": answer}

    @app.get("/folders")
    def folders() -> list[str]:
        return fol.list_folders(conn)

    @app.post("/folders")
    def create_folder(request: FolderRequest) -> dict:
        try:
            return {"id": fol.create_folder(conn, request.name)}
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.put("/meetings/{meeting_id}/folder")
    def file_meeting(meeting_id: str, request: FolderRequest) -> dict:
        folder_id = fol.create_folder(conn, request.name)
        m.set_folder(conn, meeting_id, folder_id)
        # The search chunks carry their own folder copy for scoped retrieval,
        # so a refiled meeting must move in the index too.
        if state.vector_store is not None:
            try:
                state.vector_store.set_meeting_folder(meeting_id, folder_id)
            except Exception:
                import logging

                logging.getLogger("meetingnotes").warning(
                    "updating the search index folder failed",
                    extra={"meeting_id": meeting_id})
        return {"folder_id": folder_id}

    @app.post("/meetings/{meeting_id}/suggest-folder")
    def folder_suggestion(meeting_id: str) -> dict:
        row = m.get_meeting(conn, meeting_id)
        # Give the model the title, attendees, and a slice of the summary or
        # transcript, so the suggestion reflects what the meeting was about
        # rather than a bare title.
        parts = [f"Title: {row['title']}"]
        attendees = [a["name"] for a in m.list_attendees(conn, meeting_id)]
        if attendees:
            parts.append("Attendees: " + ", ".join(attendees))
        meeting_md = vault.meeting_md_path(meeting_id)
        transcript_path = vault.transcript_path(meeting_id)
        if meeting_md.exists():
            from meetingnotes.storage.frontmatter import read_meeting_md

            _, body = read_meeting_md(meeting_md)
            parts.append("Summary:\n" + body[:1500])
        elif transcript_path.exists():
            parts.append("Transcript extract:\n" + transcript_path.read_text()[:1500])

        suggestion = suggest_folder(state.lm_client, fol.list_folders(conn), "\n\n".join(parts))
        if suggestion is None:
            return {"folder": None, "is_new": False}
        return {"folder": suggestion.folder, "is_new": suggestion.is_new}

    @app.get("/meetings/{meeting_id}/speakers")
    def meeting_speakers(meeting_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM meeting_speakers WHERE meeting_id = ? ORDER BY id", (meeting_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _reindex(meeting_id: str) -> None:
        """Re-embed the meeting's search chunks with the resolved names, off
        the request thread. Derived data only; nothing the user wrote."""
        if state.vector_store is None or state.text_embedder is None:
            return
        import threading

        from meetingnotes.vectors.indexer import index_meeting

        def run() -> None:
            try:
                index_meeting(conn, vault, state.vector_store, state.text_embedder, meeting_id)
            except Exception:
                import logging

                logging.getLogger("meetingnotes").warning(
                    "re-indexing after a name change failed",
                    extra={"meeting_id": meeting_id, "stage": "embed"},
                )

        threading.Thread(target=run, name="reindex", daemon=True).start()

    def _refresh_for(assignment_id: int, old_name: str | None) -> None:
        """After a naming change: patch the name into the summary in place
        (never regenerate; the summary may carry the user's edits), re-render
        the transcript, and re-embed the search index."""
        from meetingnotes.storage.refresh import refresh_meeting_files, rename_speaker_in_summary

        row = asg.get_assignment(conn, assignment_id)
        rename_speaker_in_summary(vault, row["meeting_id"], old_name, row["display_name"])
        refresh_meeting_files(conn, vault, row["meeting_id"])
        _reindex(row["meeting_id"])

    def _display_name(assignment_id: int) -> str | None:
        return asg.get_assignment(conn, assignment_id)["display_name"]

    @app.post("/speaker-assignments/{assignment_id}/confirm")
    def confirm_assignment(assignment_id: int) -> dict:
        old_name = _display_name(assignment_id)
        asg.confirm(state.gallery, assignment_id)
        _refresh_for(assignment_id, old_name)
        return {"confirmed": True}

    @app.post("/speaker-assignments/{assignment_id}/correct")
    def correct_assignment(assignment_id: int, request: CorrectionRequest) -> dict:
        old_name = _display_name(assignment_id)
        asg.correct(state.gallery, assignment_id, request.name)
        _refresh_for(assignment_id, old_name)
        return {"corrected": True}

    @app.post("/speaker-assignments/{assignment_id}/attendee")
    def assign_attendee(assignment_id: int, request: FolderRequest) -> dict:
        old_name = _display_name(assignment_id)
        asg.assign_from_attendee(state.gallery, assignment_id, request.name)
        _refresh_for(assignment_id, old_name)
        return {"assigned": True}

    @app.get("/settings/owner-name")
    def get_owner_name() -> dict:
        return {"owner_name": state.config.owner_name}

    @app.put("/settings/owner-name")
    def set_owner_name(request: FolderRequest) -> dict:
        """The owner's display name: the microphone channel is labelled with
        it, so the owner never needs diarising."""
        from meetingnotes.config import save_config

        name = request.name.strip() or "Me"
        state.config.owner_name = name
        save_config(state.config, vault.config_path)
        return {"owner_name": name}

    @app.post("/settings/restore-summary-prompt")
    def restore_summary_prompt() -> dict:
        """Overwrite the vault's summary prompt with the current bundled
        default (the Granola-style one). Used when a vault carries an older
        prompt that predates a default change."""
        default = Path(__file__).resolve().parents[1] / "resources" / "summary_prompt.md"
        vault.summary_prompt_path.write_text(default.read_text())
        return {"restored": True}

    @app.put("/meetings/{meeting_id}/summary")
    def edit_summary(meeting_id: str, request: SummaryRequest) -> dict:
        """The user's edited summary body, written under fresh front matter.
        Only an explicit Retry regenerates a summary over this."""
        from meetingnotes.llm.summary import meeting_front_matter
        from meetingnotes.storage.frontmatter import write_meeting_md

        m.get_meeting(conn, meeting_id)
        write_meeting_md(
            vault.meeting_md_path(meeting_id),
            meeting_front_matter(conn, meeting_id),
            request.body,
        )
        conn.execute("UPDATE meetings SET summary_edited = 1 WHERE id = ?", (meeting_id,))
        conn.commit()
        return {"saved": True}

    @app.post("/meetings/{meeting_id}/attendees")
    def add_attendees(meeting_id: str, request: AttendeesRequest) -> dict:
        """Attendee pre-fill from the calendar invite. The names feed speaker
        assignment as the second naming priority after voice enrolment."""
        m.get_meeting(conn, meeting_id)
        existing = {(a["name"], a["email"]) for a in m.list_attendees(conn, meeting_id)}
        added = 0
        for attendee in request.attendees:
            if (attendee.name, attendee.email) in existing:
                continue
            m.add_attendee(conn, meeting_id, attendee.name, attendee.email,
                           from_calendar=request.from_calendar)
            added += 1
        return {"added": added}

    @app.put("/meetings/{meeting_id}/title")
    def rename_meeting(meeting_id: str, request: FolderRequest) -> dict:
        title = request.name.strip()
        if not title:
            raise HTTPException(422, "a meeting needs a title")
        m.get_meeting(conn, meeting_id)  # 404 via KeyError if absent
        conn.execute("UPDATE meetings SET title = ? WHERE id = ?", (title, meeting_id))
        conn.commit()
        from meetingnotes.storage.refresh import refresh_meeting_files

        refresh_meeting_files(conn, vault, meeting_id)
        return {"title": title}

    def _enqueue_summarise(meeting_id: str) -> None:
        queued = conn.execute(
            "SELECT COUNT(*) FROM processing_jobs WHERE meeting_id = ? "
            "AND stage = 'summarise' AND status = 'queued'",
            (meeting_id,),
        ).fetchone()[0]
        if queued == 0:
            q.enqueue(conn, meeting_id, stage="summarise")
        state.worker.notify()

    def _summary_action_for_notes_change(meeting_id: str) -> str:
        """Notes feed the summary, so a notes change means the summary is
        stale. A machine summary regenerates on its own; an edited one is the
        user's document, so the app asks first. Returns one of: none,
        regenerating, prompt."""
        if not vault.meeting_md_path(meeting_id).exists():
            return "none"  # no summary yet; the pipeline will use the notes
        row = m.get_meeting(conn, meeting_id)
        if row["summary_edited"]:
            return "prompt"
        _enqueue_summarise(meeting_id)
        return "regenerating"

    @app.put("/meetings/{meeting_id}/notes")
    def save_notes(meeting_id: str, request: NotesRequest) -> dict:
        write_notes(vault, meeting_id, request.text)
        return {"saved": True, "summary_action": _summary_action_for_notes_change(meeting_id)}

    @app.post("/meetings/{meeting_id}/notes/image")
    def add_image(meeting_id: str, request: ImageRequest) -> dict:
        relative = paste_image(
            vault, meeting_id, base64.b64decode(request.data_base64), request.suffix
        )
        # Recognise the image's text now, so chat, the summary, and the search
        # index can all use it. Cached in a sidecar; failure never blocks the
        # paste.
        ocr_text = ""
        if state.config.ocr_enabled and state.ocr_engine is not None:
            try:
                from meetingnotes.notes.ocr import store_image_ocr

                ocr_text = store_image_ocr(
                    vault.meeting_dir(meeting_id) / relative, state.ocr_engine)
                if ocr_text:
                    _reindex(meeting_id)  # make the recognised text searchable
            except Exception:
                import logging

                logging.getLogger("meetingnotes").warning(
                    "OCR of a pasted image failed", extra={"meeting_id": meeting_id})
        return {
            "path": relative,
            "ocr_found": bool(ocr_text),
            "summary_action": _summary_action_for_notes_change(meeting_id),
        }

    @app.post("/meetings/{meeting_id}/regenerate-summary")
    def regenerate_summary(meeting_id: str) -> dict:
        """The user chose to replace their edited summary with a fresh one."""
        m.get_meeting(conn, meeting_id)
        conn.execute("UPDATE meetings SET summary_edited = 0 WHERE id = ?", (meeting_id,))
        conn.commit()
        _enqueue_summarise(meeting_id)
        return {"regenerating": True}

    @app.post("/import/granola")
    def import_granola(request: GranolaImportRequest) -> dict:
        """Import a Granola CSV export. New meetings are added to the search
        index where the embedder is available."""
        from meetingnotes.tools.granola_import import import_granola_csv
        from meetingnotes.vectors.indexer import index_meeting

        indexer = None
        if state.vector_store is not None and state.text_embedder is not None:
            def indexer(meeting_id: str) -> None:  # noqa: F811
                index_meeting(conn, vault, state.vector_store, state.text_embedder, meeting_id)

        report = import_granola_csv(conn, vault, request.csv_text, indexer=indexer)
        return {
            "total_rows": report.total_rows,
            "imported": report.imported,
            "skipped": report.skipped,
            "empty": report.empty,
            "failed": report.failed,
            "reconciled": report.reconciled,
            "folders_created": report.folders_created,
            "mapped_columns": report.mapped_columns,
            "unmapped_columns": report.unmapped_columns,
            "failures": [
                {"row": f.row, "title": f.title, "reason": f.reason} for f in report.failures
            ],
            "warnings": report.warnings,
        }

    @app.post("/library/chat")
    def library_chat(request: LibraryChatRequest) -> dict:
        if state.vector_store is None or state.text_embedder is None:
            raise HTTPException(501, "library search is not set up on this install")
        from meetingnotes.llm.librarychat import ChatScope, ask_library

        scope = ChatScope(request.scope)
        folder = fol.folder_id(conn, request.folder) if request.folder else None
        if scope is ChatScope.FOLDER and folder is None:
            raise HTTPException(422, "folder scope needs an existing folder name")
        result = ask_library(
            state.lm_client, state.vector_store, state.text_embedder,
            request.question, scope=scope, folder_id=folder,
        )
        return {"answer": result.answer, "citations": result.citations}

    @app.post("/jobs/{meeting_id}/enqueue")
    def enqueue_pending(meeting_id: str) -> dict:
        """For capture recovery: the audio is already in the vault and the
        meeting row exists; put a job back on the queue."""
        job_id = q.enqueue(conn, meeting_id)
        state.worker.notify()
        return {"job_id": job_id}

    return app
