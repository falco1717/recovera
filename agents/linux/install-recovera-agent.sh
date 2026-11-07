#!/usr/bin/env bash
# install-recovera-agent.sh — enroll a Linux host's Datto Linux Agent (dlad)
# with an offline Recovera appliance.
#
# Run as root on the Linux machine you want to protect. It installs the stock
# dlad if absent, turns off dlad's cloud trust-update (so it stops reverting the
# offline CA and pinging mothership.dtc.datto.com), installs the agent cert
# bundle minted by tools/offline-agent-pairing/make-dla-ca.sh, and installs the
# datto-cow-reserve-fix watcher (so backups of large/half-full volumes don't
# fail with a COW auto-expand overflow — see docs/offline-agent-pairing.md).
#
# Usage:  sudo ./install-recovera-agent.sh <bundle_dir>
# <bundle_dir> must contain: ca.crt server.pem server.key cloud.thm
#   (the "agent/" directory produced by make-dla-ca.sh — the server cert there
#    must have CN = this agent's installation UUID).
#
# Env:  SKIP_COW_FIX=1  skip installing the COW reserved-space watcher.
#
# After this, provision the device side on Recovera and run `snapctl agent:add`.
# See docs/offline-agent-pairing.md.
set -euo pipefail

BUNDLE=${1:?usage: install-recovera-agent.sh <bundle_dir>}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
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

TRANSFER_INSTALLER="$SCRIPT_DIR/install-recovera-agent-transfer.sh"
if [ -s "$TRANSFER_INSTALLER" ]; then
  echo "Installing Recovera agent ownership transfer service"
  bash "$TRANSFER_INSTALLER"
else
  echo "WARNING: Recovera transfer-service files were not found next to the installer; agent moves will require 'recovera-agent-transfer release' locally." >&2
fi

# --- COW reserved-space watcher -------------------------------------------
# dlad configures the dattobd snapshot driver to keep ~15% of the volume free
# before it will auto-expand the COW file. On a volume that is more than half
# full the COW cannot grow during a long first/diff-merge backup, overflows
# (-EFBIG), and the snapshot goes EIO -> VOLUME_READ_FAILED. This watcher caps
# that reserve to a sane floor on every live snapshot. See docs/.
COW_SH="$SCRIPT_DIR/datto-cow-reserve-fix.sh"
COW_SVC="$SCRIPT_DIR/datto-cow-reserve-fix.service"
if [ "${SKIP_COW_FIX:-0}" = 1 ]; then
  echo "Skipping COW reserved-space watcher (SKIP_COW_FIX=1)."
elif [ -s "$COW_SH" ] && [ -s "$COW_SVC" ]; then
  echo "Installing datto-cow-reserve-fix watcher"
  install -m 0755 "$COW_SH"  /usr/local/sbin/datto-cow-reserve-fix.sh
  install -m 0644 "$COW_SVC" /etc/systemd/system/datto-cow-reserve-fix.service
  systemctl daemon-reload
  systemctl enable --now datto-cow-reserve-fix.service
  systemctl is-active --quiet datto-cow-reserve-fix.service \
    && echo "datto-cow-reserve-fix active." \
    || echo "WARNING: datto-cow-reserve-fix did not start — check journalctl -u datto-cow-reserve-fix" >&2
else
  echo "WARNING: COW watcher files not found next to installer ($COW_SH); skipping." >&2
fi
# --------------------------------------------------------------------------

echo "Next: provision Recovera (recovera/provision-agent-pki.sh) and run 'snapctl agent:add $(hostname -I | awk '{print $1}')' there."
