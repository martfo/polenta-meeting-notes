# Build the app and its installer. Signing needs the one-off local
# certificate from scripts/make_signing_cert.sh (or SKIP_SIGNING=1).

.PHONY: app-bundle dmg

app-bundle:
	bash scripts/build_app.sh

dmg: app-bundle
	bash scripts/build_dmg.sh
