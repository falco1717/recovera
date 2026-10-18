#!/usr/bin/env bash
# One-command installer for an existing Ubuntu 22.04 amd64 VM.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$ROOT/setup/release.env"

MODE=run
BUNDLE="${RECOVERA_BUNDLE:-}"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--bundle PATH] [--check]

Installs the complete Recovera appliance on an existing Ubuntu 22.04 amd64 VM.

  --bundle PATH  Use a previously downloaded recovera-setup.tar.
  --check        Validate the VM and simulate package installation only.
  -h, --help     Show this help.

Without --bundle, the installer uses a tar file beside this script or downloads
the pinned payload from the repository's private GitHub Release with an
authenticated GitHub CLI (`gh`). The payload is verified before extraction.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle)
      [ "$#" -ge 2 ] || die "--bundle needs a path"
      BUNDLE="$2"; shift 2 ;;
    --check) MODE=check; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v tar >/dev/null 2>&1 || die "tar is required"

resolve_path() {
  local path="$1" dir base
  dir="$(cd "$(dirname "$path")" 2>/dev/null && pwd)" || return 1
  base="$(basename "$path")"
  [ -f "$dir/$base" ] || return 1
  printf '%s/%s\n' "$dir" "$base"
}

download_payload() {
  command -v gh >/dev/null 2>&1 || die \
    "no local payload found and GitHub CLI is unavailable; use --bundle PATH"

  local owner cache
  owner="${SUDO_USER:-$(id -un)}"
  if [ "$owner" = root ]; then
    cache="${XDG_CACHE_HOME:-/root/.cache}/recovera"
    mkdir -p "$cache"
    gh release download "$BUNDLE_TAG" --repo "$BUNDLE_REPO" \
      --pattern "$BUNDLE_ASSET" --dir "$cache" --clobber
  else
    cache="$(getent passwd "$owner" | cut -d: -f6)/.cache/recovera"
    if [ "$(id -u)" -eq 0 ]; then
      install -d -o "$owner" -g "$(id -gn "$owner")" "$cache"
      sudo -H -u "$owner" gh release download "$BUNDLE_TAG" --repo "$BUNDLE_REPO" \
        --pattern "$BUNDLE_ASSET" --dir "$cache" --clobber
    else
      mkdir -p "$cache"
      gh release download "$BUNDLE_TAG" --repo "$BUNDLE_REPO" \
        --pattern "$BUNDLE_ASSET" --dir "$cache" --clobber
    fi
  fi
  printf '%s/%s\n' "$cache" "$BUNDLE_ASSET"
}

if [ -z "$BUNDLE" ]; then
  for candidate in \
    "$ROOT/$BUNDLE_ASSET" \
    "$ROOT/dist/$BUNDLE_ASSET"; do
    if [ -f "$candidate" ]; then BUNDLE="$candidate"; break; fi
  done
fi

if [ -z "$BUNDLE" ]; then
  BUNDLE="$(download_payload)"
fi
BUNDLE="$(resolve_path "$BUNDLE")" || die "payload not found: $BUNDLE"

actual_sha="$(sha256sum "$BUNDLE" | awk '{print $1}')"
[ "$actual_sha" = "$BUNDLE_SHA256" ] || die \
  "payload checksum mismatch (expected $BUNDLE_SHA256, got $actual_sha)"
echo "payload verified: $actual_sha"

if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || die "sudo is required"
  if [ "$MODE" = check ]; then
    exec sudo env RECOVERA_BUNDLE="$BUNDLE" "$ROOT/install.sh" --check
  fi
  exec sudo env RECOVERA_BUNDLE="$BUNDLE" "$ROOT/install.sh"
fi

. /etc/os-release
[ "${VERSION_ID:-}" = 22.04 ] || die "Ubuntu 22.04 is required (found ${PRETTY_NAME:-unknown})"
[ "$(dpkg --print-architecture)" = amd64 ] || die "amd64 is required"

work="$(mktemp -d /var/tmp/recovera-install.XXXXXX)"
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT

# Refuse absolute paths and parent traversal before extraction.
if tar -tf "$BUNDLE" | awk '
  /^\// { bad=1 }
  /(^|\/)\.\.($|\/)/ { bad=1 }
  END { exit bad ? 0 : 1 }
'; then
  die "payload contains an unsafe archive path"
fi

tar -xf "$BUNDLE" -C "$work"
mapfile -t payloads < <(find "$work" -mindepth 2 -maxdepth 2 -type f -name setup.sh -executable -printf '%h\n')
[ "${#payloads[@]}" -eq 1 ] || die "payload must contain exactly one top-level setup directory"
payload="${payloads[0]}"

# The checked-out branch owns installer behavior and local configuration; the
# release asset supplies the large immutable package/config payload.
install -m 0755 "$ROOT/setup/setup.sh" "$payload/setup.sh"
install -m 0755 "$ROOT/setup/migrate-layout.sh" "$payload/migrate-layout.sh"
install -m 0644 "$ROOT/setup/setup.conf" "$payload/setup.conf"
install -m 0644 "$ROOT/setup/README.txt" "$payload/README.txt"
rm -rf "$payload/wheels"
cp -a "$ROOT/setup/wheels" "$payload/wheels"
rm -rf "$payload/peer"
cp -a "$ROOT/setup/peer" "$payload/peer"
rm -rf "$payload/branding"
cp -a "$ROOT/setup/branding" "$payload/branding"
rm -rf "$payload/upgrade"
cp -a "$ROOT/upgrade" "$payload/upgrade"
rm -rf "$payload/isolation"
cp -a "$ROOT/setup/isolation" "$payload/isolation"

echo "starting Recovera setup on $(hostname) ..."
"$payload/setup.sh" "$MODE"
