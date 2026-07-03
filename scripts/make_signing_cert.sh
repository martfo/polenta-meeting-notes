#!/bin/bash
# One-off, on the build machine only: create the local self-signed
# code-signing certificate the app is signed with. A stable identity keeps
# the microphone and system-audio permissions and the Keychain token working
# across rebuilds, instead of re-prompting each time.
#
# The app is not notarised, so Gatekeeper still needs a one-time right-click
# Open on each Mac.
set -euo pipefail

NAME="${1:-MeetingNotes Local Signing}"

if security find-identity -v -p codesigning | grep -q "$NAME"; then
  echo "The identity '$NAME' already exists. Nothing to do."
  exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/cert.conf" <<EOF
[ req ]
distinguished_name = dn
x509_extensions = codesign
prompt = no
[ dn ]
CN = $NAME
[ codesign ]
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
basicConstraints = critical,CA:false
EOF

openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
  -keyout "$WORK/key.pem" -out "$WORK/cert.pem" -config "$WORK/cert.conf"
openssl pkcs12 -export -inkey "$WORK/key.pem" -in "$WORK/cert.pem" \
  -name "$NAME" -out "$WORK/cert.p12" -passout pass:meetingnotes

security import "$WORK/cert.p12" -k "$HOME/Library/Keychains/login.keychain-db" \
  -P meetingnotes -T /usr/bin/codesign

echo
echo "Imported '$NAME' into the login keychain."
echo "One manual step remains: open Keychain Access, find '$NAME' under My"
echo "Certificates, open Get Info, expand Trust, and set Code Signing to"
echo "Always Trust. Then make dmg will sign with it."
