#!/usr/bin/env bash
# make-dla-ca.sh — mint an OFFLINE Device-Agent (DLA) certificate authority and
# issue the leaf certs that let a Recovera appliance and a Datto Linux Agent
# (dlad) trust each other with no Datto cloud.
#
# Datto's cloud normally issues BOTH the device's `*device.pem` and the agent's
# `server.pem` from one CA, `CN=dla.ca.datto.com`; each side trusts that CA. An
# air-gapped Recovera has no cloud to issue them, so this script creates one
# local CA (same CN, a brand-new key — it impersonates nothing; it only has to
# be the single shared trust root for this one lab) and issues both leaves.
#
# The cert DN, extensions, and validity mirror a real SIRIS device cert
# (harvested from a working appliance) so the agent's unmodifiable, encoded
# verification code accepts them. See docs/offline-agent-pairing.md.
#
# Usage:
#   make-dla-ca.sh <out_dir> <recovera_device_id> <agent_uuid>
# Produces under <out_dir>:
#   ca/ca.crt ca/ca.key            — the shared CA (keep ca.key secret, offline)
#   recovera/<prefix>_dattoAgentCaCert.crt  (= ca.crt)
#   recovera/<prefix>_device.pem  recovera/<prefix>_device.key
#   agent/ca.crt agent/server.pem agent/server.key agent/cloud.thm
# and prints the CA SHA-1 thumbprint (what dlad stores in cloud.thm).
set -euo pipefail
# Stop Git Bash / MSYS from rewriting openssl "/CN=..." subjects into Windows
# paths when this is run on the workstation. No-op on Linux appliances.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

OUT=${1:?out_dir}; DEVICE_ID=${2:?recovera_device_id}; AGENT_UUID=${3:?agent_uuid}
CA_CN=${CA_CN:-dla.ca.datto.com}
DN_C=US; DN_ST=Conneticut; DN_L=Norwalk; DN_O=Datto; DN_OU="Device-Agent CA"   # NB: Datto's own typo "Conneticut"
CA_DAYS=${CA_DAYS:-3650}; LEAF_DAYS=${LEAF_DAYS:-1095}

mkdir -p "$OUT/ca" "$OUT/recovera" "$OUT/agent"
cd "$OUT"
umask 077

# The extensions file is written per-leaf (it carries the type metadata) inside
# the output dir and referenced relatively: native (Windows) OpenSSL cannot open
# an MSYS /tmp path but resolves cwd-relative paths fine. Harmless on Linux.
trap 'rm -f "$OUT/leaf.ext"' EXIT

# --- the shared CA (self-signed, CN=dla.ca.datto.com) ---------------------------
if [ ! -s ca/ca.key ]; then
  openssl genrsa -out ca/ca.key 4096 2>/dev/null
  openssl req -x509 -new -key ca/ca.key -sha256 -days "$CA_DAYS" -subj "/CN=$CA_CN" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "subjectKeyIdentifier=hash" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out ca/ca.crt
fi

# issue_leaf <cn> <out_basename_no_ext> <nstype:device|agent>
# dlad requires an nsComment of "type:device" on the device (client) cert and
# "type:agent" on the agent (server) cert ("required metadata"), and the real
# certs are signed with SHA-512 — match both.
issue_leaf() {
  local cn=$1 base=$2 nstype=$3
  cat > leaf.ext <<EOF
basicConstraints = CA:FALSE
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
keyUsage = digitalSignature, nonRepudiation, keyEncipherment
nsComment = "type:$nstype"
EOF
  openssl genrsa -out "$base.key" 4096 2>/dev/null
  openssl req -new -key "$base.key" -sha512 \
    -subj "/C=$DN_C/ST=$DN_ST/L=$DN_L/O=$DN_O/OU=$DN_OU/CN=$cn" -out "$base.csr" 2>/dev/null
  openssl x509 -req -in "$base.csr" -CA ca/ca.crt -CAkey ca/ca.key -CAcreateserial \
    -sha512 -days "$LEAF_DAYS" -extfile leaf.ext -out "$base.pem" 2>/dev/null
  rm -f "$base.csr"
}

PREFIX="$(date +%Y%m%d%H%M%S)_$(openssl rand -hex 16)"

# Recovera device identity (device = TLS client to the agent's :25567)
cp ca/ca.crt "recovera/${PREFIX}_dattoAgentCaCert.crt"
issue_leaf "$DEVICE_ID" "recovera/${PREFIX}_device" device

# Agent identity (agent = TLS server on :25567, and client to the device transport)
cp ca/ca.crt agent/ca.crt
issue_leaf "$AGENT_UUID" agent/server agent
openssl x509 -in ca/ca.crt -noout -fingerprint -sha1 | sed 's/.*=//; s/://g' | tr 'A-F' 'a-f' > agent/cloud.thm

echo "CA SHA-1 thumbprint (cloud.thm): $(cat agent/cloud.thm)"
echo "device cert prefix: $PREFIX"
echo "done -> $OUT"
