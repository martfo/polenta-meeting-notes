# Polenta Meeting Notes — session handoff

A running summary for continuing work in a fresh Claude Code session. Pair this with
`DESIGN.md` (the pinned source of truth for schemas, formats, and architecture) and the git
log (58 commits, each a self-contained slice with its own tests).

## What this is

A native macOS app (SwiftUI + a supervised local Python/FastAPI backend) that records
meetings, transcribes them locally with WhisperX + pyannote, writes a structured summary via
LM Studio, and lets you chat with one meeting or across the library. Fully offline after a
one-time model download. British-English output, no em dashes. Product name **Polenta
Meeting Notes** (bundle id stays `co.uk.designturbine.meetingnotes` — never change it or you
reset TCC permissions and orphan the Keychain token). Original build brief is the first
message of the session; `DESIGN.md` reconciles it with the code.

## Repo layout

- `app/` — SwiftPM package. `MeetingNotesCore` (testable, UI-free logic) + `MeetingNotesApp`
  (executable, SwiftUI + Core Audio + Carbon hotkey). `app/Support/` has Info.plist,
  entitlements, AppIcon.
- `backend/` — uv-managed Python 3.11. `meetingnotes/` packages: api, pipeline, enrolment,
  storage, jobs, llm, language, notes, vectors, calendar, tools, resources.
- `scripts/` — `build_app.sh`, `build_dmg.sh`, `make_signing_cert.sh`, `make_icon.py`.
- `docs/MANUAL_CHECKLIST.md` — the [manual-hardware] acceptance items.
- `fixtures/` — audio, segments, embeddings, image, canned LLM responses.

## Build / test / ship

- `make gate` — the fast gate (backend pytest fast markers + `swift test`). Single meaning of
  green. Currently **105 backend + 24 app tests pass**.
- `make pipeline` — real WhisperX/pyannote against fixtures (needs `uv sync --extra pipeline`,
  the HF token in Keychain, and the pyannote licences accepted). Green as of last run.
- `make live-smoke` — needs LM Studio running with a model loaded.
- `make dmg` — builds and signs `dist/PolentaMeetingNotes.dmg`.

