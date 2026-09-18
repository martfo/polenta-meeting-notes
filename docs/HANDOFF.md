# Polenta Meeting Notes — session handoff

A running summary for continuing work in a fresh Claude Code session. Pair this with
`DESIGN.md` (the pinned source of truth for schemas, formats, and architecture) and the git
log (85 commits, each a self-contained slice with its own tests). **Current runtime version is
37**; HEAD is on `main`, pushed to `github.com/martfo/polenta-meeting-notes`. See the "Session
log" section below for everything done since the app first shipped (runtime 24 → 37).

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
  green. Currently **145 backend + 43 app tests pass**.
- `make pipeline` — real WhisperX/pyannote against fixtures (needs `uv sync --extra pipeline`,
  the HF token in Keychain, and the pyannote licences accepted). Green as of last run (7 tests),
  and diarisation/embedding run on the Apple GPU (MPS) there.
- `make live-smoke` — needs LM Studio running with a model loaded.
- `make dmg` — builds and signs `dist/PolentaMeetingNotes.dmg`. **See the build-hygiene gotcha
  below: after bumping `runtimeVersion`, `rm -rf app/.build` before `make dmg`** or the
  incremental release build can embed a stale version and provisioning mislabels the runtime.

### Toolchain gotchas (all already handled, but know them)
- **uv** is required (`brew install uv`); backend runs under Python 3.11.
- **ffmpeg is no longer needed** (task #13 resolved, runtime 25). `pipeline/audio_io.py`
  decodes audio with the standard library into the float32 mono 16 kHz array WhisperX and
  pyannote want (vault audio is already 16 kHz mono PCM); off-rate/multichannel/other-container
  audio is converted with `/usr/bin/afconvert` (ships with macOS). The supervisor no longer
  patches Homebrew onto the backend child's PATH.
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
`app/Sources/MeetingNotesCore/Provisioner.swift` (currently **"37"**, with a dated changelog
comment per version) is a marker: bump it whenever backend code changes so the installed app
re-provisions and picks up the new backend. **App-only changes need no bump; any backend change
does.** A stale runtime silently runs old backend code — the source of many "why isn't my fix
working" moments; the usual real cause was simply that the fixed DMG had not been installed.
The provisioner installs `backend[pipeline,embeddings]` extras. The `.provisioned` marker file
holds the version last installed; check it against `runtimeVersion` to tell whether an install
took.

## Current state: everything implemented

Phases 1–3 of the brief are complete (fast gate green, pipeline tier green, dmg builds),
plus a long tail of enhancements from a week of real use. Notable subsystems:

- **Capture**: dual-channel (runtime 24). Mic (owner) and system audio (remote) are captured
  as separate streams → `mic.wav` + `system.wav` + mixed `audio.wav`. Core Audio process tap
  for system audio; AVAudioEngine for mic. Setup runs OFF the main thread (fixes beachball).
  `CaptureController` is `@MainActor` with `nonisolated(unsafe)` audio objects driven on
  `ioQueue`. Input picker has a "System default" option (auto-follows AirPods) and switches
  mid-recording. **Common clock (added after runtime 24, app-only):** the two streams run on
  different device clocks, so each buffer is placed at its own host time against one shared
  origin (`AudioMixer.place`, fed by the AVAudioTime/AudioTimeStamp the callbacks used to
  discard); a stall becomes silence, not a shift, so mic.wav and system.wav stay the same
  length and index→time matches. This fixes the "one speaker's turns piled at the end" merge
  skew. **Needs a real-call check** (host-time glue is untestable off-hardware); the pure
  placement logic is gate-tested.
- **Pipeline** (`jobs/stages.py`): if `mic.wav`+`system.wav` exist → dual path: normalise each
  channel (`pipeline/normalize.py`, lifts quiet call audio above VAD), transcribe both, mic →
  owner name (no diarisation), pyannote only on system, merge by timestamp
  (`segments.merge_by_time`). Else single-channel (imports). Silence detection
  (`pipeline/silence.py`) skips transcription of silent audio; summary guard writes a
  "no speech" note instead of a hallucinated summary. Segments carry a `channel` field.
  Before transcription a Whisper initial prompt is built from the owner + calendar attendees +
  `config.glossary` (`pipeline/vocabulary.py`) and applied to both channels, biasing towards
  real names and domain terms. WhisperX reloads the model when the prompt changes.
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
  currently-happening event's title/attendees. Auto-stop is audio-aware (`AutoStop.decide`,
  polled each minute): the scheduled end is not a hard cutoff — past it the recording keeps
  going while the call is still audible and stops only once the system audio has been quiet for
  ~5 min (the call really ended) or the max-duration cap is hit, so overrunning meetings record
  in full. `CaptureController.secondsSinceSystemActivity()` supplies the silence measure.
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
- **Build hygiene (bit us):** `make dmg` runs an *incremental* `swift build -c release`. After
  bumping `runtimeVersion` the incremental release build embedded the *old* version in the
  binary (the bundled Python was fresh, so fixes still deployed, but provisioning wrote the wrong
  marker and the app thought it was already up to date). Fix: `rm -rf app/.build` before
  `make dmg` when the runtime changed, and verify the `.provisioned` marker equals the new
  `runtimeVersion` after installing.
