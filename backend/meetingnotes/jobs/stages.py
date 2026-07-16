"""The real stage implementations, wired for the worker.

Every external dependency (the transcription engine, the speaker embedder,
the LM Studio client, the OCR engine, the chunk embedder) is injected, so the
same wiring runs in production and, with fixture-backed fakes, in the gated
tests."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from meetingnotes.config import Config
from meetingnotes.enrolment import assignments as asg
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.llm.summary import summarise_meeting
from meetingnotes.notes.notes import read_notes
from meetingnotes.notes.ocr import OcrEngine, ocr_texts_for_meeting
from meetingnotes.pipeline.runner import PipelineRunner
from meetingnotes.pipeline.segments import (
    SegmentList,
    load_segments,
    merge_by_time,
    save_segments,
)
from meetingnotes.pipeline.vocabulary import build_initial_prompt
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

    def mic_path(meeting_id: str):
        return vault.meeting_dir(meeting_id) / "mic.wav"

    def system_path(meeting_id: str):
        return vault.meeting_dir(meeting_id) / "system.wav"

    def is_dual(meeting_id: str) -> bool:
        """A recording captured as two channels: the owner on the mic, the
        remote participants on the system audio."""
        return mic_path(meeting_id).exists() and system_path(meeting_id).exists()

    def write_transcript(meeting_id: str) -> None:
        segments = load_segments(segments_path(meeting_id)).segments
        names = asg.display_names(conn, meeting_id)
        vault.transcript_path(meeting_id).write_text(render_transcript(segments, names))

    def _has_speech(meeting_id: str) -> bool:
        path = segments_path(meeting_id)
        return path.exists() and bool(load_segments(path).segments)

    def _vocabulary_prompt(meeting_id: str) -> str | None:
        """The meeting's people and the configured glossary, as a Whisper
        prompt that biases transcription towards names and domain terms."""
        names = [config.owner_name]
        names += [row["name"] for row in m.list_attendees(conn, meeting_id) if row["name"]]
        return build_initial_prompt(names, config.glossary)

    def _transcribe_channel(audio_path, channel, speaker, prompt):
        """Normalise a channel and transcribe it, tagging its segments. A
        silent channel yields nothing."""
        from meetingnotes.pipeline.normalize import normalise_wav
        from meetingnotes.pipeline.silence import is_silent

        if is_silent(audio_path, config.silence_rms_threshold):
            return []
        with tempfile.TemporaryDirectory() as tmp:
            boosted = normalise_wav(audio_path, Path(tmp) / "norm.wav")
            result = runner.transcribe(boosted, initial_prompt=prompt)
        for seg in result.segments:
            seg.channel = channel
            seg.speaker = speaker
        return result.segments

    def transcribe(meeting_id: str) -> None:
        from meetingnotes.pipeline.silence import is_silent

        prompt = _vocabulary_prompt(meeting_id)

        if is_dual(meeting_id):
            # The mic channel is entirely the owner and needs no diarisation;
            # the system channel is diarised later.
            mic_segments = _transcribe_channel(
                mic_path(meeting_id), "mic", config.owner_name, prompt)
            system_segments = _transcribe_channel(
                system_path(meeting_id), "system", None, prompt)
            merged = merge_by_time(mic_segments, system_segments)
            save_segments(SegmentList(segments=merged), segments_path(meeting_id))
            return

        audio = vault.audio_path(meeting_id)
        # Silence would make Whisper hallucinate a transcript, so a silent
        # recording is recorded as having no speech and skips the rest.
        if is_silent(audio, config.silence_rms_threshold):
            save_segments(SegmentList(segments=[]), segments_path(meeting_id))
            write_transcript(meeting_id)
            return
        result = runner.transcribe(audio, initial_prompt=prompt)
        save_segments(result, segments_path(meeting_id))

    def diarise(meeting_id: str) -> None:
        if not _has_speech(meeting_id):
            write_transcript(meeting_id)
            return
        row = m.get_meeting(conn, meeting_id)

        if is_dual(meeting_id):
            # pyannote runs only on the system channel, where it has the
            # simpler job of separating the remote speakers; the mic channel
            # is already known to be the owner.
            segments = load_segments(segments_path(meeting_id)).segments
            mic_segments = [s for s in segments if s.channel == "mic"]
            system_segments = [s for s in segments if s.channel == "system"]
            if system_segments:
                diarised = runner.diarise(
                    system_path(meeting_id),
                    SegmentList(segments=system_segments),
                    expected_speakers=row["expected_speakers"],
                ).segments
                for seg in diarised:
                    seg.channel = "system"
                system_segments = diarised
            merged = merge_by_time(mic_segments, system_segments)
            save_segments(SegmentList(segments=merged), segments_path(meeting_id))
            write_transcript(meeting_id)
            return

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
        # A re-run (retry over repaired audio) diarises fresh clusters; the
        # previous run's assignments claim the same labels and would fail the
        # UNIQUE constraint, so they are replaced, not accumulated.
        asg.clear_meeting(conn, meeting_id)

        if is_dual(meeting_id):
            segments = load_segments(segments_path(meeting_id)).segments
            mic_segments = [s for s in segments if s.channel == "mic"]
            system_segments = [s for s in segments if s.channel == "system"]

            # The owner is known from the mic channel: name it directly, and
            # enrol the owner's voice from their own clean channel.
            if mic_segments:
                owner_vps = speaker_embedder.cluster_voiceprints(
                    mic_path(meeting_id), mic_segments)
                for label, vector in owner_vps.items():
                    row_id = asg.record_cluster(gallery, meeting_id, label, [vector])
                    asg.assign_from_attendee(gallery, row_id, config.owner_name)
                    try:
                        asg.confirm(gallery, row_id)
                    except Exception:
                        pass  # naming still stands even if enrolment fails

            # The remote speakers are matched against the gallery as usual.
            if system_segments:
                remote_vps = speaker_embedder.cluster_voiceprints(
                    system_path(meeting_id), system_segments)
                for label, vector in sorted(remote_vps.items()):
                    row_id = asg.record_cluster(gallery, meeting_id, label, [vector])
                    asg.run_enrolment(
                        gallery, row_id,
                        threshold=config.match_threshold, veto_margin=config.veto_margin,
                    )
            write_transcript(meeting_id)
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

        # Precompute and cache the folder suggestion now, while LM Studio is up
        # and the summary is fresh, so the library shows it without a wait when
        # the meeting is opened. Only for an unfiled meeting, and never fatal to
        # the pipeline: a missed suggestion is just recomputed on demand later.
        if m.get_meeting(conn, meeting_id)["folder_id"] is None:
            from meetingnotes.llm.folder_filing import suggested_folder

            try:
                suggested_folder(conn, vault, lm_client, meeting_id)
            except Exception:
                pass

    return {
        "transcribe": transcribe,
        "diarise": diarise,
        "enrich": enrich,
        "embed": embed,
        "summarise": summarise,
    }
