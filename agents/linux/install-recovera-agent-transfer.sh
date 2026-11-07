#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
for file in recovera-agent-transfer recovera-agent-transfer.service; do
  [ -s "$SCRIPT_DIR/$file" ] || { echo "missing $SCRIPT_DIR/$file" >&2; exit 1; }
done
[ -s /etc/datto/dla/certs/server.pem ] || { echo "the protected-system agent is not installed" >&2; exit 1; }

install -m 0755 "$SCRIPT_DIR/recovera-agent-transfer" /usr/local/sbin/recovera-agent-transfer
install -m 0644 "$SCRIPT_DIR/recovera-agent-transfer.service" /etc/systemd/system/recovera-agent-transfer.service
systemctl daemon-reload
systemctl enable --now recovera-agent-transfer.service
systemctl is-active --quiet recovera-agent-transfer.service \
  && echo "recovera-agent-transfer active on TCP 25569." \
  || { echo "recovera-agent-transfer failed to start" >&2; exit 1; }