- **Installing the fix is a separate step from shipping it.** Repeatedly this session, "still
  broken" meant the fixed DMG was built and pushed but not installed. To install for the user:
  `osascript -e 'quit app "Polenta Meeting Notes"'`, replace `/Applications/Polenta Meeting
  Notes.app` with `dist/Polenta Meeting Notes.app`, `open` it. A backend bump then re-provisions
  on launch (watch `.provisioned`). Verify the running venv code, not just the bundle:
  `~/Library/Application Support/MeetingNotes/runtime/venv` is what actually runs.
- **`AVAudioEngine.installTapOnBus` throws an uncatchable Obj-C NSException** on a bad/mismatched
  mic format; catch it via the `ObjCSupport.ObjCTryCatch` shim and validate formats first
  (see the AirPods crash fix). Swift `try/catch` cannot catch it.

## Session log — everything done since the app first shipped (runtime 24 → 37)

Chronological, grouped by theme. Each landed as its own commit with tests; the fast gate and
(where relevant) the pipeline tier stayed green. Runtime numbers in brackets; "app-only" means
no runtime bump.

**Repo / distribution**
- Pushed the whole project to `github.com/martfo/polenta-meeting-notes` (GPLv3, public).
  Reconciled the repo's existing LICENSE + short README on first push. Repo description and
  topics updated; README rewritten for the current feature set.

**ffmpeg removed [25]** — `pipeline/audio_io.py` (`load_audio_16k_mono`) reads audio with the
stdlib `wave` module into the float32 mono 16 kHz array WhisperX wants; diarisation is handed a
preloaded ndarray so pyannote never decodes a file; `afconvert` converts anything off-format.
`BackendSupervisor` no longer patches Homebrew onto PATH. Confirmed on the pipeline tier.

**Transcript quality (the big arc — Granola A/B on real meetings)**
- **Dual-channel timeline common clock [app-only]** — `AudioMixer.place` + `HostClock` +
  `SystemAudioTap` now place each buffer at its true host time on one shared origin (the
  callbacks used to discard the timestamps and concat positionally), so mic.wav and system.wav
  stay the same length and merge correctly. Fixed the "one speaker's turns piled at the end".
- **Vocabulary prompt [25]** — `pipeline/vocabulary.py` builds a Whisper `initial_prompt` from
  owner + calendar attendees + `config.glossary`; applied to both channels; model reloads on
  change. Rescues mis-heard names (Nisha vs "Misha") and domain terms.
- **AirPods sample-rate mislabel — the real remote-loss cause [app-only]** — the tap read its
  rate once at start; when AirPods' mic engages the output device drops rate mid-call, so every
  buffer was resampled ~2x too fast into chirp that Whisper's VAD rejects (remote side vanished,
  hallucinated "Thanks for watching"). `SampleRateEstimator` measures the true rate per buffer
  from sample-time vs host-time deltas. **Confirmed on a real AirPods call** (remote side
  recovered; centroid ~860 Hz vs ~3000 Hz when broken). Diagnostic: pitch/spectral check +
  stretch-and-transcribe on `system.wav`.
- **Loudness normalisation [26]** — `normalize.py` targets voiced RMS with a limiter instead of
  scaling by peak. Kept as a genuine robustness gain, but was NOT the remote-loss fix.
