# DESIGN.md

This file pins the decisions the build depends on, so the code and the build prompt agree.
Write it before feature code and keep it in step with the codebase. Where this file and the
build prompt differ, treat this file as the source of truth for the codebase and reconcile
the two.

## Scope in one paragraph

A native macOS app that records meetings, transcribes them locally with speaker labels,
produces a structured summary, and lets the user chat with one transcript or across a folder
of transcripts. Everything runs on the machine. The only network access is a one-time model
download at first setup. English only for now. Recording must never wait for processing, so
back-to-back meetings queue behind one another while a new recording can always start.

## Platform and versions

- macOS 14.4 or later, Apple Silicon.
- App: Swift 5.9 or later, SwiftUI. Tests in Swift Testing, XCTest where it does not fit.
- Backend: Python 3.11. FastAPI, uvicorn, pydantic v2. Tests in pytest, with a marker that
  separates the fast gate from the slow pipeline tier.
- Transcription: WhisperX, faster-whisper backend on CPU, Whisper large-v3, English wav2vec2
  alignment. Diarisation via pyannote speaker-diarisation-community-1.
- Embeddings: bge-m3, run in the backend, vectors L2 normalised.
- Vector store: LanceDB. Index: SQLite through the standard library with a small migration
  runner. No server.
- British English pass: a bundled American-to-British map plus the en_GB Hunspell dictionary
  read through spylls. Both bundled for offline use.
- Environment: uv. The backend runs as a supervised child process of the app.
- Ports: LM Studio on 127.0.0.1:1234. Backend on 127.0.0.1:8765.

## Source tree

```
meeting-notes/
  DESIGN.md
  README.md
  Makefile                     make gate runs the fast gate
  app/
    Sources/
    Tests/                     named by AC id
  backend/
    pyproject.toml
    meetingnotes/
      api/                     FastAPI routes
      pipeline/                whisperx transcription and diarisation
      enrolment/               matching, gallery, provenance
      storage/                 sqlite, vault, markdown read and write
      jobs/                    processing queue and worker
      llm/                     LM Studio client, summary, chat
      language/                em dash strip, British pass, dictionary flag
      logging/                 log setup and helpers
      resources/               american_to_british.json, technical_allowlist.txt,
                               summary_prompt.md default
      config.py
    tests/
      unit/
      integration/
      pipeline/
  fixtures/
    audio/
    segments/
    embeddings/
    images/
    llm/
```

## Vault layout

```
MeetingVault/
  index.sqlite
  lancedb/
  speakers/
  logs/
  settings/
    summary_prompt.md
    config.json
  meetings/
    2026-07-02_1400_client-review/
      meeting.md
      transcript.md
      audio.wav
      notes.md
      assets/
```

Folders are flat. A meeting belongs to exactly one folder.

## SQLite schema

- folders(id, name, created_at)
- meetings(id, title, folder_id, started_at, duration_s, source, vault_path,
  processing_status, summary_status, created_at)
- attendees(id, meeting_id, name, email, from_calendar)
- speakers(id, name, created_at)
- voiceprints(id, speaker_id, kind, embedding_ref, source_meeting_id, created_at),
  kind is positive or negative
- meeting_speakers(id, meeting_id, diarised_label, speaker_id, display_name, confirmed,
  assigned_by, matched_voiceprint_id, match_score), assigned_by is enrolment, attendee,
  or manual
- processing_jobs(id, meeting_id, stage, status, attempts, last_error, created_at,
  updated_at), status is queued, running, done, or failed
- settings(key, value)

processing_status values: recording, queued, transcribing, diarising, enriching,
summarising, ready, needs_attention, failed.

summary_status values: pending, ready, needs_attention.

## LanceDB

One row per transcript chunk: meeting_id, folder_id, chunk_text, speaker, start_s, end_s,
and the embedding vector.

## config.json

