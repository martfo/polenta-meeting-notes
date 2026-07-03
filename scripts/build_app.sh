#!/bin/bash
# Builds dist/MeetingNotes.app from the SwiftPM package and signs it with the
# local self-signed certificate (see scripts/make_signing_cert.sh, a one-off
# per build machine). The bundle carries everything provisioning needs on a
# new Mac: the backend source, a uv binary, and the bundled language
# resources. Model weights are never bundled.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT/dist/Polenta Meeting Notes.app"
IDENTITY="${SIGNING_IDENTITY:-MeetingNotes Local Signing}"

echo "==> building the Swift app (release)"
cd "$ROOT/app"
swift build -c release
BIN="$(swift build -c release --show-bin-path)"

echo "==> assembling ${APP_DIR}"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$BIN/MeetingNotesApp" "$APP_DIR/Contents/MacOS/MeetingNotesApp"
if [ -d "$BIN/MeetingNotes_MeetingNotesApp.bundle" ]; then
  cp -R "$BIN/MeetingNotes_MeetingNotesApp.bundle" "$APP_DIR/Contents/Resources/"
fi
cp "$ROOT/app/Support/Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$ROOT/app/Support/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"

echo "==> bundling resources"
RES="$APP_DIR/Contents/Resources"
mkdir -p "$RES/language"
cp "$ROOT/backend/meetingnotes/resources/american_to_british.json" "$RES/language/"
cp "$ROOT/backend/meetingnotes/resources/NOTICE-VarCon.txt" "$RES/language/"
cp "$ROOT/backend/meetingnotes/resources/technical_allowlist.txt" "$RES/language/"
cp "$ROOT/backend/meetingnotes/resources/summary_prompt.md" "$RES/"
cp -R "$ROOT/backend/meetingnotes/resources/dict" "$RES/language/dict"

echo "==> bundling the backend for first-run provisioning"
mkdir -p "$RES/backend"
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'tests' \
  "$ROOT/backend/pyproject.toml" "$ROOT/backend/meetingnotes" "$RES/backend/"
if command -v uv >/dev/null 2>&1; then
  cp "$(command -v uv)" "$RES/uv"
else
  echo "warning: uv not found on the build machine; first-run provisioning needs it" >&2
fi

if [ "${SKIP_SIGNING:-0}" = "1" ]; then
  echo "==> SKIP_SIGNING=1, leaving the bundle unsigned"
  exit 0
fi

if ! security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
  echo "error: signing identity '$IDENTITY' not found." >&2
  echo "Create it once with scripts/make_signing_cert.sh, or set SKIP_SIGNING=1." >&2
  exit 1
fi

echo "==> signing inside out with '$IDENTITY'"
# Every embedded Mach-O first, then the bundle itself with the entitlements.
find "$APP_DIR/Contents/Resources" -type f \( -name 'uv' -o -name '*.dylib' -o -name '*.so' \) -print0 |
  while IFS= read -r -d '' binary; do
    codesign --force --sign "$IDENTITY" "$binary"
  done
codesign --force --sign "$IDENTITY" \
  --entitlements "$ROOT/app/Support/MeetingNotes.entitlements" \
  "$APP_DIR"
codesign --verify --strict "$APP_DIR"
echo "==> built and signed $APP_DIR"