- **Idempotent enrich [27]** — enrich clears a meeting's `meeting_speakers` rows before
  recording fresh clusters, so Retry can reprocess a ready meeting (needed to re-run repaired
  audio) instead of failing the UNIQUE constraint.
- Two damaged historical meetings were recovered offline (de-gap + 2x stretch `system.wav`,
  re-run) back to Granola parity.

**Speed / GPU**
- **distil-large-v3 [29]** — English-only distillation of large-v3; ~2x faster on CPU, better
  punctuation, no accuracy loss (verified on the fixture).
- **Diarisation, embedding, alignment on the Apple GPU (MPS) [30]** — `pipeline/device.py`
  selects `mps` with `PYTORCH_ENABLE_MPS_FALLBACK=1` and a `MEETINGNOTES_FORCE_CPU` escape
  hatch. Benchmarked ~20x faster diarisation with identical speaker output. Transcription stays
  CPU-bound (CTranslate2 has no Metal — see open items for the MLX lever).
- **GPU meta-tensor fallback [31]** — a real run hit an uncatchable-looking meta-tensor error
  moving the wav2vec2 align model to MPS; couldn't reproduce it in isolation, so alignment,
  diarisation, and embedding each try the GPU and retry once on CPU on any failure, remembering
  the working device. Verified by injecting the exact error.
- **Transcription CPU threads [37]** — whisperx defaulted to 4 CPU threads; the engine now uses
  `min(os.cpu_count(), 12)`. Benchmarked ~2x faster on real audio (12 = sweet spot, no gain past
  it, memory-bandwidth bound). A 5-hour import dropped from ~49 min to ~24.

**Import**
- **Granola CSV import fixed for the real export [28]** — maps `document_created`,
  `workspace_name`, and the separate `notes` column (was swallowed by the summary).
- **Import any audio file [34]** — Settings → Import, or **drag-and-drop onto the window**
  (with a confirm). Any format `afconvert` reads (mp3/m4a/wav) is converted to the vault's
  16 kHz mono and run through the single-channel pipeline. Shared code path with the picker.
- **Filename date on import [35]** — `jobs/filename_date.py` reads a date/time out of names like
  `2026-08-19 14-30.m4a` or `20260819_143000.mp3` (day-first when ambiguous) and files the
  meeting under that day. Captures are untouched.
- **Adjustable recorded date [36]** — a date picker in the meeting header; `PUT
  /meetings/{id}/date` updates the `started_at` column + `meeting.md` front matter (the id/folder
  name is deliberately left as-is). Fixes imports filed on the wrong day.

**LLM / summaries / folders**
- **Summary prompt hardening [25-ish]** — never attribute points/actions to placeholder or
  channel labels (Me, Unassigned, Speaker N, diarisation labels).