### Toolchain gotchas (all already handled, but know them)
- **uv** is required (`brew install uv`); backend runs under Python 3.11.
- **ffmpeg** is a per-Mac prerequisite (`brew install ffmpeg`) — WhisperX shells out to it.
  **This is a sign-off blocker (task #13): the shipped app must not need a manual ffmpeg
  install.** Either bundle a signed static arm64 ffmpeg, or drop the dependency by feeding
  WhisperX preloaded audio arrays. The supervisor currently patches `/opt/homebrew/bin` onto
  the backend child's PATH so the dev build works.
- **Swift Testing on Command-Line-Tools-only machines**: `Testing.framework` isn't on
  SwiftPM's default search path. The Makefile's `gate-app` adds `-F`/rpath flags and
  `-disable-cross-import-overlays`. With full Xcode the flags collapse to nothing.
- **Signing**: local self-signed cert "MeetingNotes Local Signing" via
  `scripts/make_signing_cert.sh` (imports PEM key+cert directly — OpenSSL 3 PKCS12 is
  unreadable by the Security framework). Manual one-off: set Trust → Always Trust for Code
  Signing in Keychain Access. `SKIP_SIGNING=1 make dmg` for unsigned test builds.

## The runtime-version mechanism (CRITICAL)

The shipped app provisions the Python backend into
`~/Library/Application Support/MeetingNotes/runtime` on first run. `runtimeVersion` in
`app/Sources/MeetingNotesCore/Provisioner.swift` (currently **"24"**) is a marker: bump it
whenever backend code changes so the installed app re-provisions and picks up the new
backend. **App-only changes need no bump; any backend change does.** A stale runtime silently
runs old backend code — the source of several "why isn't my fix working" moments this
session. The provisioner installs `backend[pipeline,embeddings]` extras.

## Current state: everything implemented

Phases 1–3 of the brief are complete (fast gate green, pipeline tier green, dmg builds),
plus a long tail of enhancements from a week of real use. Notable subsystems:

- **Capture**: dual-channel (runtime 24). Mic (owner) and system audio (remote) are captured
  as separate streams → `mic.wav` + `system.wav` + mixed `audio.wav`. Core Audio process tap
  for system audio; AVAudioEngine for mic. Setup runs OFF the main thread (fixes beachball).
  `CaptureController` is `@MainActor` with `nonisolated(unsafe)` audio objects driven on
  `ioQueue`. Input picker has a "System default" option (auto-follows AirPods) and switches
  mid-recording.
- **Pipeline** (`jobs/stages.py`): if `mic.wav`+`system.wav` exist → dual path: normalise each
  channel (`pipeline/normalize.py`, lifts quiet call audio above VAD), transcribe both, mic →
  owner name (no diarisation), pyannote only on system, merge by timestamp
  (`segments.merge_by_time`). Else single-channel (imports). Silence detection
  (`pipeline/silence.py`) skips transcription of silent audio; summary guard writes a
  "no speech" note instead of a hallucinated summary. Segments carry a `channel` field.
- **Enrolment**: voice gallery with threshold/veto matching, false-attribution correction
  that teaches the gallery. Owner voice enrolled from the clean mic channel.
- **Summary**: prompt at `settings/summary_prompt.md` (per-vault copy; bundled default is the
  Granola-style bulleted one). Variable substitution: `{{meeting_datetime}}`,
  `{{meeting_date}}`, `{{meeting_title}}` filled from the meeting row. Editable summaries with
  an Edit toggle; naming a speaker patches names in place (never regenerates over edits);
  notes changes regenerate a machine summary but prompt before touching an edited one.
- **Chat**: single-meeting (full transcript + notes + pasted-image OCR) and library-wide
  (LanceDB retrieval, folder-scoped by default, widens to whole vault when empty, cites only
  the meetings the answer drew on via a validated `Sources:` trailer). Multi-turn.
- **Calendar**: EventKit read-only. Wide due-window (5 min before → 25 min in), 15s poll,
  prompt-to-record (never auto-records). Call-app detection is edge-triggered on mic
  becoming busy (so idle Slack never prompts). Hand-started recordings borrow a
  currently-happening event's title/attendees. Auto-stop at meeting end + max-duration safety.
- **Library**: Folders / Date grouping toggle (Today/Yesterday/Earlier this week/This
  month/Older). Folder suggestion uses the summary content and prefers existing folders.
- **Global hotkey**: Carbon `RegisterEventHotKey` (works unfocused, no Accessibility perm).
  Default ⌃⌥⌘R, all modifiers configurable in Settings, toggles start/stop.
- **UI**: rendered markdown (`RichMarkdownView`) with comfortable typography; light-pill
  Start button; rounded three-dots meeting menu (Reveal/Regenerate/Delete); soft-fill inputs;
  brand logo in toolbar; full-window "Ask the library" panel with persistent conversation;
  Settings (owner name, recording shortcut, appearance font/size, summary prompt restore,
  Granola import, logs).
- **Granola import** (`tools/granola_import.py`): CSV importer, tolerant column mapping,
  atomic per-row writes with rollback, full reconciliation (every row → imported/skipped/
  empty/failed), folder auto-create. Settings → Import.
- **Cross-cutting**: rotating dual-format logs (never contain meeting content), Keychain-only
  HF token (via `security` CLI both sides), offline guarantee test, source-string lint.

## Key gotchas discovered this session (don't rediscover them)

- pyannote.audio 4 / current whisperx take `token=`, not `use_auth_token=` (silent auth fail).
- pyannote 4 file decoding needs torchcodec/ffmpeg libs; we pass **preloaded waveforms**
  instead (`enrolment/embedder.py`, `_load_waveform`).
- Whisper segments split on sentences, not speakers — the runner splits on word-level speaker
  changes so one Whisper segment spanning a handover becomes multiple turns.
- bge-m3 short name resolves to `BAAI/bge-m3` in the embedder.
- The supervised backend must not outlive the app (parent watchdog in `__main__.py`) and the
  app kills any orphan on the port at launch (BackendSupervisor). Empty/header-only recordings
  create no meeting; a startup sweep purges old empty ones.
- Recording start/stop is guarded by `isTransitioning` in AppModel to stop a double-start
  crash (this also made the hotkey reliably toggle).
- Granola's local cache (`~/Library/Application Support/Granola/cache-v6.json.enc`) is
  encrypted with a custom AES scheme; the official **CSV export** (Settings→Profile→Generate
  CSV) is the supported import path — do not try to decrypt the cache.

## Pending / open

- **Task #13 (sign-off blocker)**: remove the manual ffmpeg dependency (bundle static ffmpeg,
  or feed WhisperX preloaded arrays). See memory `ffmpeg-signoff-blocker`.
- **Task #14**: enrolment management screen (Phase 2.3 UI) — backend module
  `enrolment/management.py` is built and tested; the SwiftUI screen + endpoints are not.
- **Model choice**: default guidance is Qwen3-30B-A3B-Instruct in LM Studio; a larger model
  (dense 70B or bigger MoE) would improve summary attribution/faithfulness. App is
  model-agnostic — just load a different model. Worth A/B-ing on real meetings.

## Verification caveats (I cannot test these here)

Everything below is logic-tested with fakes but needs a **real Mac + real call** to confirm:
dual-channel capture actually splitting me/them, the remote channel no longer lossy after
normalisation, mid-recording input switching, auto-stop timing, and the global hotkey while
another app is focused. The Console subsystem for capture/tap diagnostics is
`co.uk.designturbine.meetingnotes`.

## User environment specifics

- Vault: `/Users/dtrb/Work/Meeting Vault`.
- macOS with Homebrew ffmpeg installed; AirPods often the input.
- HF token stored in Keychain (service `MeetingNotes`, account `huggingface-token`).
- git identity is set repo-local (Martin / martin@designturbine.co.uk).
- Commit trailer convention: `Co-Authored-By: Claude ...`.
