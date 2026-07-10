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
  docs/MANUAL_CHECKLIST.md     the [manual-hardware] checklist
  scripts/                     build_app.sh, build_dmg.sh, make_signing_cert.sh
  app/
    Support/                   Info.plist and MeetingNotes.entitlements
  backend/
    pyproject.toml
    scripts/                   build_british_map.py, make_fixtures.py
    meetingnotes/
      api/                     FastAPI routes
      pipeline/                whisperx transcription and diarisation
      enrolment/               matching, gallery, provenance, management
      storage/                 sqlite, vault, markdown read and write, keychain
      jobs/                    processing queue, worker, stages, import
      llm/                     LM Studio client, summary, chat, folders, library chat
      language/                em dash strip, British pass, dictionary flag, lint
      logging/                 log setup and helpers
      notes/                   notes.md, pasted images, OCR
      vectors/                 chunking, LanceDB store, bge-m3 indexer
      calendar/                read-only client and meeting detection
      resources/               american_to_british.json, technical_allowlist.txt,
                               summary_prompt.md default, dict/en_GB
      config.py
    tests/
      unit/
      integration/
      pipeline/                plus live smoke, run on demand
      manual/                  always-skipped placeholders for the checklist
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
      audio.wav                 mixed stream, for playback and retention
      mic.wav                   owner channel (present for captured meetings)
      system.wav                remote channel (present for captured meetings)
      segments.json             pipeline output; segments carry a channel field
      notes.md
      assets/
```

Folders are flat. A meeting belongs to exactly one folder.

Recordings are captured as two channels: the microphone (the owner) as mic.wav and the
system audio (remote participants) as system.wav, plus a mixed audio.wav for playback. The
microphone and the system-audio tap run on different device clocks and deliver buffers
independently, so every buffer is placed at its own host time against a single origin shared
by both channels (see AudioMixer.place): a stall on either stream becomes silence rather than
a shift, so sample index maps to the same instant in both WAVs and they are the same length.
Without this the channels drift apart and merging by start time piles one speaker's turns at
the end. The pipeline normalises and transcribes each channel separately, so quiet call audio
is not buried under the louder microphone and discarded by the transcriber's voice-activity
threshold. The mic channel is labelled with the owner name (config.owner_name) and needs no
diarisation; pyannote runs only on the system channel to separate the remote speakers; the
two are merged by timestamp into one transcript. Imported meetings (a single audio.wav, no
channel files) use the original single-channel path.

Before transcription each meeting builds a Whisper initial prompt from its participant names
(the owner plus calendar attendees) and the configured glossary (config.glossary), so the
model biases towards those words instead of a common-word homophone. The prompt is applied to
both channels. See pipeline/vocabulary.py.

## SQLite schema

- folders(id, name, created_at)
- meetings(id, title, folder_id, started_at, duration_s, source, vault_path,
  processing_status, summary_status, last_error, failed_stage, expected_speakers,
  summary_edited, created_at). last_error and failed_stage hold the plain-language
  failure record shown in the library, and Retry re-enqueues from failed_stage.
  expected_speakers is the optional count passed to diarisation. summary_edited marks a
  summary the user has changed by hand: a machine summary regenerates on its own when
  the notes change, an edited one only after the user agrees, and speaker renames are
  always patched into the body in place rather than regenerated.
- attendees(id, meeting_id, name, email, from_calendar)
- speakers(id, name, created_at)
- voiceprints(id, speaker_id, kind, embedding_ref, source_meeting_id, flagged,
  created_at), kind is positive or negative. flagged marks the stored positive that
  drove a false match, surfaced for review and removal.
- meeting_speakers(id, meeting_id, diarised_label, speaker_id, display_name, confirmed,
  assigned_by, matched_voiceprint_id, match_score, cluster_embedding_ref), assigned_by
  is enrolment, attendee, or manual. cluster_embedding_ref keeps the cluster voiceprint
  so a later confirmation or correction can teach the gallery.
- processing_jobs(id, meeting_id, stage, status, attempts, last_error, created_at,
  updated_at), status is queued, running, done, or failed. A job's stage is the stage to
  start from, which is how Retry resumes mid-pipeline.
- settings(key, value). Values here override config.json for audio_retention_days,
  match_threshold, and veto_margin, so the app can tune them without rewriting the file.

processing_status values: recording, queued, transcribing, diarising, enriching,
summarising, ready, needs_attention, failed. The embed stage shows enriching, because
the pinned status set has no embedding entry.

summary_status values: pending, ready, needs_attention.

Embedding vectors are not stored in SQLite: each voiceprint is a JSON file under
speakers/ and embedding_ref is its file name.

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
  "glossary": ["Camunda", "Workato", "CoSec"],
  "log_level": "info"
}
```

