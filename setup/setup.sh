#!/bin/bash
# spf-datto replica: one-shot setup for a fresh Ubuntu 22.04 (jammy, amd64) VM.
#
# Installs every package from spf-datto at its exact version from the bundled .debs
# (no internet needed), then applies everything learned building spf-datto-pkgs:
# SSH lockout guard, FIPS-off boot, snapd/cloud-init removal, ZFS homePool, and a
# NetworkManager bridge with a self-check and automatic revert. See ../WALKTHROUGH.md.
#
#   sudo ./setup.sh            run (detaches into a systemd unit and follows the log)
#   sudo ./setup.sh check      preflight + apt dry run only (stages /opt/spf-datto and adds the
#                              local apt source; installs nothing)
#   sudo ./setup.sh status     show progress / follow the log of a running setup
#   sudo ./setup.sh verify     health check of a finished replica
#
# Resumable: finished phases are recorded in /var/lib/spf-datto-setup; just run it again.
set -uo pipefail

INSTALL_DIR=/opt/spf-datto
STATE_DIR=/var/lib/spf-datto-setup
LOG=/var/log/spf-datto-setup.log
VERIFY_LOG=/var/log/spf-datto-verify.log
BACKUP_DIR=/root/spf-datto-backup
UNIT=spf-datto-setup
LOCAL_LIST=/etc/apt/sources.list.d/spf-datto-local.list
LOCAL_ONLY=(-o "Dir::Etc::sourcelist=$LOCAL_LIST" -o "Dir::Etc::sourceparts=/nonexistent" -o "DPkg::Lock::Timeout=900")
EXPECTED_FAILED="openipmi.service apache2.service datto-speedsync-cache-update.service datto-system-speedsync-check.service datto-telegraf-configure.service datto-update-assets.service"
# Removals the dry run may propose on a cloud image. Anything in PROTECTED aborts.
PROTECTED_RE='^(openssh-server|sudo|systemd|network-manager|netplan\.io|zfsutils-linux|grub-pc|grub-efi-amd64|grub-efi-amd64-signed|shim-signed|linux-image-.*)$'

SELF="$(readlink -f "$0")"
BUNDLE="$(dirname "$SELF")"
MODE="${1:-run}"

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1

# ------------------------------------------------------------------------- helpers
ts()   { date '+%F %T'; }
log()  { echo "[$(ts)] $*"; }
warn() { echo "[$(ts)] WARNING: $*"; }
die()  { echo "[$(ts)] FAILED: $*"; echo "SETUP-FAILED"; exit 1; }
done_p()  { [ -f "$STATE_DIR/$1.done" ]; }
mark_p()  { mkdir -p "$STATE_DIR"; date '+%F %T' > "$STATE_DIR/$1.done"; }
phase() {   # phase <id> <description> <function>; function returns 2 = skipped, retry on next run
  if done_p "$1"; then log "== $1: $2 (already done, skipping)"; return 0; fi
  log "== $1: $2"
  "$3"; local rc=$?
  case $rc in
    0) mark_p "$1" ;;
    2) log "== $1 not completed; it will be retried the next time setup.sh runs" ;;
    *) die "$1: $2" ;;
  esac
}

load_conf() {
  local c="$INSTALL_DIR/setup.conf"; [ -f "$c" ] || c="$BUNDLE/setup.conf"
  [ -f "$c" ] || die "setup.conf not found"
  # shellcheck source=/dev/null
  . "$c"
  : "${NET_CONFIGURE:=yes}" "${NET_IP:=current}" "${NET_GATEWAY:=}" "${NET_DNS:=}" "${NET_IFACE:=}"
  : "${ZFS_CONFIGURE:=yes}" "${ZFS_DISK:=auto}" "${ZFS_MIN_GB:=20}" "${ZFS_POOL:=homePool}" "${ZFS_MOVE_HOME:=yes}"
  : "${FIPS_OFF:=yes}" "${REMOVE_SNAPD:=yes}" "${REMOVE_CLOUD_INIT:=yes}" "${APT_FREEZE:=yes}" "${AUTO_REBOOT:=yes}"
  LOGIN_USER="${LOGIN_USER:-${SUDO_USER:-}}"
  [ -n "$LOGIN_USER" ] || LOGIN_USER="$(getent passwd 1000 | cut -d: -f1)"
}

