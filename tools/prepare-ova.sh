#!/bin/bash
# Sanitize a fresh, unregistered Recovera build and arm clone-safe first boot.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo 'run with sudo' >&2; exit 1; }
SOURCE="$(cd "$(dirname "$0")" && pwd)/recovera-ova-firstboot"
[ -f "$SOURCE" ] || { echo "missing $SOURCE" >&2; exit 1; }
command -v recovera-peer >/dev/null
command -v recovera-backup-admin >/dev/null
zpool list -H homePool >/dev/null

# Refuse to publish an image containing protected systems, received replicas,
# pairing relationships, or an already registered local administrator.
if find /home/agents -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .; then
  echo 'refusing OVA preparation: protected-system data exists in /home/agents' >&2
  exit 1
fi
python3 - <<'PY'
import json
from pathlib import Path

config = Path('/etc/recovera-peer/config.json')
if config.is_file():
    value = json.loads(config.read_text())
    if value.get('peers') or value.get('sources') or value.get('assets'):
        raise SystemExit('refusing OVA preparation: peer relationships exist')
PY

systemctl stop recovera-peer.service recovera-peer-sync.timer apache2.service ssh.service || true
install -m 0755 "$SOURCE" /usr/local/sbin/recovera-ova-firstboot
cat > /etc/systemd/system/recovera-ova-firstboot.service <<'EOF'
[Unit]
Description=Initialize clone-specific Recovera appliance identity
DefaultDependencies=no
After=local-fs.target systemd-machine-id-commit.service
Before=network-pre.target NetworkManager.service ssh.service apache2.service recovera-peer.service
Wants=network-pre.target
ConditionPathExists=!/var/lib/recovera-ova/first-boot-complete

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/recovera-ova-firstboot
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable recovera-ova-firstboot.service >/dev/null
if systemd-analyze verify recovera-ova-firstboot.service 2>&1 | grep -qi 'ordering cycle'; then
  echo 'refusing OVA preparation: first-boot service has an ordering cycle' >&2
  exit 1
fi

# The temporary build login is not an appliance account. OVA deployments use
# the per-clone backup-admin account initialized on first boot.
builder_user="${SUDO_USER:-}"
if [ -z "$builder_user" ] || [ "$builder_user" = root ]; then
  builder_user=$(getent passwd 1000 | cut -d: -f1)
fi
if [ -n "$builder_user" ] && [ "$builder_user" != backup-admin ] && id "$builder_user" >/dev/null 2>&1; then
  userdel -f -r "$builder_user" >/dev/null 2>&1 || {
    echo "could not remove temporary builder account: $builder_user" >&2
    exit 1
  }
fi
sed -Ei 's/^LOGIN_USER=.*/LOGIN_USER="backup-admin"/' /opt/spf-datto/setup.conf

# Remove all clone-sensitive identities. First boot recreates them.
userdel -r backup-admin >/dev/null 2>&1 || true
rm -rf /etc/recovera /etc/recovera-peer /var/lib/recovera-peer
rm -f /datto/config/deviceID /datto/config/local/offline-registration.pending.json
rm -f /etc/apache2/ssl/www.key /etc/apache2/ssl/www.crt
rm -f /etc/ssh/ssh_host_* /etc/machine-id /var/lib/dbus/machine-id /etc/hostid
touch /etc/machine-id
rm -f /var/lib/NetworkManager/*.lease /var/lib/dhcp/*

# An exported appliance never retains the temporary OVA-builder login key.
find /home -path '*/.ssh/authorized_keys' -type f -delete
rm -f /root/.bash_history /home/*/.bash_history
journalctl --rotate >/dev/null 2>&1 || true
journalctl --vacuum-time=1s >/dev/null 2>&1 || true
find /var/log -type f -exec truncate -s 0 {} +
apt-get clean
fstrim -av >/dev/null 2>&1 || true
zpool trim -w homePool >/dev/null 2>&1 || true

# Keep the deployment network flexible and clone-safe.
if [ -f /etc/NetworkManager/system-connections/br0.nmconnection ]; then
  sed -Ei 's/^cloned-mac-address=.*/cloned-mac-address=stable/' \
    /etc/NetworkManager/system-connections/br0.nmconnection
  sed -Ei '/^address[0-9]*=/d; /^gateway[0-9]*=/d; /^dns=/d; s/^method=manual$/method=auto/' \
    /etc/NetworkManager/system-connections/br0.nmconnection
fi

sync
echo 'OVA preparation complete. Power off now; do not boot this builder before export.'
