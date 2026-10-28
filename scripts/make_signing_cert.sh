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

# find-certificate rather than find-identity -v: the latter only lists
# trusted identities, so it would miss a cert imported but not yet trusted
# and this script would import a duplicate.
if security find-certificate -c "$NAME" >/dev/null 2>&1; then
  echo "The certificate '$NAME' already exists in the keychain."
  echo "If codesigning still fails, set its Trust to Always Trust for Code"
  echo "Signing in Keychain Access."
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

# The key and certificate are imported as PEM, separately, on purpose. A
# PKCS12 bundle from OpenSSL 3 uses AES and SHA-256 defaults that the macOS
# Security framework cannot verify (security import fails with "MAC
# verification failed"), and the PEM path has no such format dependency.
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
security import "$WORK/key.pem" -k "$KEYCHAIN" -T /usr/bin/codesign
security import "$WORK/cert.pem" -k "$KEYCHAIN" -T /usr/bin/codesign

echo
echo "Imported '$NAME' into the login keychain."
echo "One manual step remains: open Keychain Access, find '$NAME' under My"
echo "Certificates, open Get Info, expand Trust, and set Code Signing to"
echo "Always Trust. Then make dmg will sign with it."
