#!/usr/bin/env bash
# install-recovera-agent.sh — enroll a Linux host's Datto Linux Agent (dlad)
# with an offline Recovera appliance.
#
# Run as root on the Linux machine you want to protect. It installs the stock
# dlad if absent, turns off dlad's cloud trust-update (so it stops reverting the
# offline CA and pinging mothership.dtc.datto.com), and installs the agent cert
# bundle minted by tools/offline-agent-pairing/make-dla-ca.sh.
#
# Usage:  sudo ./install-recovera-agent.sh <bundle_dir>
# <bundle_dir> must contain: ca.crt server.pem server.key cloud.thm
#   (the "agent/" directory produced by make-dla-ca.sh — the server cert there
#    must have CN = this agent's installation UUID).
#
# After this, provision the device side on Recovera and run `snapctl agent:add`.
# See docs/offline-agent-pairing.md.
set -euo pipefail

BUNDLE=${1:?usage: install-recovera-agent.sh <bundle_dir>}
CERTS=/etc/datto/dla/certs
CONF=/etc/datto/dla/config.json
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
for f in ca.crt server.pem server.key cloud.thm; do
  [ -s "$BUNDLE/$f" ] || { echo "missing $BUNDLE/$f" >&2; exit 1; }
done

if ! command -v dlad >/dev/null && [ ! -x /usr/sbin/dlad ]; then
  echo "dlad not installed — installing stock agent from cpkg.datto.com"
  curl -sS https://cpkg.datto.com/getLinuxAgent.sh -o /tmp/getLinuxAgent.sh
  bash /tmp/getLinuxAgent.sh
fi

echo "Backing up current agent state"
cp -a "$CERTS" "$CERTS.bak-$(date +%s)"
[ -f "$CONF" ] && cp -a "$CONF" "$CONF.bak-$(date +%s)"

echo "Disabling dlad cloud trust-update (certCheck) and checkin"
# dlad otherwise detects the swapped CA as 'superseded' and refetches from cloud.
sed -i 's/"certCheck.enabled": *true/"certCheck.enabled": false/; s/"checkin.enabled": *true/"checkin.enabled": false/' "$CONF"

echo "Installing offline cert bundle into $CERTS"
install -o root -g root -m 600 "$BUNDLE/ca.crt"     "$CERTS/ca.crt"
install -o root -g root -m 600 "$BUNDLE/server.pem" "$CERTS/server.pem"
install -o root -g root -m 600 "$BUNDLE/server.key" "$CERTS/server.key"
install -o root -g root -m 600 "$BUNDLE/cloud.thm"  "$CERTS/cloud.thm"

systemctl restart dlad
sleep 3
systemctl is-active --quiet dlad && echo "dlad active; agent ready for pairing." \
  || { echo "dlad failed to start — check journalctl -u dlad" >&2; exit 1; }
echo "Next: provision Recovera (recovera/provision-agent-pki.sh) and run 'snapctl agent:add $(hostname -I | awk '{print $1}')' there."