- **Pending summaries auto-resume [33]** — the worker sweeps for `ready/pending` meetings when
  idle and re-enqueues them once LM Studio is reachable (`enqueue_pending_summaries`, throttled).
  Note: LM Studio can report a model "loaded" while chat still 500s ("Failed to resolve model
  metadata") — reloading the model in LM Studio fixes it. The sweep gate uses model-loaded, so
  it retries harmlessly until chat truly works.
- **Folder suggestion learns from filing** — the prompt lists each folder's example titles.
- **Folder suggestion cached [32]** — `suggested_folder` column; precomputed after summarising
  and served from cache (the LLM call is ~16s on a large model).
- **No generic catch-all folders [37]** — the prompt used to say "give it a short, general
  name", which made the model literally invent "General"/"Uncategorized". Prompt now prefers
  existing folders and forbids catch-alls; `parse_suggestion` drops generic new-folder names as
  a guard. Junk cached suggestions were cleared from the live vault.

**UI / app**
- New app icon (from `New Icon/` iconset).
- Summary is selectable without Edit — the detail screen polled the meeting every 2s and
  re-rendered, wiping the selection; now it stops polling once settled and only republishes a
  changed detail.
- Recording time shown in the Date view; right-click context menu on library rows
  (Reveal/Regenerate/Delete); folder + date grouping.
- HF token pre-filled from the Keychain on the first-run screen (it reappears after a runtime
  bump; `KeychainTokenStore.load`).
- **Find and replace across a meeting's summary and notes** — three-dots menu → sheet;
  `MeetingNotesCore.TextReplace`.
- **Audio-aware auto-stop** — see the Calendar bullet in "Current state".
- **AirPods installTap crash fix [app-only]** — starting a recording could abort the app:
  `AVAudioEngine.installTapOnBus` raises an uncatchable NSException when the mic format is
  invalid or disagrees with the hardware (AirPods rate switch). Fixed two ways: validate the
  input/output formats agree and install with a `nil` tap format, and wrap the call in a small
  Objective-C try/catch shim (`app/Sources/ObjCSupport`, `ObjCTryCatch`) so anything that slips
  through degrades to system-audio-only instead of crashing.

## Pending / open

- **GPU transcription (MLX) — the biggest remaining speed win.** Transcription is the only
  CPU-bound stage (faster-whisper's CTranslate2 has no Metal backend; diarisation/embedding
  already run on the GPU). The user imports very long recordings (one was 5 hours), so this is
  the real lever. Swapping the transcribe step to an Apple-GPU engine (MLX Whisper) would likely
  be several times faster again. It is a proper engine swap (new runtime dependency, re-wire
  transcribe/align keeping pyannote diarisation, full pipeline-tier testing). Discussed and
  deferred; distil + more threads was the low-risk interim.
- ~~**Task #13**: remove the ffmpeg dependency.~~ **Done** (runtime 25), confirmed on the
  pipeline tier.
- **Task #14**: enrolment management screen (Phase 2.3 UI) — backend module
  `enrolment/management.py` is built and tested; the SwiftUI screen + endpoints are not.
- **Optional follow-ups the user raised**: library-wide find/replace (fix a name across every
  meeting, not just one); cleaning up the meeting title when an imported filename is purely a
  timestamp; renaming the on-disk folder when the recorded date changes (currently the id/folder
  stays put, only the displayed date moves).
- **Model choice**: the user runs a large Qwen instruct model in LM Studio. App is
  model-agnostic. A non-thinking instruct model gives the cleanest strict-JSON folder replies.

## Verification caveats (I cannot test these here)

Everything below is logic-tested with fakes but needs a **real Mac + real call** to confirm:
dual-channel capture actually splitting me/them, the remote channel no longer lossy after
normalisation, mid-recording input switching, auto-stop timing, and the global hotkey while
another app is focused. The Console subsystem for capture/tap diagnostics is
`co.uk.designturbine.meetingnotes`.

**Now confirmed on real calls / the pipeline tier** (were caveats earlier this session):
- ffmpeg removal, vocabulary prompt (`asr_options`), and MPS diarisation/embedding — green on
  `make pipeline`.
- AirPods rate fix + the timeline common clock — a real AirPods call recovered the remote side
  (healthy `system.wav`, natural speech), and imported real meetings summarise at Granola parity.
- distil transcription, the CPU-thread speedup, folder-suggestion caching, filename-date import,
  adjustable date, pending-summary resume, and the installTap crash fix are all installed and
  running (runtime 37 verified live in the vault's venv).

**Still genuinely unverified / worth watching:**
- The installTap crash fix's worst case is untestable off the exact device state; the Obj-C
  catch is a hard guarantee it can no longer abort, but the degradation (system-audio-only when
  the mic can't be tapped) has not been exercised.
- Mid-recording input switching and the global hotkey while another app is focused remain
  logic-tested only.

## User environment specifics

- Vault: `/Users/dtrb/Work/Meeting Vault`. `config.json` there has `owner_name: "Martin"` and a
  `glossary` of the user's recurring names/terms; folders in use: DP, DesignTurbine, EON,
  Ocorian. The user imports long recordings (some multi-hour) named by date/time.
- macOS on an **M3 Ultra (20 P-cores, 60-core GPU, 256 GB)**; AirPods often the input. ffmpeg is
  no longer required (removed in runtime 25) — do not reintroduce a dependency on it.
- Installed app is **runtime 37** (verified: `.provisioned` marker = 37, venv code current).
- HF token stored in Keychain (service `MeetingNotes`, account `huggingface-token`).
- git identity is set repo-local (Martin / martin@designturbine.co.uk); remote is
  `github.com/martfo/polenta-meeting-notes` over gh HTTPS (the SSH key is not authorised — use
  the gh credential helper / HTTPS remote).
- Commit trailer convention: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- The user's workflow this session: implement → `make gate` → `make dmg` → commit → push, then
  (often) install the DMG for them. Push only when asked; they gate pushes explicitly.
