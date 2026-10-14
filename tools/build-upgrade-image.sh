#!/bin/bash
# Build, split, and sign a bootable Recovera root image from a prepared root tree.
set -euo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

ROOT=
VERSION=
SEQUENCE=
CHANNEL=stable
OUTPUT=
SIGNING_KEY=
PART_SIZE=1900M

usage() {
  echo "usage: sudo $0 --root DIR --version VERSION --sequence N --output DIR --signing-key FILE [--channel NAME]" >&2
}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) ROOT=$2; shift 2;;
    --version) VERSION=$2; shift 2;;
    --sequence) SEQUENCE=$2; shift 2;;
    --channel) CHANNEL=$2; shift 2;;
    --output) OUTPUT=$2; shift 2;;
    --signing-key) SIGNING_KEY=$2; shift 2;;
    *) usage; exit 2;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -d "$ROOT" ] && [ -n "$VERSION" ] && [[ "$SEQUENCE" =~ ^[1-9][0-9]*$ ]] && \
  [ -n "$OUTPUT" ] && [ -f "$SIGNING_KEY" ] || { usage; exit 2; }
[[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$ ]] || { echo "invalid version" >&2; exit 2; }
for command in rsync mkfs.ext4 e2fsck resize2fs xz split ssh-keygen jq; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