# ------------------------------------------------------------------------ preflight
preflight() {
  [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
  . /etc/os-release
  [ "${VERSION_ID:-}" = "22.04" ] || { echo "needs Ubuntu 22.04 (this is ${PRETTY_NAME:-unknown}); the packages are jammy builds"; exit 1; }
  [ "$(dpkg --print-architecture)" = amd64 ] || { echo "needs amd64"; exit 1; }
  load_conf
  id "$LOGIN_USER" >/dev/null 2>&1 || { echo "LOGIN_USER '$LOGIN_USER' does not exist"; exit 1; }
  local home; home="$(getent passwd "$LOGIN_USER" | cut -d: -f6)"
  [ -s "$home/.ssh/authorized_keys" ] || echo "WARNING: $home/.ssh/authorized_keys is empty; key login for $LOGIN_USER won't work"
  [ -d "$BUNDLE/debs" ] || [ -d "$INSTALL_DIR/debs" ] || { echo "no debs/ folder next to setup.sh"; exit 1; }
}

stage_bundle() {   # copy the bundle to /opt/spf-datto so nothing depends on /home (which may move to ZFS)
  if [ "$BUNDLE" = "$INSTALL_DIR" ]; then return 0; fi
  local need_kb free_kb
  need_kb=$(( $(du -sk "$BUNDLE" | cut -f1) + 6*1024*1024 ))   # bundle + ~6 GB for the install itself
  free_kb=$(df -Pk / | awk 'NR==2{print $4}')
  [ "$free_kb" -ge "$need_kb" ] || { echo "not enough space on /: need ~$((need_kb/1024/1024)) GB, have $((free_kb/1024/1024)) GB"; exit 1; }
  echo "staging bundle into $INSTALL_DIR ..."
  mkdir -p "$INSTALL_DIR"
  cp -a "$BUNDLE/setup.sh" "$BUNDLE/setup.conf" "$INSTALL_DIR/"
  [ -f "$BUNDLE/README.txt" ] && cp -a "$BUNDLE/README.txt" "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/lists"; cp -a "$BUNDLE/lists" "$INSTALL_DIR/"
  if [ ! -f "$INSTALL_DIR/debs/.verified" ]; then
    rm -rf "$INSTALL_DIR/debs"; cp -a "$BUNDLE/debs" "$INSTALL_DIR/"
  fi
  chmod 755 "$INSTALL_DIR/setup.sh"
}

verify_checksums() {
  [ -f "$INSTALL_DIR/debs/.verified" ] && return 0
  echo "verifying SHA256SUMS of $(ls "$INSTALL_DIR"/debs/*.deb | wc -l) packages ..."
  (cd "$INSTALL_DIR/debs" && sha256sum -c --quiet SHA256SUMS) || { echo "checksum mismatch in $INSTALL_DIR/debs"; exit 1; }
  touch "$INSTALL_DIR/debs/.verified"
}

# ------------------------------------------------------------------------- phases
p10_repo() {
  echo "deb [trusted=yes] file:$INSTALL_DIR/debs ./" > "$LOCAL_LIST"
  # fresh cloud VMs run apt-daily/unattended-upgrades right after boot; get them out of the way
  systemctl stop apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service unattended-upgrades.service 2>/dev/null || true
  apt-get -qq "${LOCAL_ONLY[@]}" update
}

p20_dryrun() {
  local sim=$STATE_DIR/dryrun.txt rem bad
  mkdir -p "$STATE_DIR"
  apt-get -s "${LOCAL_ONLY[@]}" install --allow-downgrades --allow-change-held-packages \
    $(cat "$INSTALL_DIR/lists/all-packages-versions.txt") > "$sim" 2>&1
  grep -q '^E:' "$sim" && { grep '^E:' "$sim"; return 1; }
  rem=$(awk '/^Remv/{print $2}' "$sim")
  log "dry run: install $(grep -c ^Inst "$sim"), downgrades $(grep -c '^Inst.*\[.*\] (' "$sim"), remove $(echo "$rem" | grep -c .)"
  [ -n "$rem" ] && log "will remove: $(echo $rem)"
  bad=$(echo "$rem" | grep -E "$PROTECTED_RE" || true)
  [ -z "$bad" ] || { log "refusing: dry run would remove protected packages: $(echo $bad)"; return 1; }
}

p30_prep() {
  # Datto symlinks sshd_config to sshd_config_device at every boot: "AllowGroups remote-users".
  # The group must exist and contain the login user BEFORE the first reboot, or SSH locks out.
  groupadd -f remote-users
  usermod -aG remote-users "$LOGIN_USER"
  log "$LOGIN_USER added to remote-users"
  # keep cloud-init (until it is removed) from rewriting the network config
  if [ -d /etc/cloud/cloud.cfg.d ]; then
    echo "network: {config: disabled}" > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
  fi
}

p40_install() {
  log "installing (about 15 min: metalibvirt compiles libvirt 10.9 from source)"
  apt-get -y "${LOCAL_ONLY[@]}" -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install --allow-downgrades --allow-change-held-packages \
    $(cat "$INSTALL_DIR/lists/all-packages-versions.txt") || return 1
  local audit; audit=$(dpkg --audit)
  [ -z "$audit" ] || { echo "$audit"; return 1; }
  local want have
  want=$(wc -l < "$INSTALL_DIR/lists/all-packages-versions.txt")
  have=$(comm -12 <(sort "$INSTALL_DIR/lists/all-packages-versions.txt") \
                  <(dpkg-query -W -f='${Package}=${Version}\n' | sort) | wc -l)
  log "exact versions installed: $have/$want"
  [ "$have" -eq "$want" ] || return 1
}

p50_boot() {
  if [ "$FIPS_OFF" = yes ]; then
    cat > /etc/default/grub.d/99z-match-spf-datto.cfg <<'EOF'
# Match spf-datto: 6.8 HWE generic kernel, FIPS off. ubuntu-fips stays installed;
# this sorts after 99-fips.cfg / 99-ubuntu-fips.cfg and overrides them.
GRUB_FLAVOUR_ORDER="generic"
GRUB_CMDLINE_LINUX_DEFAULT="$(echo "$GRUB_CMDLINE_LINUX_DEFAULT" | sed "s/ *fips=1//g")"
EOF
  fi
  update-grub >/dev/null 2>&1 || return 1
  log "default boot: $(awk '/^\tlinux/ {print $2; exit}' /boot/grub/grub.cfg), fips=1 entries: $(grep -c 'fips=1' /boot/grub/grub.cfg)"
}

p60_cleanup() {
  if [ "$REMOVE_SNAPD" = yes ] && dpkg -s snapd >/dev/null 2>&1; then
    apt-get -y -q -o DPkg::Lock::Timeout=900 purge snapd >/dev/null || return 1
    log "snapd purged"
  fi
  if [ "$REMOVE_CLOUD_INIT" = yes ] && dpkg -s cloud-init >/dev/null 2>&1; then
    apt-get -y -q -o DPkg::Lock::Timeout=900 purge cloud-init >/dev/null || return 1
    log "cloud-init purged"
  fi
  # snapd owns /usr/bin/snapctl; Datto repoints it. Purging snapd deletes Datto's link.
  ln -sfn /datto/bin/snapctl /usr/bin/snapctl
  snapctl --version >/dev/null 2>&1 || { log "snapctl not working"; return 1; }
  log "ordering cycles in unit graph: $(systemd-analyze verify default.target 2>&1 | grep -ci 'ordering cycle' || true)"
}

zfs_pick_disk() {
  local root_disk best="" best_size=0 name size
  root_disk=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null | head -1)
  while read -r name size; do
    [ "$name" = "$root_disk" ] && continue
    [ "$(lsblk -no NAME "/dev/$name" | wc -l)" -eq 1 ] || continue           # has partitions
    [ -z "$(lsblk -no FSTYPE "/dev/$name" | tr -d ' \n')" ] || continue      # has a filesystem / zfs label
    [ "$size" -ge $((ZFS_MIN_GB*1024*1024*1024)) ] || continue
    [ "$size" -gt "$best_size" ] && { best=$name; best_size=$size; }
  done < <(lsblk -dnbo NAME,SIZE,TYPE | awk '$3=="disk"{print $1, $2}')
  echo "$best"
}

