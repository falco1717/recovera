#!/usr/bin/env bash
# Destructive only to the fixed eeee... test asset and homePool/recovera-peer-e2e.
set -Eeuo pipefail

ASSET=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
FIRST=1791846000
SECOND=1791846060
SOURCE_ROOT=homePool/recovera-peer-e2e
TARGET_ROOT=homePool/home/agents
SCRIPT=${RECOVERA_PEER_SCRIPT:-/usr/local/sbin/recovera-peer}
WORK=$(mktemp -d /tmp/recovera-peer-e2e.XXXXXX)
SOURCE_ID=""

peer_env() {
  env \
    RECOVERA_PEER_ETC="$WORK/etc" \
    RECOVERA_PEER_STATE="$WORK/state" \
    RECOVERA_PEER_KEYS="$WORK/keys" \
    RECOVERA_PEER_LOCK="$WORK/lock" \
    RECOVERA_PEER_STATE_LOCK="$WORK/state.lock" \
    RECOVERA_PEER_AUTHORIZED_KEYS="$WORK/authorized_keys" \
    python3 "$SCRIPT" "$@"
}

cleanup() {
  set +e
  if [ -n "$SOURCE_ID" ]; then
    recovera-peer source-remove "$SOURCE_ID" >/dev/null 2>&1
  fi
  if zfs list -H "$TARGET_ROOT/$ASSET" >/dev/null 2>&1; then
    owner=$(python3 -c 'import json,sys; a=sys.argv[1]; print(json.load(open("/var/lib/recovera-peer/state.json")).get("received",{}).get(a,{}).get("source_id",""))' "$ASSET" 2>/dev/null)
    if [ -z "$owner" ]; then
      owner=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("sourceApplianceId", ""))' "/datto/config/keys/$ASSET.originDevice" 2>/dev/null)
    fi
    if [ -n "$SOURCE_ID" ] && [ "$owner" = "$SOURCE_ID" ]; then
      zfs destroy -r "$TARGET_ROOT/$ASSET"
    else
      echo "WARNING: not removing target test dataset because its owner does not match" >&2
    fi
  fi
  if ! zfs list -H "$TARGET_ROOT/$ASSET" >/dev/null 2>&1; then
    recovera-peer received-forget "$ASSET" >/dev/null 2>&1
  fi
  zfs list -H "$SOURCE_ROOT" >/dev/null 2>&1 && zfs destroy -r "$SOURCE_ROOT"
  for path in /datto/config/keys/$ASSET.*; do
    [ -e "$path" ] || continue
    [ "$(basename "$path")" != "${ASSET}.${path##*.}" ] || rm -f -- "$path"
  done
  rm -rf -- "$WORK"
}
trap cleanup EXIT

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
command -v recovera-peer >/dev/null
systemctl is-active --quiet recovera-peer.service
! zfs list -H "$TARGET_ROOT/$ASSET" >/dev/null 2>&1 || {
  echo "fixed test asset already exists; refusing to overwrite it" >&2
  exit 1
}
! zfs list -H "$SOURCE_ROOT" >/dev/null 2>&1 || {
  echo "fixed test source dataset already exists; refusing to overwrite it" >&2
  exit 1
}

mkdir -p "$WORK/etc" "$WORK/state" "$WORK/keys"
peer_env init >/dev/null
sed -i "s|\"source_root\": \"homePool/home/agents\"|\"source_root\": \"$SOURCE_ROOT\"|" "$WORK/etc/config.json"
SOURCE_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["appliance_id"])' "$WORK/etc/config.json")

zfs create -o mountpoint="$WORK/data" "$SOURCE_ROOT"
zfs create "$SOURCE_ROOT/$ASSET"
dd if=/dev/zero of="$WORK/data/$ASSET/test-backup.img" bs=1M count=2 status=none
printf linux > "$WORK/keys/$ASSET.osType"
printf 'a:4:{s:4:"type";s:14:"agentlessLinux";s:8:"hostname";s:16:"Recovera-E2E-Test";s:4:"name";s:16:"Recovera-E2E-Test";s:4:"uuid";s:32:"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";}' \
  > "$WORK/keys/$ASSET.agentInfo"
zfs snapshot "$SOURCE_ROOT/$ASSET@$FIRST"

code=$(recovera-peer pairing-code | head -1)
peer_env peer-add 127.0.0.1 --code "$code" --yes >/dev/null
peer_id=$(python3 -c 'import json,sys; print(next(iter(json.load(open(sys.argv[1]))["peers"])))' "$WORK/etc/config.json")

echo "full transfer"
peer_env replicate "$ASSET" --peer "$peer_id"
zfs list -H "$TARGET_ROOT/$ASSET@$FIRST" >/dev/null
[ "$(zfs get -H -o value readonly "$TARGET_ROOT/$ASSET")" = on ]
[ "$(zfs get -H -o value mountpoint "$TARGET_ROOT/$ASSET")" = "/home/agents/$ASSET" ]
[ -r "/home/agents/$ASSET/test-backup.img" ]

printf incremental >> "$WORK/data/$ASSET/test-backup.img"
zfs snapshot "$SOURCE_ROOT/$ASSET@$SECOND"
echo "incremental transfer"
peer_env replicate "$ASSET" --peer "$peer_id"
zfs list -H "$TARGET_ROOT/$ASSET@$FIRST" >/dev/null
zfs list -H "$TARGET_ROOT/$ASSET@$SECOND" >/dev/null

if ssh -T -i "$WORK/etc/id_ed25519" -o BatchMode=yes -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$WORK/etc/known_hosts" \
  recovera-repl@127.0.0.1 uname >/dev/null 2>&1; then
  echo "receiver unexpectedly allowed an arbitrary command" >&2
  exit 1
fi

python3 -c 'import json; d=json.load(open("/datto/config/keys/eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee.originDevice")); assert d["isReplicated"] is True'
echo "E2E RESULT: PASS"
