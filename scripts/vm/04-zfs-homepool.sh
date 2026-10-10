#!/bin/bash
# Run ON the VM (as ubuntu, sudo) after attaching the 3 TB disk (scripts/vcenter/vc-add-disk.ps1).
# Builds homePool with spf-datto's settings and dataset layout, and moves /home onto it
# without breaking the SSH key in /home/ubuntu/.ssh.
set -euo pipefail

for h in /sys/class/scsi_host/host*/scan; do echo "- - -" | sudo tee "$h" >/dev/null; done; sleep 3
DEV=$(lsblk -dnbo NAME,SIZE,TYPE | awk '$3=="disk" && $2>3000000000000 {print $1}')
[ -n "$DEV" ] || { echo "3T disk not found"; exit 1; }
# Refuse anything that already has partitions or a filesystem
[ -z "$(lsblk -no FSTYPE /dev/$DEV | tr -d ' \n')" ] && [ "$(lsblk -no NAME /dev/$DEV | wc -l)" -eq 1 ] \
  || { echo "/dev/$DEV is not blank, stopping"; exit 1; }
ID=$(for l in /dev/disk/by-path/*; do [ "$(readlink -f "$l")" = "/dev/$DEV" ] && echo "$l"; done | head -1)
echo "using /dev/$DEV = $ID"

# spf-datto: ashift 12, compression on, pool mounted at /homePool
sudo zpool create -o ashift=12 -O compression=on -O mountpoint=/homePool homePool "$ID"
sudo zfs create homePool/.recv
sudo zfs create homePool/os
sudo zfs create -o mountpoint=/datto/transfer homePool/transfer

# Copy /home into the new dataset before mounting it over /home
sudo zfs create -o mountpoint=/mnt/newhome homePool/home
sudo rsync -aHAX /home/ /mnt/newhome/
sudo diff -r /home /mnt/newhome >/dev/null && echo "home copy verified"
sudo zfs set mountpoint=/home homePool/home
# The original /home stays underneath as a fallback; overlay lets zfs-mount mount over it
sudo zfs set overlay=on homePool/home
sudo zfs create homePool/home/agents
sudo zfs create homePool/home/configBackup
sudo rmdir /mnt/newhome 2>/dev/null || true

sudo zpool list -o name,size,ashift,health homePool
sudo zfs list -o name,used,avail,mountpoint,compression -r homePool
echo "test a NEW ssh login now, then reboot and check: systemctl is-active zfs-mount"