p70_zfs() {
  [ "$ZFS_CONFIGURE" = yes ] || { log "ZFS disabled in setup.conf"; return 0; }
  modprobe zfs || return 1
  local P="$ZFS_POOL"
  if ! zpool list -H "$P" >/dev/null 2>&1; then
    zpool import "$P" >/dev/null 2>&1 && log "imported existing $P"
  fi
  if ! zpool list -H "$P" >/dev/null 2>&1; then
    for h in /sys/class/scsi_host/host*/scan; do echo "- - -" > "$h"; done; sleep 3
    local dev="$ZFS_DISK"
    [ "$dev" = auto ] && dev=$(zfs_pick_disk) && [ -n "$dev" ] && dev=/dev/$dev
    if [ -z "$dev" ] || [ "$dev" = auto ]; then
      warn "no blank disk >= ${ZFS_MIN_GB} GB found; skipping ZFS (attach one and re-run setup.sh)"
      return 2
    fi
    local id="" l
    for l in /dev/disk/by-id/wwn-* /dev/disk/by-id/scsi-* /dev/disk/by-path/*; do
      [ -e "$l" ] && [ "$(readlink -f "$l")" = "$(readlink -f "$dev")" ] && { id=$l; break; }
    done
    log "creating $P on $dev (${id:-no stable id}), $(lsblk -dno SIZE "$dev")"
    zpool create -o ashift=12 -O compression=on -O mountpoint=/$P "$P" "${id:-$dev}" || return 1
  fi
  zfs list "$P/.recv" >/dev/null 2>&1 || zfs create "$P/.recv"
  zfs list "$P/os"    >/dev/null 2>&1 || zfs create "$P/os"
  zfs list "$P/transfer" >/dev/null 2>&1 || zfs create -o mountpoint=/datto/transfer "$P/transfer"

  if [ "$ZFS_MOVE_HOME" = yes ] && [ "$(findmnt -no SOURCE /home)" != "$P/home" ]; then
    zfs list "$P/home" >/dev/null 2>&1 || zfs create -o mountpoint=/mnt/spf-newhome "$P/home"
    [ "$(zfs get -H -o value mountpoint "$P/home")" = /home ] && zfs set mountpoint=/mnt/spf-newhome "$P/home"
    rsync -aHAX /home/ /mnt/spf-newhome/ || return 1
    diff -rq /home /mnt/spf-newhome >/dev/null || { log "/home copy differs"; return 1; }
    log "/home copied and verified"
    zfs set overlay=on "$P/home"            # original /home stays underneath as a fallback
    zfs set mountpoint=/home "$P/home" || return 1
    rmdir /mnt/spf-newhome 2>/dev/null || true
  fi
  zfs list "$P/home/agents"       >/dev/null 2>&1 || zfs create "$P/home/agents"
  zfs list "$P/home/configBackup" >/dev/null 2>&1 || zfs create "$P/home/configBackup"
  local home; home="$(getent passwd "$LOGIN_USER" | cut -d: -f6)"
  [ -s "$home/.ssh/authorized_keys" ] || warn "$home/.ssh/authorized_keys missing after /home move"
  zpool list -H -o name,size,health "$P" | sed 's/^/  pool: /'
}

net_revert() {
  rm -f /etc/NetworkManager/system-connections/br0.nmconnection \
        "/etc/NetworkManager/system-connections/$1.nmconnection"
  nmcli connection reload
  nmcli connection down br0 >/dev/null 2>&1; ip link delete br0 2>/dev/null
  cp -a "$BACKUP_DIR"/netplan/*.yaml /etc/netplan/ 2>/dev/null
  netplan apply
}

p80_network() {
  [ "$NET_CONFIGURE" = yes ] || { log "network change disabled in setup.conf"; return 0; }
  if nmcli -t -f DEVICE,STATE dev 2>/dev/null | grep -q '^br0:connected'; then log "br0 already up"; return 0; fi
  local ifc mac cidr gw dns zone ipv4
  ifc="${NET_IFACE:-$(ip route show default | awk '{print $5; exit}')}"
  [ -n "$ifc" ] && [ -e "/sys/class/net/$ifc" ] || { log "cannot find the primary interface"; return 1; }
  mac=$(cat "/sys/class/net/$ifc/address")
  cidr=$(ip -4 -o addr show dev "$ifc" | awk '{print $4; exit}')
  gw="${NET_GATEWAY:-$(ip route show default dev "$ifc" | awk '{print $3; exit}')}"
  dns="${NET_DNS:-$(resolvectl dns "$ifc" 2>/dev/null | cut -d: -f2- | xargs)}"
  dns="${dns:-$gw}"
  case "$NET_IP" in
    dhcp)    ipv4=$'method=auto' ;;
    current) [ -n "$cidr" ] || { log "no current IPv4 on $ifc"; return 1; }
             ipv4="method=manual"$'\n'"address1=$cidr,$gw"$'\n'"dns=$(echo "$dns" | tr ' ' ';');" ;;
    *)       ipv4="method=manual"$'\n'"address1=$NET_IP,$gw"$'\n'"dns=$(echo "$dns" | tr ' ' ';');" ;;
  esac
  zone=""; firewall-cmd --get-zones 2>/dev/null | grep -qw datto && zone="zone=datto"
  log "bridge br0 <- $ifc ($mac); ipv4: $(echo "$ipv4" | tr '\n' ' '); $zone"

  mkdir -p "$BACKUP_DIR/netplan"; cp -a /etc/netplan/*.yaml "$BACKUP_DIR/netplan/" 2>/dev/null
  cat > /etc/NetworkManager/system-connections/br0.nmconnection <<EOF
[connection]
id=br0
type=bridge
interface-name=br0
$zone

[ethernet]
cloned-mac-address=$mac

[bridge]
stp=false

[ipv4]
$ipv4

[ipv6]
addr-gen-mode=stable-privacy
method=disabled

[proxy]
EOF
  cat > "/etc/NetworkManager/system-connections/$ifc.nmconnection" <<EOF
[connection]
id=$ifc
type=ethernet
interface-name=$ifc
master=br0
slave-type=bridge
$zone

[ethernet]

[bridge-port]
EOF
  chmod 600 /etc/NetworkManager/system-connections/br0.nmconnection "/etc/NetworkManager/system-connections/$ifc.nmconnection"

  log "switching networking to NetworkManager (an SSH session may drop if the address changes)"
  rm -f /etc/netplan/*.yaml
  netplan apply
  ip addr flush dev "$ifc"
  nmcli connection reload
  nmcli connection up "$ifc" >/dev/null 2>&1
  nmcli connection up br0 >/dev/null 2>&1

  local ok="" i
  for i in $(seq 1 45); do
    if ip -4 -o addr show dev br0 | grep -q inet && ping -c1 -W2 "$gw" >/dev/null 2>&1; then ok=1; break; fi
    sleep 2
  done
  if [ -z "$ok" ]; then
    log "br0 did not reach the gateway $gw; reverting to the previous netplan config"
    net_revert "$ifc"
    warn "network left on netplan/networkd; see $LOG"
    return 2
  fi
  log "br0 up: $(ip -4 -o addr show dev br0 | awk '{print $4}'), gateway $gw reachable"
  # spf-datto has no networkd; otherwise its wait-online adds ~2 min to every boot
  systemctl disable --now systemd-networkd-wait-online.service systemd-networkd.socket systemd-networkd.service >/dev/null 2>&1
}

p85_apt() {
  if [ "$APT_FREEZE" = yes ]; then
    mkdir -p "$BACKUP_DIR/apt"
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
      [ -f "$f" ] && [ "$f" != "$LOCAL_LIST" ] && mv "$f" "$BACKUP_DIR/apt/"
    done
    touch /etc/apt/sources.list
    systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service >/dev/null 2>&1
    log "apt frozen: only $LOCAL_LIST remains (Ubuntu sources backed up to $BACKUP_DIR/apt)"
  else
    systemctl start apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
    log "apt left on Ubuntu sources; unattended-upgrades will drift from spf-datto's versions"
  fi
  apt-get -qq update 2>/dev/null || true
}

p90_verify_timer() {
  cat > /etc/systemd/system/spf-datto-verify.service <<EOF
[Unit]
Description=spf-datto replica post-setup verification
[Service]
Type=oneshot
ExecStart=$INSTALL_DIR/setup.sh verify --after-boot
EOF
  cat > /etc/systemd/system/spf-datto-verify.timer <<EOF
[Unit]
Description=Run spf-datto replica verification once after boot
[Timer]
OnBootSec=3min
[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable spf-datto-verify.timer >/dev/null 2>&1
}

# --------------------------------------------------------------------------- verify
verify() {
  load_conf
  local fails=0 failed unexpected cyc want have sshlink
  check() { if eval "$2" >/dev/null 2>&1; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
  echo "spf-datto replica verification $(ts) on $(hostname)"
  echo "  kernel $(uname -r), fips_enabled=$(cat /proc/sys/crypto/fips_enabled 2>/dev/null || echo n/a)"
  want=$(wc -l < "$INSTALL_DIR/lists/all-packages-versions.txt")
  have=$(comm -12 <(sort "$INSTALL_DIR/lists/all-packages-versions.txt") <(dpkg-query -W -f='${Package}=${Version}\n' | sort) | wc -l)
  cyc=$(journalctl -b -o cat 2>/dev/null | grep -c 'Found ordering cycle')
  sshlink=$(readlink /etc/ssh/sshd_config)
  check "packages at spf-datto versions: $have/$want"      "[ $have -eq $want ]"
  check "dpkg --audit clean"                               "[ -z \"\$(dpkg --audit)\" ]"
  check "no systemd ordering cycles this boot ($cyc)"      "[ $cyc -eq 0 ]"
  check "sshd active, config -> ${sshlink:-regular file}"  "systemctl is-active ssh"
  check "$LOGIN_USER in remote-users"                      "id -nG $LOGIN_USER | grep -qw remote-users"
  check "snapctl works"                                    "snapctl --version"
  check "php8.1-fpm active (/run/php)"                     "systemctl is-active php8.1-fpm"
  # libvirtd is socket-activated with --timeout 120, so "inactive" is normal; ask it instead
  check "libvirt answers (virsh version)"                  "virsh -c qemu:///system version"
  if [ "$ZFS_CONFIGURE" = yes ] && zpool list -H "$ZFS_POOL" >/dev/null 2>&1; then
    check "$ZFS_POOL ONLINE"                               "[ \"\$(zpool list -H -o health $ZFS_POOL)\" = ONLINE ]"
    check "zfs-mount active"                               "systemctl is-active zfs-mount"
    [ "$ZFS_MOVE_HOME" = yes ] && check "/home on $ZFS_POOL/home" "[ \"\$(findmnt -no SOURCE /home)\" = $ZFS_POOL/home ]"
  else
    echo "  --    ZFS pool not present"
  fi
  if [ "$NET_CONFIGURE" = yes ]; then
    check "br0 managed by NetworkManager: $(ip -4 -o addr show dev br0 2>/dev/null | awk '{print $4}')" "nmcli -t -f DEVICE,STATE dev | grep -q '^br0:connected'"
  fi
  [ "$NET_CONFIGURE" = yes ] || EXPECTED_FAILED="$EXPECTED_FAILED NetworkManager-wait-online.service datto-network-repair.service"
  [ "$ZFS_CONFIGURE" = yes ] || EXPECTED_FAILED="$EXPECTED_FAILED datto-zfs-cache-update.service"
  failed=$(systemctl --failed --no-legend --plain | awk '{print $1}')
  unexpected=$(for u in $failed; do echo " $EXPECTED_FAILED " | grep -q " $u " || echo "$u"; done)
  echo "  expected failures (no IPMI / no Datto registration): $(for u in $failed; do echo " $EXPECTED_FAILED " | grep -q " $u " && echo -n "$u "; done)"
  if [ -n "$unexpected" ]; then echo "  FAIL  unexpected failed units: $(echo $unexpected)"; fails=$((fails+1)); else echo "  ok    no unexpected failed units"; fi
  echo "RESULT: $([ $fails -eq 0 ] && echo PASS || echo "$fails check(s) failed")"
  return $fails
}

# ----------------------------------------------------------------------------- main
run_all() {
  load_conf
  log "spf-datto replica setup starting on $(hostname) ($(. /etc/os-release; echo "$PRETTY_NAME"), kernel $(uname -r))"
  log "config: login=$LOGIN_USER net=$NET_CONFIGURE/$NET_IP zfs=$ZFS_CONFIGURE/$ZFS_DISK fips_off=$FIPS_OFF freeze=$APT_FREEZE"
  phase p10 "local apt repo from $INSTALL_DIR/debs"           p10_repo
  phase p20 "dry run"                                         p20_dryrun
  phase p30 "SSH guard (remote-users) and cloud-init network" p30_prep
  phase p40 "install all packages at exact versions"          p40_install
  phase p50 "boot config (FIPS off)"                          p50_boot
  phase p60 "remove snapd + cloud-init, restore snapctl"      p60_cleanup
  phase p70 "ZFS $ZFS_POOL"                                   p70_zfs
  phase p80 "NetworkManager bridge br0"                       p80_network
  phase p85 "apt sources"                                     p85_apt
  phase p90 "post-boot verification timer"                    p90_verify_timer
  verify || true
  log "setup finished; report above. Post-reboot check: $VERIFY_LOG"
  echo "SETUP-COMPLETE"
  if [ "$AUTO_REBOOT" = yes ]; then
    log "rebooting in 15 s"
    systemd-run --on-active=15 --unit=spf-datto-reboot /bin/systemctl reboot >/dev/null
  fi
}

follow() {
  echo "following $LOG (Ctrl-C stops following; setup keeps running)"
  tail -n +1 -f "$LOG" &
  local t=$!
  while systemctl is-active --quiet "$UNIT"; do sleep 3; done
  sleep 1; kill $t 2>/dev/null
  grep -q SETUP-COMPLETE "$LOG" && echo ">>> done. ssh back in after the reboot; check: sudo cat $VERIFY_LOG"
}

case "$MODE" in
  run)
    if [ "${SPF_DETACHED:-}" = 1 ]; then run_all; exit $?; fi
    preflight
    if systemctl is-active --quiet "$UNIT"; then echo "setup is already running"; follow; exit 0; fi
    stage_bundle; verify_checksums
    echo "starting setup as systemd unit $UNIT (safe to lose this SSH session)"
    : >> "$LOG"
    echo "------------------------------------------------------------ $(ts)" >> "$LOG"
    systemd-run --unit="$UNIT" --collect --setenv=SPF_DETACHED=1 \
      --property=StandardOutput=append:"$LOG" --property=StandardError=append:"$LOG" \
      /bin/bash "$INSTALL_DIR/setup.sh" run >/dev/null || die "could not start $UNIT"
    sleep 1; follow ;;
  check)
    preflight; stage_bundle; verify_checksums; load_conf
    mkdir -p "$STATE_DIR"; p10_repo && p20_dryrun && echo "check OK: setup.sh can run" ;;
  status)
    ls "$STATE_DIR" 2>/dev/null | sed 's/^/done: /'
    if systemctl is-active --quiet "$UNIT"; then follow; else tail -n 25 "$LOG" 2>/dev/null; fi ;;
  verify)
    [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
    if [ "${2:-}" = --after-boot ]; then
      for i in $(seq 1 60); do [ "$(systemctl is-system-running)" = starting ] || break; sleep 5; done
      verify > "$VERIFY_LOG" 2>&1; rc=$?
      systemctl disable spf-datto-verify.timer >/dev/null 2>&1
      exit $rc
    fi
    verify ;;
  *) sed -n '2,15p' "$SELF"; exit 1 ;;
esac
