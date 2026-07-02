# Manual hardware checklist

These are the [manual-hardware] acceptance criteria. They can only be proven on
a real Mac with real permissions, so a person runs this list once per phase
gate and records the date and machine at the bottom.

## Phase 1

- [ ] AC-1.1-i: Start a recording for the first time. The system-audio capture
      prompt and the microphone prompt both appear. Play sound in a call and
      speak into the microphone; both input level meters move; after Stop, the
      saved audio contains both sides.
- [ ] AC-1.8-c: Press Reveal in Finder on a meeting. Finder opens at that
      meeting's folder inside the vault.

## Phase 3

- [ ] AC-3.1-e: On a Mac with no Python installed, first run provisions the
      backend into Application Support and the backend starts.
- [ ] AC-3.3-b: `codesign --verify --deep --strict` passes on the built app
      bundle and its embedded binaries.
- [ ] AC-3.3-c: Rebuild the app with the same local certificate and reinstall.
      The microphone and system-audio permissions and the Keychain token are
      still in place, with no re-prompt.
- [ ] AC-3.4-c: On a Mac that has not seen the app, mount the .dmg, drag the
      app to Applications, right-click Open once, and the app launches.
- [ ] AC-3.5-b: Full new-Mac flow in order: install LM Studio, load a model,
      install the app from the .dmg, right-click Open, pick a vault, let the
      models download, record or import a test meeting, and see it process to
      a summary.

## Record of runs

| Date | Machine | Phase | Result | Notes |
|------|---------|-------|--------|-------|
