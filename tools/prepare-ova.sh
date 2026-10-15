#!/bin/bash
# Sanitize a fresh, unregistered Recovera build and arm clone-safe first boot.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo 'run with sudo' >&2; exit 1; }
SOURCE="$(cd "$(dirname "$0")" && pwd)/recovera-ova-firstboot"
[ -f "$SOURCE" ] || { echo "missing $SOURCE" >&2; exit 1; }
# Do not let this process itself pin the ZFS-backed /home mount. The caller
# should also invoke this script after `cd /` so its waiting login shell is not
# holding the dataset busy.
cd /
command -v recovera-peer >/dev/null
command -v recovera-backup-admin >/dev/null
zpool list -H homePool >/dev/null

compact_data_pool() {
  local unexpected snapshots pool_dev root_disk data_disk

  # An OVA must never inherit application data. Rebuild the otherwise-empty
  # data pool so VMware exports a fresh sparse disk rather than every block
  # written during package installation and validation.
  unexpected=$(zfs list -H -o name -r homePool | awk '
    $0 != "homePool" &&
    $0 != "homePool/.recv" &&
    $0 != "homePool/os" &&
    $0 != "homePool/transfer" &&
    $0 != "homePool/home" &&
    $0 != "homePool/home/agents" &&
    $0 != "homePool/home/configBackup" { print }
  ')
  [ -z "$unexpected" ] || {
    echo "refusing OVA preparation: unexpected datasets exist:" >&2
    printf '%s\n' "$unexpected" >&2
    exit 1
  }
  snapshots=$(zfs list -H -t snapshot -o name -r homePool 2>/dev/null || true)
  [ -z "$snapshots" ] || {
    echo 'refusing OVA preparation: ZFS snapshots exist' >&2
    exit 1
  }

  mapfile -t pool_devices < <(
    zpool status -P -L homePool |
      awk '$1 ~ "^/dev/" && $1 !~ "-(part[0-9]+|[0-9]+)$" { print $1 }'
  )
  # Some stable by-id/by-path names end in a digit, so fall back to every
  # absolute leaf when the conservative filter did not find one.
  if [ "${#pool_devices[@]}" -eq 0 ]; then
    mapfile -t pool_devices < <(zpool status -P -L homePool | awk '$1 ~ "^/dev/" { print $1 }')
  fi
  [ "${#pool_devices[@]}" -eq 1 ] || {
    echo 'refusing OVA preparation: homePool must contain exactly one data disk' >&2
    exit 1
  }
  pool_dev=$(readlink -f "${pool_devices[0]}")
  [ -b "$pool_dev" ] || { echo "invalid homePool device: $pool_dev" >&2; exit 1; }
  root_disk=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" | head -1)
  data_disk=$(lsblk -no PKNAME "$pool_dev" | head -1)
  [ -n "$data_disk" ] || data_disk=$(basename "$pool_dev")
  [ "$data_disk" != "$root_disk" ] || {
    echo 'refusing OVA preparation: homePool resolves to the system disk' >&2
    exit 1
  }

  zpool destroy -f homePool
  # With the pool gone, /home exposes the root filesystem directory that was
  # hidden by the dataset. It may contain files left by the original cloud
  # image, so clean it before recreating the empty template pool.
  find /home -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  wipefs -a "$pool_dev" >/dev/null
  if ! blkdiscard -f "$pool_dev" 2>/dev/null; then
    # A small zeroed prefix removes old labels when the virtual controller does
    # not advertise discard. The new pool only writes a small amount of fresh
    # metadata, keeping its stream-optimized VMDK sparse.
    dd if=/dev/zero of="$pool_dev" bs=4M count=16 conv=fsync status=none
  fi

  zpool create -o ashift=12 -O compression=on -O mountpoint=/homePool \
    homePool "$pool_dev"
  zfs create homePool/.recv
  zfs create homePool/os
  zfs create -o mountpoint=/datto/transfer homePool/transfer
  zfs create -o mountpoint=/home homePool/home
  zfs create homePool/home/agents
  zfs create homePool/home/configBackup
  zpool set autotrim=on homePool 2>/dev/null || true
  sync
  zpool trim -w homePool >/dev/null 2>&1 || true
}

compact_root_disk() {
  local zero_file=/.recovera-ova-zero

  rm -f "$zero_file"
  rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb
  rm -rf /root/.cache/*
  # libguestfs and metalibvirt leave large, reproducible build caches behind.
  # Runtime libraries and executables are installed outside these paths.
  rm -rf /var/tmp/.guestfs-* /etc/metalibvirt/build
  find /var/tmp -mindepth 1 -maxdepth 1 -mtime +0 -exec rm -rf -- {} +
  journalctl --rotate >/dev/null 2>&1 || true
  journalctl --vacuum-time=1s >/dev/null 2>&1 || true
  find /var/log -type f -exec truncate -s 0 {} +

  # Stream-optimized VMDKs compress zero grains extremely well. Filling and
  # removing one file also converts stale filesystem blocks into zeros when
  # the backing datastore does not propagate guest discard reliably.
  set +e
  dd if=/dev/zero of="$zero_file" bs=16M status=none
  set -e
  sync
  rm -f "$zero_file"
  sync
  fstrim -av >/dev/null 2>&1 || true
}

compact_installer_payload() {
  local deb_dir=/opt/spf-datto/debs version baseline saved

  # A deployed OVA does not need the 1.3 GB offline bootstrap repository. Keep
  # only the installed Recovera control-plane package as its signed-updater
  # rollback baseline, and rebuild the tiny local-repository metadata around it.
  version=$(dpkg-query -W -f='${Version}' recovera-appliance 2>/dev/null) || {
    echo 'refusing OVA preparation: recovera-appliance is not installed' >&2
    exit 1
  }
  baseline="$deb_dir/recovera-appliance_${version}_all.deb"
  [ -f "$baseline" ] || {
    echo "refusing OVA preparation: rollback baseline is missing: $baseline" >&2
    exit 1
  }
  command -v dpkg-scanpackages >/dev/null || {
    echo 'refusing OVA preparation: dpkg-scanpackages is unavailable' >&2
    exit 1
  }
  saved=$(mktemp)
  cp "$baseline" "$saved"
  rm -rf "$deb_dir"
  install -d -m 0755 "$deb_dir"
  install -m 0644 "$saved" "$baseline"
  rm -f "$saved"
  (
    cd "$deb_dir"
    sha256sum "$(basename "$baseline")" > SHA256SUMS
    dpkg-scanpackages . /dev/null > Packages
    gzip -9c Packages > Packages.gz
    touch .verified
  )
}

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
rm -f /var/lib/recovera-ova/first-boot-complete
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
registered_admin=""
if [ -s /datto/config/local/webaccess ]; then
  registered_admin=$(head -n 1 /datto/config/local/webaccess | cut -d: -f1)
  case "$registered_admin" in
    ''|root|backup-admin|statususer|recovera-repl)
      echo "refusing OVA preparation: unsafe registered administrator name: $registered_admin" >&2
      exit 1
      ;;
  esac
  [[ "$registered_admin" =~ ^[a-z_][a-z0-9_-]*$ ]] || {
    echo "refusing OVA preparation: invalid registered administrator name" >&2
    exit 1
  }
  if id "$registered_admin" >/dev/null 2>&1; then
    userdel -f -r "$registered_admin" >/dev/null 2>&1 || {
      echo "could not remove registered administrator: $registered_admin" >&2
      exit 1
    }
  fi
fi
if id backup-admin >/dev/null 2>&1; then
  userdel -f -r backup-admin >/dev/null 2>&1 || true
  if id backup-admin >/dev/null 2>&1; then
    echo 'could not remove backup-admin before OVA export' >&2
    exit 1
  fi
fi
rm -rf /etc/recovera /etc/recovera-peer /var/lib/recovera-peer
rm -f /datto/config/deviceID \
  /datto/config/local/offline-registration.pending.json \
  /datto/config/local/reg /datto/config/local/reg.error \
  /datto/config/local/webaccess
rm -f /var/lib/php/sessions/sess_*
rm -f /etc/apache2/ssl/www.key /etc/apache2/ssl/www.crt
rm -f /etc/ssh/ssh_host_* /etc/machine-id /var/lib/dbus/machine-id /etc/hostid
touch /etc/machine-id
rm -f /var/lib/NetworkManager/*.lease /var/lib/dhcp/*

# An exported appliance never retains the temporary OVA-builder login key.
find /home -path '*/.ssh/authorized_keys' -type f -delete
rm -f /root/.bash_history /home/*/.bash_history
apt-get clean
compact_installer_payload
compact_data_pool
compact_root_disk

# Keep the deployment network flexible and clone-safe.
if [ -f /etc/NetworkManager/system-connections/br0.nmconnection ]; then
  sed -Ei 's/^cloned-mac-address=.*/cloned-mac-address=stable/' \
    /etc/NetworkManager/system-connections/br0.nmconnection
  sed -Ei '/^address[0-9]*=/d; /^gateway[0-9]*=/d; /^dns=/d; s/^method=manual$/method=auto/' \
    /etc/NetworkManager/system-connections/br0.nmconnection
fi

sync
echo 'OVA preparation complete. Power off now; do not boot this builder before export.'
