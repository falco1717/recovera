#!/bin/sh
# Migrate Recovera-owned paths from the pre-rename appliance layout.
set -eu

ROOT_PREFIX=${RECOVERA_MIGRATION_ROOT:-}
if [ -z "$ROOT_PREFIX" ] && [ "$(id -u)" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

at() { printf '%s%s' "$ROOT_PREFIX" "$1"; }
note() { printf '%s\n' "Recovera layout migration: $*"; }

move_directory() {
  old=$(at "$1")
  new=$(at "$2")
  [ -d "$old" ] || return 0
  if [ -e "$new" ]; then
    note "both $1 and $2 exist; preserving $1 for manual review"
    return 0
  fi
  mkdir -p "$(dirname "$new")"
  mv "$old" "$new"
  note "moved $1 to $2"
}

move_file() {
  old=$(at "$1")
  new=$(at "$2")
  [ -e "$old" ] || return 0
  mkdir -p "$(dirname "$new")"
  if [ -e "$new" ]; then
    if cmp -s "$old" "$new"; then
      rm -f "$old"
    else
      note "both $1 and $2 exist; preserving $1 for manual review"
    fi
    return 0
  fi
  mv "$old" "$new"
  note "moved $1 to $2"
}

move_directory /opt/spf-datto /opt/recovera
move_directory /var/lib/spf-datto-setup /var/lib/recovera-setup
move_directory /root/spf-datto-backup /root/recovera-backup
move_directory /root/.cache/spf-datto /root/.cache/recovera

move_file /var/log/spf-datto-setup.log /var/log/recovera-setup.log
move_file /var/log/spf-datto-verify.log /var/log/recovera-verify.log
move_file /var/log/spf-datto-libguestfs-test.log /var/log/recovera-libguestfs-test.log
move_file /etc/apt/sources.list.d/spf-datto-local.list /etc/apt/sources.list.d/recovera-local.list
move_file /etc/default/grub.d/99z-match-spf-datto.cfg /etc/default/grub.d/99-recovera.cfg

new_list=$(at /etc/apt/sources.list.d/recovera-local.list)
if [ -f "$new_list" ]; then
  sed -i 's#/opt/spf-datto#/opt/recovera#g' "$new_list"
fi

old_service=$(at /etc/systemd/system/spf-datto-verify.service)
old_timer=$(at /etc/systemd/system/spf-datto-verify.timer)
new_service=$(at /etc/systemd/system/recovera-verify.service)
new_timer=$(at /etc/systemd/system/recovera-verify.timer)
if [ -f "$old_service" ] || [ -f "$old_timer" ]; then
  if [ -z "$ROOT_PREFIX" ]; then
    systemctl disable --now spf-datto-verify.timer >/dev/null 2>&1 || true
  fi
  if [ -f "$old_service" ] && [ ! -e "$new_service" ]; then
    sed -e 's#/opt/spf-datto#/opt/recovera#g' -e 's/spf-datto/recovera/g' \
      "$old_service" > "$new_service"
  fi
  if [ -f "$old_timer" ] && [ ! -e "$new_timer" ]; then
    sed 's/spf-datto/recovera/g' "$old_timer" > "$new_timer"
  fi
  rm -f "$old_service" "$old_timer"
fi

if [ -z "$ROOT_PREFIX" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  [ ! -f "$new_timer" ] || systemctl enable recovera-verify.timer >/dev/null 2>&1 || true
fi

exit 0
