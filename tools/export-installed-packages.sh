#!/usr/bin/env bash
# Export every installed package at its exact version for an offline bundle.
# Run on the validated reference appliance as root.
set -euo pipefail

OUT=${1:-/var/tmp/pkgexport-recovera}
shift || true
EXTRA_DIRS=("$@")
DEBS="$OUT/debs"
LISTS="$OUT/lists"
CONFFILES="$OUT/conffiles"
WORK=$(mktemp -d /var/tmp/recovera-export.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
EXCLUDE_FILE=${RECOVERA_EXPORT_EXCLUDE_FILE:-}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
for command in apt-get dpkg-deb dpkg-query sha256sum python3; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

# Keep already downloaded .debs when resuming after an unavailable local
# package is supplied. Inventory and configuration metadata are regenerated.
mkdir -p "$DEBS"
rm -rf -- "$LISTS" "$CONFFILES"
mkdir -p "$LISTS" "$CONFFILES/files"
chmod 0755 "$OUT" "$DEBS"

dpkg-query -W -f='${db:Status-Abbrev}\t${binary:Package}\t${Version}\n' |
  awk -F '\t' '$1 ~ /^ii/ {print $2 "=" $3}' | sort -u > "$WORK/installed.txt"
declare -A excluded
if [ -n "$EXCLUDE_FILE" ] && [ -f "$EXCLUDE_FILE" ]; then
  while IFS= read -r package; do
    package=${package%%#*}
    package=${package//[[:space:]]/}
    [ -n "$package" ] && excluded["$package"]=1
  done < "$EXCLUDE_FILE"
fi
: > "$LISTS/all-packages-versions.txt"
while IFS= read -r requirement; do
  package=${requirement%%=*}
  base=${package%%:*}
  [ -n "${excluded[$base]:-}" ] || printf '%s\n' "$requirement" >> "$LISTS/all-packages-versions.txt"
done < "$WORK/installed.txt"
apt-mark showmanual | sort -u > "$LISTS/manual.txt"
cut -d= -f1 "$LISTS/all-packages-versions.txt" | sed 's/:.*$//' | sort -u > "$LISTS/portable.txt"
: > "$LISTS/local-debs.txt"
: > "$LISTS/repacked.txt"
: > "$LISTS/unavailable.txt"

# Prefer exact packages already retained by the appliance or supplied as
# reviewed overrides. The latter is where sanitized application/control-plane
# packages must be placed.
SOURCE_DIRS=("$DEBS" /opt/recovera/debs /var/cache/apt/archives "${EXTRA_DIRS[@]}")
declare -A local_deb
for directory in "${SOURCE_DIRS[@]}"; do
  [ -d "$directory" ] || continue
  while IFS= read -r -d '' deb; do
    package=$(dpkg-deb -f "$deb" Package 2>/dev/null || true)
    version=$(dpkg-deb -f "$deb" Version 2>/dev/null || true)
    [ -n "$package" ] && [ -n "$version" ] || continue
    local_deb["$package=$version"]=$deb
  done < <(find "$directory" -maxdepth 1 -type f -name '*.deb' -print0)
done

: > "$WORK/missing.txt"
while IFS= read -r requirement; do
  package=${requirement%%=*}
  base=${package%%:*}
  version=${requirement#*=}
  source=${local_deb["$base=$version"]:-}
  if [ -n "$source" ]; then
    destination="$DEBS/$(basename "$source")"
    if [ "$(readlink -f "$source")" != "$(readlink -f "$destination")" ]; then
      cp -a "$source" "$DEBS/"
    fi
    printf '%s\n' "$base" >> "$LISTS/local-debs.txt"
  else
    printf '%s\n' "$requirement" >> "$WORK/missing.txt"
  fi
done < "$LISTS/all-packages-versions.txt"

download_batch() {
  local -a batch=("$@")
  [ "${#batch[@]}" -gt 0 ] || return 0
  (cd "$DEBS" && apt-get download "${batch[@]}") && return 0
  if [ "${#batch[@]}" -eq 1 ]; then
    printf '%s\n' "${batch[0]}" >> "$LISTS/unavailable.txt"
    return 0
  fi
  # Bisect failed batches instead of retrying every member individually. A
  # single unavailable local package should not serialize dozens of downloads.
  local midpoint=$(( ${#batch[@]} / 2 ))
  download_batch "${batch[@]:0:midpoint}"
  download_batch "${batch[@]:midpoint}"
}

batch=()
while IFS= read -r requirement; do
  [ -n "$requirement" ] || continue
  if ! apt-cache show "$requirement" >/dev/null 2>&1; then
    printf '%s\n' "$requirement" >> "$LISTS/unavailable.txt"
    continue
  fi
  batch+=("$requirement")
  if [ "${#batch[@]}" -ge 80 ]; then
    download_batch "${batch[@]}"
    batch=()
  fi
done < "$WORK/missing.txt"
download_batch "${batch[@]}"

sort -u -o "$LISTS/unavailable.txt" "$LISTS/unavailable.txt"
if [ -s "$LISTS/unavailable.txt" ]; then
  echo "packages unavailable from configured repositories:" >&2
  cat "$LISTS/unavailable.txt" >&2
  exit 1
fi

# Build an exact package/version index from the result and fail if the export is
# incomplete. This also rejects accidental zero-byte or non-Debian downloads.
: > "$WORK/exported.txt"
while IFS= read -r -d '' deb; do
  package=$(dpkg-deb -f "$deb" Package)
  version=$(dpkg-deb -f "$deb" Version)
  printf '%s=%s\n' "$package" "$version" >> "$WORK/exported.txt"
done < <(find "$DEBS" -maxdepth 1 -type f -name '*.deb' -print0)
sort -u -o "$WORK/exported.txt" "$WORK/exported.txt"
sed 's/:.*=/_ARCH_=/' "$LISTS/all-packages-versions.txt" |
  sed 's/_ARCH_=/=/' | sort -u > "$WORK/required-base.txt"
comm -23 "$WORK/required-base.txt" "$WORK/exported.txt" > "$WORK/unresolved.txt"
if [ -s "$WORK/unresolved.txt" ]; then
  echo "exact packages missing after export:" >&2
  cat "$WORK/unresolved.txt" >&2
  exit 1
fi

sort -u -o "$LISTS/local-debs.txt" "$LISTS/local-debs.txt"

# Export current dpkg conffiles without credentials outside the declared
# conffile set. make-bundle.sh applies its stricter identity/telemetry denylist
# and repacks this archive with root ownership.
python3 - "$CONFFILES" <<'PY'
import hashlib
import os
import pathlib
import shutil
import sys

out = pathlib.Path(sys.argv[1])
root = out / "files"
status = pathlib.Path("/var/lib/dpkg/status").read_text(encoding="utf-8", errors="replace")
manifest = []
for paragraph in status.split("\n\n"):
    fields = {}
    current = None
    for line in paragraph.splitlines():
        if line.startswith((" ", "\t")) and current:
            fields[current] += "\n" + line
            continue
        if ":" in line:
            current, value = line.split(":", 1)
            fields[current] = value.lstrip()
    if not fields.get("Status", "").startswith("install ok installed"):
        continue
    package = fields.get("Package", "")
    for line in fields.get("Conffiles", "").splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("/"):
            continue
        source = pathlib.Path(parts[0])
        if not source.is_file() or source.is_symlink():
            continue
        destination = root / source.relative_to("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        digest = hashlib.md5(source.read_bytes()).hexdigest()
        manifest.append((digest, str(source), package))

with (out / "manifest.tsv").open("w", encoding="utf-8") as handle:
    for row in sorted(set(manifest), key=lambda item: item[1]):
        handle.write("\t".join(row) + "\n")
PY

(cd "$CONFFILES/files" && tar --owner=0 --group=0 --numeric-owner -czf ../conffiles.tgz .)
rm -rf -- "$CONFFILES/files"
(cd "$DEBS" && find . -maxdepth 1 -type f -name '*.deb' -printf '%f\n' | sort | xargs sha256sum > SHA256SUMS)

echo "exported $(find "$DEBS" -maxdepth 1 -type f -name '*.deb' | wc -l) packages"
echo "package inventory: $(wc -l < "$LISTS/all-packages-versions.txt")"
echo "configuration files: $(wc -l < "$CONFFILES/manifest.tsv")"
echo "output: $OUT"
