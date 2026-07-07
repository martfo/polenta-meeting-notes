"""The real stage implementations, wired for the worker.

Every external dependency (the transcription engine, the speaker embedder,
the LM Studio client, the OCR engine, the chunk embedder) is injected, so the
same wiring runs in production and, with fixture-backed fakes, in the gated
tests."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Mapping

from meetingnotes.config import Config
from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.llm.summary import summarise_meeting
from meetingnotes.notes.notes import read_notes
from meetingnotes.notes.ocr import OcrEngine, ocr_texts_for_meeting
from meetingnotes.pipeline.runner import PipelineRunner
from meetingnotes.pipeline.segments import SegmentList, load_segments, save_segments
from meetingnotes.storage import meetings as m
from meetingnotes.storage.transcript import render_transcript
from meetingnotes.storage.vault import Vault

SEGMENTS_FILE = "segments.json"


def build_stages(
    conn: sqlite3.Connection,
    vault: Vault,
    config: Config,
    engine: Any,
    speaker_embedder: Any,
    lm_client: Any,
    ocr_engine: OcrEngine | None = None,
    chunk_indexer: Callable[[str], None] | None = None,
) -> Mapping[str, Callable[[str], None]]:
    runner = PipelineRunner(engine)
    gallery = Gallery(conn, vault)

    def segments_path(meeting_id: str):
        return vault.meeting_dir(meeting_id) / SEGMENTS_FILE

    def write_transcript(meeting_id: str) -> None:
        segments = load_segments(segments_path(meeting_id)).segments
        names = asg.display_names(conn, meeting_id)
        vault.transcript_path(meeting_id).write_text(render_transcript(segments, names))

    def _has_speech(meeting_id: str) -> bool:
        path = segments_path(meeting_id)
        return path.exists() and bool(load_segments(path).segments)

    def transcribe(meeting_id: str) -> None:
        from meetingnotes.pipeline.silence import is_silent

        audio = vault.audio_path(meeting_id)
        # Silence would make Whisper hallucinate a transcript, so a silent
        # recording is recorded as having no speech and skips the rest.
        if is_silent(audio, config.silence_rms_threshold):
            save_segments(SegmentList(segments=[]), segments_path(meeting_id))
            write_transcript(meeting_id)
            return
        result = runner.transcribe(audio)
        save_segments(result, segments_path(meeting_id))

    def diarise(meeting_id: str) -> None:
        if not _has_speech(meeting_id):
            write_transcript(meeting_id)
            return
        row = m.get_meeting(conn, meeting_id)
        aligned = load_segments(segments_path(meeting_id))
        result = runner.diarise(
            vault.audio_path(meeting_id), aligned,
            expected_speakers=row["expected_speakers"],
        )
        save_segments(result, segments_path(meeting_id))
        write_transcript(meeting_id)

    def enrich(meeting_id: str) -> None:
        if not _has_speech(meeting_id):
            return
        segments = load_segments(segments_path(meeting_id)).segments
        voiceprints = speaker_embedder.cluster_voiceprints(
            vault.audio_path(meeting_id), segments
        )
        for label, vector in sorted(voiceprints.items()):
            row_id = asg.record_cluster(gallery, meeting_id, label, [vector])
            asg.run_enrolment(
                gallery, row_id,
                threshold=config.match_threshold, veto_margin=config.veto_margin,
            )
        write_transcript(meeting_id)

    def embed(meeting_id: str) -> None:
        if chunk_indexer is not None:
            chunk_indexer(meeting_id)

    def summarise(meeting_id: str) -> None:
        transcript = vault.transcript_path(meeting_id).read_text()
        notes = read_notes(vault, meeting_id)
        ocr_texts = ocr_texts_for_meeting(
            vault, meeting_id, ocr_engine, enabled=config.ocr_enabled
        ) if ocr_engine is not None else []
        summarise_meeting(conn, vault, lm_client, meeting_id, transcript, notes, ocr_texts)

    return {
        "transcribe": transcribe,
        "diarise": diarise,
        "enrich": enrich,
        "embed": embed,
        "summarise": summarise,
    }