mkdir -p "$OUTPUT"
work=$(mktemp -d /var/tmp/recovera-image-build.XXXXXX)
mountpoint=$work/root
image=$work/recovera-$VERSION.img
mounted=no
cleanup() {
  if [ "$mounted" != no ]; then
    for filesystem in sys proc dev; do umount -R "$mountpoint/$filesystem" 2>/dev/null || true; done
    umount "$mountpoint" 2>/dev/null || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT

used_kb=$(du -sx --block-size=1024 "$ROOT" | awk '{print $1}')
image_mb=$(( (used_kb * 13 / 10 + 1024*1024 - 1) / 1024 + 1024 ))
truncate -s "${image_mb}M" "$image"
mkfs.ext4 -q -F -L recovera-root "$image"
mkdir -p "$mountpoint"
mount -o loop "$image" "$mountpoint"
mounted=yes
rsync -aHAX --numeric-ids --one-file-system \
  --exclude=/dev --exclude=/proc --exclude=/sys --exclude=/run --exclude=/tmp \
  --exclude=/host --exclude=/mnt --exclude=/media --exclude=/var/tmp \
  "$ROOT"/ "$mountpoint"/

# A release image is generic. The receiving appliance injects its identity only
# after the signed base image has been verified. Never publish builder secrets.
rm -rf "$mountpoint/etc/recovera-peer" "$mountpoint/var/lib/recovera-peer" \
  "$mountpoint/etc/NetworkManager/system-connections"/*
rm -f "$mountpoint/etc/recovera/github-token" \
  "$mountpoint/etc/recovera/backup-admin.json" \
  "$mountpoint/etc/recovera/image-layout.json" \
  "$mountpoint/etc/apache2/ssl/www.key" "$mountpoint/etc/apache2/ssl/www.crt" \
  "$mountpoint/etc/ssh"/ssh_host_* "$mountpoint/datto/config/deviceID"
: > "$mountpoint/etc/machine-id"
printf 'recovera\n' > "$mountpoint/etc/hostname"
chroot "$mountpoint" passwd -l backup-admin >/dev/null 2>&1 || true
mkdir -p "$mountpoint"/{dev,proc,sys,run,tmp,host,mnt,media,var/tmp} \
  "$mountpoint/usr/local/lib/recovera-upgrade" \
  "$mountpoint/usr/local/share/recovera-upgrade" \
  "$mountpoint/etc/initramfs-tools/hooks" \
  "$mountpoint/etc/initramfs-tools/scripts/local-top" \
  "$mountpoint/etc/initramfs-tools/scripts/local-bottom" \
  "$mountpoint/etc/default/grub.d" "$mountpoint/etc/grub.d"
chmod 1777 "$mountpoint/tmp" "$mountpoint/var/tmp"

install -m 0755 "$REPO_ROOT/upgrade/recovera-upgrade" "$mountpoint/usr/local/sbin/recovera-upgrade"
install -m 0755 "$REPO_ROOT/upgrade/recovera-image-boot" "$mountpoint/usr/local/lib/recovera-upgrade/recovera-image-boot"
install -m 0755 "$REPO_ROOT/upgrade/recovera-migrate-config" "$mountpoint/usr/local/lib/recovera-upgrade/recovera-migrate-config"
install -m 0755 "$REPO_ROOT/upgrade/initramfs-hook-recovera" "$mountpoint/etc/initramfs-tools/hooks/recovera-image"
install -m 0755 "$REPO_ROOT/upgrade/initramfs-local-top-recovera" "$mountpoint/etc/initramfs-tools/scripts/local-top/recovera-image"
install -m 0755 "$REPO_ROOT/upgrade/initramfs-local-bottom-recovera" "$mountpoint/etc/initramfs-tools/scripts/local-bottom/recovera-image"
install -m 0755 "$REPO_ROOT/upgrade/07_recovera_images" "$mountpoint/etc/grub.d/07_recovera_images"
install -m 0644 "$REPO_ROOT/upgrade/99_recovera_images.cfg" "$mountpoint/etc/default/grub.d/99_recovera_images.cfg"
install -m 0644 "$REPO_ROOT/upgrade/keys/recovera-release-signers" "$mountpoint/usr/local/share/recovera-upgrade/release-signers"
install -m 0644 "$REPO_ROOT/upgrade/recovera-upgrade-validate.service" "$mountpoint/etc/systemd/system/recovera-upgrade-validate.service"
if [ ! -f "$mountpoint/etc/recovera/upgrade.conf" ]; then
  mkdir -p "$mountpoint/etc/recovera"
  install -m 0600 "$REPO_ROOT/upgrade/recovera-upgrade.conf" "$mountpoint/etc/recovera/upgrade.conf"
fi
jq -n --arg version "$VERSION" --argjson sequence "$SEQUENCE" \
  '{schema:1,version:$version,sequence:$sequence}' > "$mountpoint/etc/recovera-image-release"

for filesystem in dev proc sys; do mount --rbind "/$filesystem" "$mountpoint/$filesystem"; done
chroot "$mountpoint" update-initramfs -u -k all
chroot "$mountpoint" systemctl enable recovera-upgrade-validate.service >/dev/null
for filesystem in sys proc dev; do umount -R "$mountpoint/$filesystem"; done
[ -e "$mountpoint/boot/vmlinuz" ] && [ -e "$mountpoint/boot/initrd.img" ] || {
  echo "image has no /boot/vmlinuz and /boot/initrd.img symlinks" >&2; exit 1;
}
umount "$mountpoint"
mounted=no
e2fsck -fy "$image"
resize2fs -M "$image"
truncate -s "$(dumpe2fs -h "$image" 2>/dev/null | awk '/Block count:/{c=$3}/Block size:/{s=$3}END{print c*s}')" "$image"

compressed=$OUTPUT/recovera-$VERSION.img.xz
xz -T0 -9 -c "$image" > "$compressed"
rm -f "$OUTPUT"/recovera-$VERSION.img.xz.part-*
split -b "$PART_SIZE" -d -a 3 "$compressed" "$OUTPUT/recovera-$VERSION.img.xz.part-"

manifest=$OUTPUT/recovera-image-manifest.json
python3 - "$VERSION" "$SEQUENCE" "$CHANNEL" "$image" "$compressed" "$OUTPUT" > "$manifest" <<'PY'
import hashlib, json, pathlib, sys
version, sequence, channel, raw_name, compressed_name, output_name = sys.argv[1:]
def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()
raw = pathlib.Path(raw_name)
compressed = pathlib.Path(compressed_name)
parts = []
for part in sorted(pathlib.Path(output_name).glob(f'recovera-{version}.img.xz.part-*')):
    parts.append({'name': part.name, 'size': part.stat().st_size, 'sha256': digest(part)})
print(json.dumps({
    'schema': 1, 'version': version, 'sequence': int(sequence), 'channel': channel,
    'architecture': 'amd64', 'minimum_updater': 1,
    'image': {'compression': 'xz', 'size': compressed.stat().st_size,
              'sha256': digest(compressed), 'uncompressed_size': raw.stat().st_size,
              'uncompressed_sha256': digest(raw), 'parts': parts},
}, indent=2, sort_keys=True))
PY
rm -f "$manifest.sig"
ssh-keygen -Y sign -q -f "$SIGNING_KEY" -n recovera-upgrade "$manifest"
echo "signed Recovera $VERSION image assets written to $OUTPUT"
