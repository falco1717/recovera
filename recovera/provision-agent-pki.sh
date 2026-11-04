#!/usr/bin/env bash
# provision-agent-pki.sh — install an offline device-agent cert set on a
# Recovera appliance so it can pair a Datto Linux Agent with no Datto cloud.
#
# Run as root on the Recovera appliance. Takes the "recovera/" bundle minted by
# tools/offline-agent-pairing/make-dla-ca.sh and installs it into
# /datto/config/certs with the modes the (encoded) SIRIS cert loader expects.
#
# Usage:  sudo ./provision-agent-pki.sh <bundle_dir> [device_id]
#   <bundle_dir> contains: <prefix>_dattoAgentCaCert.crt, <prefix>_device.pem,
#                          <prefix>_device.key
#   [device_id]  optional: also write it to /datto/config/deviceID (must equal
#                the agent-derived deviceID AND the device cert CN — see
#                docs/offline-agent-pairing.md for how to discover it).
set -euo pipefail

BUNDLE=${1:?usage: provision-agent-pki.sh <bundle_dir> [device_id]}
DEVICE_ID=${2:-}
CERTS=/datto/config/certs
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
getent group ssl-cert >/dev/null || { echo "ssl-cert group missing" >&2; exit 1; }

ca=$(ls "$BUNDLE"/*_dattoAgentCaCert.crt 2>/dev/null | head -1)
dev=$(ls "$BUNDLE"/*_device.pem 2>/dev/null | head -1)
key=$(ls "$BUNDLE"/*_device.key 2>/dev/null | head -1)
[ -s "$ca" ] && [ -s "$dev" ] && [ -s "$key" ] || { echo "bundle must contain *_dattoAgentCaCert.crt, *_device.pem, *_device.key" >&2; exit 1; }

echo "Backing up $CERTS"
cp -a "$CERTS" "$CERTS.bak-$(date +%s)"
# clear any previous offline set (timestamp-prefixed), keep the shipped shadowsnap CA
rm -f "$CERTS"/2[0-9][0-9][0-9]*_device.pem "$CERTS"/2[0-9][0-9][0-9]*_device.key "$CERTS"/2[0-9][0-9][0-9]*_dattoAgentCaCert.crt

install -o root -g root     -m 644 "$ca"  "$CERTS/$(basename "$ca")"
install -o root -g root     -m 644 "$dev" "$CERTS/$(basename "$dev")"
install -o root -g ssl-cert -m 640 "$key" "$CERTS/$(basename "$key")"
echo "Installed device cert set into $CERTS"

if [ -n "$DEVICE_ID" ]; then
  cp -a /datto/config/deviceID "/datto/config/deviceID.bak-$(date +%s)" 2>/dev/null || true
  printf '%s' "$DEVICE_ID" > /datto/config/deviceID
  echo "Set /datto/config/deviceID = $DEVICE_ID"
fi
echo "Next: snapctl agent:add <agentIP> --offsiteTarget noOffsite"
