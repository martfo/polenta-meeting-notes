#!/bin/bash
# Stages and builds the drag-to-install disk image: the app, a symbolic link
# to /Applications, and a short read-me with the right-click Open step. The
# dmg carries the app and its bundled resources only; the transcription and
# diarisation model weights and LM Studio are never inside.
#
# Usage:
#   build_dmg.sh [--stage-only] [app-path] [staging-dir]
# Defaults: dist/MeetingNotes.app and dist/dmg-staging, dmg at
# dist/MeetingNotes.dmg. --stage-only lets the tests assert the layout
# without hdiutil.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE_ONLY=0
if [ "${1:-}" = "--stage-only" ]; then
  STAGE_ONLY=1
  shift
fi
APP_PATH="${1:-$ROOT/dist/Polenta Meeting Notes.app}"
STAGING="${2:-$ROOT/dist/dmg-staging}"
DMG="$ROOT/dist/PolentaMeetingNotes.dmg"

if [ ! -d "$APP_PATH" ]; then
  echo "error: no app bundle at $APP_PATH (run make app-bundle first)" >&2
  exit 1
fi

echo "==> staging $STAGING"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP_PATH" "$STAGING/Polenta Meeting Notes.app"
ln -s /Applications "$STAGING/Applications"
cat > "$STAGING/Read me first.txt" <<'EOF'
Installing Polenta Meeting Notes

1. Drag Polenta Meeting Notes.app onto the Applications folder alongside it.
2. The first time only: right-click (or Control-click) the app in
   Applications and choose Open, then Open again in the dialogue. This is
   needed because the app is signed locally rather than notarised.
3. On first launch the app walks you through choosing a vault, storing your
   Hugging Face token, fetching its backend, and downloading the speech
   models. It needs the network for that first run only.

You also need LM Studio installed and running with a model loaded on port
1234 for summaries and chat. See the README in the repository for the full
new-Mac steps.
EOF

if [ "$STAGE_ONLY" = "1" ]; then
  echo "==> staged only (no dmg)"
  exit 0
fi

echo "==> building $DMG"
rm -f "$DMG"
hdiutil create -volname "Polenta Meeting Notes" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
echo "==> built $DMG"
