---
name: handoff
description: >-
  Update or regenerate docs/HANDOFF.md, the running session-handoff doc that lets a fresh Claude
  Code session pick up this project (Polenta Meeting Notes). Use when the user asks to update or
  write the handoff, "hand off", "write up what we've done so a new session can continue", or
  after a meaningful batch of work that a later session should inherit. It refreshes the stale
  metadata (commit count, runtimeVersion, test counts, HEAD), appends a themed Session log of
  what changed and how it was verified, and updates the open items, gotchas, and environment.
---

# Handoff: keep docs/HANDOFF.md current

`docs/HANDOFF.md` is the one file a fresh Claude Code session reads to continue this project.
Pair it with `DESIGN.md` (schemas/architecture, the source of truth) and the git log. Keep it
accurate and current; a stale handoff is worse than none.

## When to use
- The user asks to update/write the handoff, or to "write up everything done so a new session
  can continue".
- At the end of a batch of shipped work worth inheriting.

## Its structure (preserve these sections, in order)
What this is · Repo layout · Build / test / ship · The runtime-version mechanism (CRITICAL) ·
Current state · Key gotchas · Session log · Pending / open · Verification caveats · User
environment specifics.

## Procedure

1. **Gather facts — never guess.** Run these and use the real values:
   - `git rev-list --count HEAD` → commit count
   - `grep -o 'runtimeVersion = "[0-9]*"' app/Sources/MeetingNotesCore/Provisioner.swift`
   - Backend tests: `cd backend && uv run pytest -q -m "not pipeline and not live_smoke" | tail -1`
   - App tests: `make gate-app 2>&1 | grep "Test run with"`
   - `git rev-parse --short HEAD`, `git status -sb`, and whether local == `origin/main`.

2. **Fix stale metadata** in the intro line, "Build / test / ship" (the `make gate` test
   counts), and "The runtime-version mechanism" (the current `runtimeVersion`).

3. **Extend the "Session log"** with everything shipped since the last handoff, grouped by
   theme (repo/distribution, transcript quality, speed/GPU, import, LLM/summaries/folders,
   UI/app). For each item give: what it does, its runtime number in brackets (or "app-only" if
   no bump), briefly why, and how it was verified (fast gate / `make pipeline` / a real call).
   Merge with the existing log rather than duplicating.

4. **Update "Pending / open"**: strike through finished items, add new ones, and keep the big
   levers visible (e.g. MLX GPU transcription is the current top open item).

5. **Update "Key gotchas"** with anything newly learned so it is not rediscovered.

6. **Update "Verification caveats"**: move anything now confirmed (on the gate, the pipeline
   tier, or a real call) into a "confirmed" list; keep only what is genuinely still unverified.

7. **Update "User environment specifics"** if it changed (vault path, hardware, installed
   runtime, config like `owner_name`/`glossary`/folders, remote/auth).

8. Read the file first; make targeted edits. If the numbers or facts are unchanged, do not
   churn the prose.

## Conventions
- Voice: concise and factual, one idea per bullet, like the rest of the file. Em dashes are
  fine **in this doc** — the "no em dashes" rule applies only to the app's own output
  (summaries and chat), not to repo docs.
- Convert relative dates to absolute (this session's clock may be wrong across turns).
- Commit and push **only when the user asks**; they gate pushes explicitly. Commit-message
  trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Facts a good handoff always carries
- The current `runtimeVersion` and the bump rule: **any backend change needs a bump; app-only
  changes do not.** The `.provisioned` marker holds the version last installed.
- Build hygiene: after bumping `runtimeVersion`, `rm -rf app/.build` before `make dmg`, or the
  incremental release build can embed the old version and provisioning mislabels the runtime.
- **Installing the fix is a separate step from shipping it** — "still broken" usually meant the
  fixed DMG was pushed but not installed. Verify the running venv
  (`~/Library/Application Support/MeetingNotes/runtime/venv`), not just the app bundle.
- `make gate` is the single meaning of green; `make pipeline` runs the real models;
  `make dmg` ships. Remote is `github.com/martfo/polenta-meeting-notes` over gh HTTPS (the SSH
  key is not authorised).