```
{
  "vault_path": "/Users/martin/MeetingVault",
  "backend_port": 8765,
  "lmstudio_base_url": "http://127.0.0.1:1234/v1",
  "embedding_model": "bge-m3",
  "language": "en",
  "match_threshold": 0.75,
  "veto_margin": 0.10,
  "audio_retention_days": 30,
  "ocr_enabled": true,
  "log_level": "info"
}
```

The Hugging Face token is not in this file. It lives in the Keychain.

## File formats

### transcript.md

```
# Transcript

**[00:00:04] Ben Adams**
What Ben said in this turn, one paragraph per turn.

**[00:00:19] Roger Neel**
What Roger said next.
```

Timestamps are [hh:mm:ss] from the start. The name is the resolved name where known, else the
diarised label. One blank line between turns.

### meeting.md front matter

```
---
id: 2026-07-02_1400_client-review
title: Client review
date: 2026-07-02
start_time: "14:00"
duration_s: 3212
source: online
folder: Clients
attendees:
  - name: Ben Adams
    email: ben@example.com
speakers:
  - Ben Adams
  - Roger Neel
tags: []
processing_status: ready
summary_status: ready
---
```

### Summary headings

```
## Core items discussed
## Next Steps
## Open Questions
```

Core items discussed and Next Steps are mandatory. Open Questions is optional. The validator
matches a level-two heading by its trimmed text, case-insensitive.

### Folder suggestion contract

The model replies with strict JSON and nothing else:

```
{ "folder": "Clients", "is_new": false }
```

Parse defensively. A malformed reply, or a folder that is neither in the list nor marked new,
falls back to no suggestion. It never blocks saving.

## Speaker matching

For each diarised cluster:

1. Cluster voiceprint is the mean of its segment embeddings, L2 normalised.
2. For each speaker, pos is the highest cosine similarity to any positive voiceprint, neg is
   the highest to any negative voiceprint.
3. Candidate is the speaker with the highest pos.
4. Auto-assign only if pos is at or above match_threshold (0.75) and pos minus neg is at or
   above veto_margin (0.10). Otherwise leave for attendee or manual naming.
5. Record provenance: candidate, pos as the score, and the nearest positive voiceprint id.

Correcting a wrong auto-assignment records the cluster voiceprint as a negative example
against the wrongly matched speaker, adds it as a positive example only to the correct
speaker, and flags the positive voiceprint that drove the false match for review and removal.

## Processing queue

Capture and import both write audio to the vault and enqueue a job, then return at once. One
worker processes jobs first in, first out, through the stages transcribe, diarise, enrich,
embed, summarise. One meeting at a time. The queue is persisted in processing_jobs and resumes
after a restart. Summarising needs LM Studio; the earlier stages do not, so a meeting can
reach transcribed with summary pending when LM Studio is down. A failed stage records a
plain-language error and lets the worker move on.

## British English pass

Generated summary and chat text passes through, in order: the em dash strip, then the
American-to-British map (word-boundary, case preserving, map words only), then the dictionary
flag. The map is the only thing allowed to rewrite text automatically. The dictionary flags
unknown words without changing them and skips code spans, capitalised likely-names, and the
technical allowlist. The pass does not touch the user's own typed notes.

The map at backend/meetingnotes/resources/american_to_british.json is generated from the
VarCon dataset by backend/scripts/build_british_map.py, preferring British -ise forms,
filtering by SCOWL level, and excluding meaning-dependent words such as license and practice
and the software word program. Generation is a build-time step, not runtime. Keep the VarCon
licence notice at backend/meetingnotes/resources/NOTICE-VarCon.txt.

## Logging

A rotating log file at MeetingVault/logs/. Each line has an ISO timestamp, level, the meeting
id and stage where relevant, and a plain message. A companion file holds one JSON record per
line. Logs never contain transcript or summary text. Levels are set by log_level. The app uses
unified logging and mirrors errors to the same file.

## Definition of done

make gate runs every unit, integration-fixture, and contract-mock test and is the single
meaning of green. The pipeline tier runs at phase boundaries. The manual hardware checklist is
run once on a real Mac. A feature is complete when its acceptance criteria tests pass and the
fast gate still passes.
