#!/bin/bash
# Validate the shape and release-size ceiling of an exported Recovera OVA.
set -euo pipefail

OVA=${1:-}
MAX_BYTES=${RECOVERA_OVA_MAX_BYTES:-2000000000}

[ -n "$OVA" ] || { echo "usage: $0 /path/to/Recovera.ova" >&2; exit 2; }
[ -f "$OVA" ] || { echo "OVA not found: $OVA" >&2; exit 1; }
[[ "$MAX_BYTES" =~ ^[0-9]+$ ]] || { echo 'RECOVERA_OVA_MAX_BYTES must be an integer' >&2; exit 2; }

size=$(stat -c %s "$OVA")
[ "$size" -le "$MAX_BYTES" ] || {
  printf 'OVA is too large: %s bytes (maximum %s bytes)\n' "$size" "$MAX_BYTES" >&2
  exit 1
}

mapfile -t members < <(tar -tf "$OVA")
[ "${#members[@]}" -ge 3 ] || { echo 'OVA archive is incomplete' >&2; exit 1; }
for member in "${members[@]}"; do
  case "$member" in
    /*|../*|*/../*) echo "unsafe OVA member: $member" >&2; exit 1 ;;
    *.ovf|*.mf|*.vmdk) ;;
    *) echo "unexpected OVA member: $member" >&2; exit 1 ;;
  esac
done

ovf_members=()
vmdk_members=()
for member in "${members[@]}"; do
  case "$member" in
    *.ovf) ovf_members+=("$member") ;;
    *.vmdk) vmdk_members+=("$member") ;;
  esac
done
[ "${#ovf_members[@]}" -eq 1 ] || { echo 'OVA must contain exactly one OVF descriptor' >&2; exit 1; }
[ "${#vmdk_members[@]}" -eq 2 ] || { echo 'OVA must contain exactly two VMDKs' >&2; exit 1; }

ovf=$(tar -xOf "$OVA" "${ovf_members[0]}")
disk_rows=$(grep -o 'ovf:format="[^"]*"' <<<"$ovf" || true)
[ "$(grep -c streamOptimized <<<"$disk_rows")" -eq 2 ] || {
  echo 'both OVA disks must use VMware streamOptimized format' >&2
  exit 1
}

printf 'OVA validation passed: %s bytes (%.2f GiB, limit %.2f GiB)\n' \
  "$size" "$(awk -v n="$size" 'BEGIN { print n / 1073741824 }')" \
  "$(awk -v n="$MAX_BYTES" 'BEGIN { print n / 1073741824 }')"
