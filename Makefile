# One entry point for the fast gate. It runs every [unit], [integration-fixture],
# and [contract-mock] test and is the single meaning of green.

.PHONY: gate gate-backend gate-app pipeline live-smoke dmg app-bundle

gate: gate-backend gate-app

gate-backend:
	cd backend && uv run pytest -q -m "not pipeline and not live_smoke"

# On a machine with only the Command Line Tools, Testing.framework lives in a
# directory SwiftPM does not search by default. With full Xcode installed the
# directory is absent and the flags collapse to nothing.
CLT_FRAMEWORKS := /Library/Developer/CommandLineTools/Library/Developer/Frameworks
SWIFT_TEST_FLAGS := $(shell test -d $(CLT_FRAMEWORKS) && echo "-Xswiftc -F -Xswiftc $(CLT_FRAMEWORKS) -Xswiftc -Xfrontend -Xswiftc -disable-cross-import-overlays -Xlinker -F -Xlinker $(CLT_FRAMEWORKS) -Xlinker -rpath -Xlinker $(CLT_FRAMEWORKS)")

gate-app:
	cd app && swift test $(SWIFT_TEST_FLAGS)

# Slow tier: the real WhisperX and pyannote pipeline against fixture audio.
# Run at phase boundaries. Needs the models present (uv sync --extra pipeline).
pipeline:
	cd backend && uv run pytest -q -m pipeline

# On-demand short runs against a real loaded model in LM Studio.
live-smoke:
	cd backend && uv run pytest -q -m live_smoke

app-bundle:
	bash scripts/build_app.sh

dmg: app-bundle
	bash scripts/build_dmg.sh
