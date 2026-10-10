#!/bin/bash
# Run ON the VM (as ubuntu, sudo). Removes the two cloud-image packages that spf-datto
# doesn't have and that form systemd ordering cycles with Datto's ZFS/network units.
# Those cycles made systemd drop sockets.target and systemd-tmpfiles-setup at boot,
# so /run/php was never created and php8.1-fpm failed.
set -euo pipefail

echo "cycles before: $(sudo systemd-analyze verify default.target 2>&1 | grep -ci cycle || true)"

sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get -y -q purge snapd
# snapd owns /usr/bin/snapctl. Datto had repointed it at its own snapctl, so the purge
# deleted Datto's link and every Datto boot service failed. Put it back like spf-datto.
sudo ln -sfn /datto/bin/snapctl /usr/bin/snapctl
snapctl --version | head -1

# Network config was already disabled in cloud-init (01-static-ip.sh); nothing else needs it.
sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get -y -q purge cloud-init

echo "cycles after: $(sudo systemd-analyze verify default.target 2>&1 | grep -ci cycle || true)"
echo "reboot, then check: journalctl -b | grep -c 'Found ordering cycle'  (expect 0)"