glossary is an optional list of domain terms (product names, jargon, acronyms) fed to
Whisper as an initial prompt alongside the meeting's participant names.

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
## Decisions
## Open Questions
```

Core items discussed and Next Steps are mandatory. Decisions and Open Questions are optional
and are left out when there is nothing to record. The validator matches a level-two heading by
its trimmed text, case-insensitive. The default prompt is Granola-style: each core item is a
bold sub-heading with bullets beneath, and Next Steps, Decisions, and Open Questions are
bulleted.

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

## Capture staging and the backend-down path

The app mixes each recording to one 16 kHz mono WAV and writes it to
MeetingVault/captures/ before telling the backend anything, so capture never depends on
the backend being up. Import then copies the audio into the meeting folder. If the
backend is unreachable at Stop, the pending recording is recorded in
settings/pending_recordings.json and enqueued when the backend returns.

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

## Packaging and provisioning

- The runtime is provisioned on first run into
  ~/Library/Application Support/MeetingNotes/runtime, separate from the vault: a bundled
  uv binary fetches a standalone CPython 3.11, creates runtime/venv, and installs the
  backend copy that ships inside the app bundle at Contents/Resources/backend. A
  .provisioned marker holding the runtime version is written only after a complete run,
  so a partial install is always detected and run over.
- scripts/build_app.sh assembles dist/MeetingNotes.app from the SwiftPM build,
  Support/Info.plist (which carries NSAudioCaptureUsageDescription and
  NSMicrophoneUsageDescription), the language resources, the backend copy, and uv, then
  signs inside out with the local identity "MeetingNotes Local Signing" and
  Support/MeetingNotes.entitlements. scripts/make_signing_cert.sh is the documented
  one-off that creates the identity. SKIP_SIGNING=1 skips signing for unsigned test
  builds.
- scripts/build_dmg.sh stages the app, an Applications symlink, and a short read-me with
  the right-click Open step, then builds dist/MeetingNotes.dmg with hdiutil. make dmg
  runs both scripts. Model weights never ship in the dmg.
- The Hugging Face token lives in the Keychain under service MeetingNotes, account
  huggingface-token; the Swift app writes it with SecItemAdd and the backend reads it
  with the security command.

## Toolchain notes

WhisperX's own load_audio shells out to ffmpeg, which once made ffmpeg a per-Mac
prerequisite. The dependency is now removed: pipeline/audio_io.py reads audio into the
float32 mono 16 kHz array WhisperX wants using the standard library (vault audio is
already 16 kHz mono 16-bit PCM), and diarisation is handed the same preloaded array so
pyannote never decodes a file either. Anything not already 16 kHz mono PCM (a different
rate, more channels, another container from an import) is converted first with afconvert,
which ships with macOS. So the shipped app needs no ffmpeg and the supervisor no longer
patches Homebrew onto the backend's PATH. This mirrors the pyannote embedding path, which
already passes preloaded waveforms and so has no torchcodec or FFmpeg library dependency.
pyannote.audio 4 and current whisperx take token=, not use_auth_token=; the older name
is silently ignored and downloads then fail on the gated repos.

On a machine with only the Command Line Tools, Swift Testing's framework lives outside
SwiftPM's default search path; the Makefile's gate-app target adds the search-path and
rpath flags and disables cross-import overlays. With full Xcode installed the flags
collapse to nothing.

## Definition of done

make gate runs every unit, integration-fixture, and contract-mock test and is the single
meaning of green. The pipeline tier runs at phase boundaries. The manual hardware checklist
(docs/MANUAL_CHECKLIST.md) is run once on a real Mac. A feature is complete when its
acceptance criteria tests pass and the fast gate still passes.
