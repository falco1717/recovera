#!/bin/bash
# datto-cow-reserve-fix — cap dattobd COW auto-expand reserved space.
#
# WHY: the Datto Linux Agent (dlad) configures the dattobd snapshot driver to
# refuse COW auto-expansion unless a large amount of free space remains on the
# protected volume (observed ~15% of volume size, e.g. 74.8 GiB on a 491 GB
# root). On a volume that is more than half full, free space dips below that
# floor during a long first/diff-merge backup, the very next auto-expand is
# rejected, the COW file overflows (-EFBIG), and the snapshot device returns
# EIO -> "VOLUME_READ_FAILED" and the backup fails. dlad recomputes and reapplies
# this reserved value on every new snapshot, so the fix must run continuously.
#
# WHAT: watch /proc/datto-info; whenever a live snapshot has reserved_space_mib
# above THRESH_MIB, call dbdctl reconfigure-auto-expand to cap it to RESERVE_MIB
# with STEP_MIB. This keeps a sane free-space floor (RESERVE_MIB) while letting
# the COW grow as needed for the backup. Reversible: it only tunes live snapshots;
# stop the service and dlad's own defaults apply again.
set -u
RESERVE_MIB=${RESERVE_MIB:-30720}   # keep this much free on the volume (30 GiB)
STEP_MIB=${STEP_MIB:-10240}         # grow the COW in 10 GiB steps
THRESH_MIB=${THRESH_MIB:-40960}     # only act when dlad set reserve above 40 GiB
INTERVAL=${INTERVAL:-5}
DBDCTL=${DBDCTL:-/usr/bin/dbdctl}
log(){ echo "$(date -Is) datto-cow-reserve-fix: $*"; }

log "started (reserve=${RESERVE_MIB}MiB step=${STEP_MIB}MiB thresh=${THRESH_MIB}MiB)"
while true; do
  if [ -r /proc/datto-info ]; then
    # Emit "<minor> <reserved_space_mib>" per active device.
    while read -r minor reserved; do
      [ -z "${minor:-}" ] && continue
      if [ "$reserved" -gt "$THRESH_MIB" ] 2>/dev/null; then
        log "minor $minor reserved=${reserved}MiB > ${THRESH_MIB}; capping to ${RESERVE_MIB}MiB"
        if "$DBDCTL" reconfigure-auto-expand -r "$RESERVE_MIB" "$STEP_MIB" "$minor"; then
          log "minor $minor reconfigured ok"
        else
          log "minor $minor reconfigure FAILED (rc=$?)"
        fi
      fi
    done < <(python3 -I -c '
import json,sys
try:
    d=json.load(open("/proc/datto-info"))
except Exception:
    sys.exit(0)
for dev in d.get("devices",[]):
    ae=dev.get("auto_expand") or {}
    r=ae.get("reserved_space_mib")
    m=dev.get("minor")
    if r is not None and m is not None:
        print(m, r)
')
  fi
  sleep "$INTERVAL"
done
