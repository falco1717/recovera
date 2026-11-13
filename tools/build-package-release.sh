#!/bin/bash
# Build and optionally sign a small, offline-complete Recovera package release.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACKAGES=
VERSION=
SEQUENCE=
CHANNEL=
OS_VERSION=22.04
CHANNELS_DIR=$ROOT/upgrade/channels
OUTPUT=
SIGNING_KEY=
REBOOT_REQUIRED=false

usage() {
  echo "usage: $0 --packages DIR --version VERSION --sequence N --output DIR [--os-version 22.04|24.04] [--channel NAME] [--channels-dir DIR] [--signing-key FILE] [--reboot-required]" >&2
}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --packages) PACKAGES=$2; shift 2;;
    --version) VERSION=$2; shift 2;;
    --sequence) SEQUENCE=$2; shift 2;;
    --os-version) OS_VERSION=$2; shift 2;;
    --channels-dir) CHANNELS_DIR=$2; shift 2;;
    --channel) CHANNEL=$2; shift 2;;
    --output) OUTPUT=$2; shift 2;;
    --signing-key) SIGNING_KEY=$2; shift 2;;
    --reboot-required) REBOOT_REQUIRED=true; shift;;
    *) usage; exit 2;;
  esac
done
[ -d "$PACKAGES" ] && [ -n "$VERSION" ] && [[ "$SEQUENCE" =~ ^[1-9][0-9]*$ ]] && \
  [ -n "$OUTPUT" ] || { usage; exit 2; }
[ "$(readlink -f "$PACKAGES")" != "$(readlink -f "$OUTPUT")" ] || { echo "package input and output directories must differ" >&2; exit 2; }
[[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$ ]] || { echo "invalid version" >&2; exit 2; }
# Appliances on Ubuntu 22.04 read the historical channel names (stable); every
# other release reads "<codename>-<channel>" (see effective_channel in
# upgrade/recovera-upgrade). A release must be built for exactly one OS.
case "$OS_VERSION" in
  22.04) OS_PREFIX=;;
  24.04) OS_PREFIX=noble-;;
  *) echo "unsupported --os-version: $OS_VERSION" >&2; exit 2;;
esac
[ -n "$CHANNEL" ] || CHANNEL=${OS_PREFIX}stable
[[ "$CHANNEL" =~ ^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$ ]] || { echo "invalid channel" >&2; exit 2; }
if [ -n "$OS_PREFIX" ]; then
  [[ "$CHANNEL" == "$OS_PREFIX"* ]] || { echo "Ubuntu $OS_VERSION releases belong on a ${OS_PREFIX}* channel" >&2; exit 2; }
elif [[ "$CHANNEL" == noble-* ]]; then
  echo "Ubuntu 22.04 releases cannot use a noble-* channel" >&2; exit 2
fi
# One sequence counter across every channel, so an appliance that moves to its
# new OS release's channel never sees that channel's releases as older.
highest=0
# (--channels-dir points test fixtures at their own, empty, set of pointers.)
for pointer in "$CHANNELS_DIR"/*.json; do
  [ -e "$pointer" ] || continue
  value=$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("sequence") or 0))' "$pointer")
  [ "$value" -le "$highest" ] || highest=$value
done
[ "$SEQUENCE" -gt "$highest" ] || { echo "sequence $SEQUENCE must be greater than $highest, the highest sequence on any channel" >&2; exit 2; }
[ -z "$SIGNING_KEY" ] || [ -f "$SIGNING_KEY" ] || { echo "signing key not found: $SIGNING_KEY" >&2; exit 2; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

mapfile -d '' debs < <(find "$PACKAGES" -maxdepth 1 -type f -name '*.deb' -print0 | sort -z)
[ "${#debs[@]}" -gt 0 ] || { echo "no .deb packages found in $PACKAGES" >&2; exit 1; }
mkdir -p "$OUTPUT"
rm -f "$OUTPUT"/*.deb "$OUTPUT/recovera-package-manifest.json" "$OUTPUT/recovera-package-manifest.json.sig"
for deb in "${debs[@]}"; do cp -- "$deb" "$OUTPUT/"; done

manifest=$OUTPUT/recovera-package-manifest.json
python3 - "$VERSION" "$SEQUENCE" "$CHANNEL" "$REBOOT_REQUIRED" "$OUTPUT" "$OS_VERSION" > "$manifest" <<'PY'
import hashlib, json, pathlib, re, subprocess, sys

version, sequence, channel, reboot, output, os_version = sys.argv[1:]
forbidden = re.compile(
    r'^(?:linux-(?:image|headers|modules|tools)|grub|shim|initramfs-tools|'
    r'systemd|libc6|zfs(?:utils|initramfs|dkms|modules)?)(?:[-:].*)?$'
)

def field(path, name):
    return subprocess.check_output(['dpkg-deb', '-f', str(path), name], text=True).strip()

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

packages = []
seen = set()
for path in sorted(pathlib.Path(output).glob('*.deb')):
    name = field(path, 'Package')
    package_version = field(path, 'Version')
    architecture = field(path, 'Architecture')
    if forbidden.match(name):
        raise SystemExit(f'{name} is a platform package; ship it in a signed image release')
    if name in seen:
        raise SystemExit(f'duplicate package in release: {name}')
    if architecture not in ('all', 'amd64'):
        raise SystemExit(f'unsupported package architecture for {name}: {architecture}')
    seen.add(name)
    packages.append({
        'name': name, 'version': package_version, 'architecture': architecture,
        'asset': path.name, 'size': path.stat().st_size, 'sha256': digest(path),
    })

print(json.dumps({
    'schema': 2, 'type': 'package', 'version': version, 'sequence': int(sequence),
    'channel': channel, 'architecture': 'amd64', 'minimum_updater': 2,
    'os': {'id': 'ubuntu', 'version_id': os_version},
    'download_size': sum(item['size'] for item in packages),
    'reboot_required': reboot == 'true', 'packages': packages,
}, indent=2, sort_keys=True))
PY

if [ -n "$SIGNING_KEY" ]; then
  ssh-keygen -Y sign -q -f "$SIGNING_KEY" -n recovera-upgrade "$manifest"
  echo "signed Recovera $VERSION package release written to $OUTPUT"
else
  echo "unsigned Recovera $VERSION package release written to $OUTPUT"
  echo "sign $manifest on the isolated release workstation before publishing" >&2
fi
