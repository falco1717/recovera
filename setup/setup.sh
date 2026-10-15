#!/bin/bash
# Recovera: one-shot setup for a fresh Ubuntu 22.04 (jammy, amd64) VM.
#
# Installs the reviewed application package set at its exact versions from the bundled
# .debs (no internet needed), then applies everything learned building spf-datto-pkgs:
# SSH lockout guard, FIPS-off boot, snapd/cloud-init removal, ZFS homePool, and a
# NetworkManager bridge with a self-check and automatic revert.
#
#   sudo ./setup.sh            run (detaches into a systemd unit and follows the log)
#   sudo ./setup.sh check      preflight + apt dry run only (stages /opt/spf-datto and adds the
#                              local apt source; installs nothing)
#   sudo ./setup.sh status     show progress / follow the log of a running setup
#   sudo ./setup.sh verify     health check of a finished replica
#   sudo ./setup.sh install-peer install/update only the peer-replication service
#   sudo ./setup.sh install-updater install/update only the signed updater
#   sudo ./setup.sh apply-branding apply/update only the Recovera WebUI branding
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
LOCAL_ONLY=(-o "Dir::Etc::sourcelist=$LOCAL_LIST" -o "Dir::Etc::sourceparts=/nonexistent" -o "DPkg::Lock::Timeout=900" -o "Acquire::Retries=0")
EXPECTED_FAILED="openipmi.service datto-ipmi-setup.service datto-asset-replication-reconcile.service datto-https-check.service datto-send-volumes-to-portal.service datto-speedsync-cache-update.service datto-system-speedsync-check.service datto-update-assets.service datto-upgrade-channel-get.service"
# Source-appliance identity, removed telemetry, and physical watchdog configuration
# are never copied to a replica. Everything else that differs is applied in p45.
CONFFILE_DENY_RE='^(/root/|/etc/(filebeat|fluent-bit|telegraf)/|/etc/apache2/ssl/|/etc/bash\.bashrc$|/etc/watchdog\.conf$|/etc/ssh/ssh_host_|/etc/hostname$|/etc/machine-id$)'
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
primary_iface() {
  local ifc
  ifc=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
  [ -n "$ifc" ] || ifc=$(ip -4 -o addr show scope global 2>/dev/null | awk '$2 != "lo" {print $2; exit}')
  echo "$ifc"
}
offline_run() {
  if [ "${OFFLINE_MODE:-yes}" != yes ]; then "$@"; return $?; fi
  if command -v systemd-run >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemd-run --quiet --wait --pipe --collect \
      --unit="${UNIT}-offline-${BASHPID:-$$}-$RANDOM" --property=PrivateNetwork=yes \
      --setenv=DEBIAN_FRONTEND=noninteractive --setenv=NEEDRESTART_SUSPEND=1 \
      --setenv=PIP_NO_INDEX=1 --setenv="PIP_FIND_LINKS=$INSTALL_DIR/wheels" \
      --setenv=PIP_DISABLE_PIP_VERSION_CHECK=1 -- "$@"
  elif command -v unshare >/dev/null 2>&1; then
    PIP_NO_INDEX=1 PIP_FIND_LINKS="$INSTALL_DIR/wheels" PIP_DISABLE_PIP_VERSION_CHECK=1 \
      unshare --net -- "$@"
  else
    log "no private-network runner is available (need systemd-run or unshare)"
    return 1
  fi
}
restore_policy_rc() {
  local policy=/usr/sbin/policy-rc.d
  local policy_backup=$STATE_DIR/policy-rc.d.before-p40
  local policy_marker=$STATE_DIR/policy-rc.d.setup-state
  [ -f "$policy_marker" ] || return 0
  rm -f "$policy"
  if [ "$(cat "$policy_marker")" = original ] && { [ -e "$policy_backup" ] || [ -L "$policy_backup" ]; }; then
    cp -a "$policy_backup" "$policy" || return 1
  fi
  rm -f "$policy_backup" "$policy_marker"
}
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
  : "${REQUIRE_KVM:=yes}" "${MIN_RAM_GB:=8}"
  : "${ZFS_CONFIGURE:=yes}" "${ZFS_DISK:=auto}" "${ZFS_MIN_GB:=20}" "${ZFS_POOL:=homePool}" "${ZFS_MOVE_HOME:=yes}"
  : "${PEER_REPLICATION:=yes}"
  : "${FIPS_OFF:=yes}" "${REMOVE_SNAPD:=yes}" "${REMOVE_CLOUD_INIT:=yes}" "${APT_FREEZE:=yes}" "${OFFLINE_MODE:=yes}" "${AUTO_REBOOT:=yes}"
  LOGIN_USER="${LOGIN_USER:-${SUDO_USER:-}}"
  [ -n "$LOGIN_USER" ] || LOGIN_USER="$(getent passwd 1000 | cut -d: -f1)"
}

validate_conf() {
  case "$OFFLINE_MODE" in yes|no) ;; *) die "OFFLINE_MODE must be yes or no" ;; esac
  case "$REQUIRE_KVM" in yes|no) ;; *) die "REQUIRE_KVM must be yes or no" ;; esac
  [[ "$MIN_RAM_GB" =~ ^[1-9][0-9]*$ ]] || die "MIN_RAM_GB must be a positive integer"
  case "$ZFS_CONFIGURE" in yes|no|auto) ;; *) die "ZFS_CONFIGURE must be yes, no, or auto" ;; esac
  case "$PEER_REPLICATION" in yes|no) ;; *) die "PEER_REPLICATION must be yes or no" ;; esac
  [ "$PEER_REPLICATION" != yes ] || [ "$ZFS_CONFIGURE" != no ] || \
    die "PEER_REPLICATION=yes requires ZFS_CONFIGURE=yes or auto"
  if [ "$OFFLINE_MODE" = yes ]; then
    [ "$APT_FREEZE" = yes ] || die "OFFLINE_MODE=yes requires APT_FREEZE=yes"
    command -v systemd-run >/dev/null 2>&1 || command -v unshare >/dev/null 2>&1 || \
      die "OFFLINE_MODE=yes needs systemd-run or unshare for private-network package operations"
  fi
}

kvm_ready() {
  local module=""
  if grep -qE '(^|[[:space:]])vmx([[:space:]]|$)' /proc/cpuinfo; then
    module=kvm_intel
  elif grep -qE '(^|[[:space:]])svm([[:space:]]|$)' /proc/cpuinfo; then
    module=kvm_amd
  else
    return 1
  fi
  modprobe kvm >/dev/null 2>&1 || true
  modprobe "$module" >/dev/null 2>&1 || true
  [ -c /dev/kvm ]
}

# ------------------------------------------------------------------------ preflight
preflight() {
  [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
  . /etc/os-release
  [ "${VERSION_ID:-}" = "22.04" ] || { echo "needs Ubuntu 22.04 (this is ${PRETTY_NAME:-unknown}); the packages are jammy builds"; exit 1; }
  [ "$(dpkg --print-architecture)" = amd64 ] || { echo "needs amd64"; exit 1; }
  load_conf
  validate_conf
  local mem_kb mem_gb
  mem_kb=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
  # Linux reserves a small part of configured VM memory, so compare the
  # ceiling of MemTotal rather than rejecting an 8 GB VM that reports ~7.8 GiB.
  mem_gb=$(( (${mem_kb:-0} + 1024*1024 - 1) / 1024 / 1024 ))
  [ "$mem_gb" -ge "$MIN_RAM_GB" ] || {
    echo "needs at least ${MIN_RAM_GB} GB RAM for local recovery-point boot verification (detected ${mem_gb} GB)"
    echo "increase the appliance VM memory while powered off, then retry"
    exit 1
  }
  if [ "$REQUIRE_KVM" = yes ] && ! kvm_ready; then
    local virt
    virt=$(systemd-detect-virt 2>/dev/null || echo unknown)
    if [ "$virt" != none ] && [ "$virt" != unknown ]; then
      echo "hardware virtualization is unavailable inside this $virt VM"
      echo "enable nested virtualization (Expose hardware-assisted virtualization) on the appliance VM, cold-start it, and retry"
    else
      echo "hardware virtualization is unavailable; enable Intel VT-x or AMD-V in firmware and retry"
    fi
    exit 1
  fi
  id "$LOGIN_USER" >/dev/null 2>&1 || { echo "LOGIN_USER '$LOGIN_USER' does not exist"; exit 1; }
  local home; home="$(getent passwd "$LOGIN_USER" | cut -d: -f6)"
  [ -s "$home/.ssh/authorized_keys" ] || echo "WARNING: $home/.ssh/authorized_keys is empty; key login for $LOGIN_USER won't work"
  [ -d "$BUNDLE/debs" ] || [ -d "$INSTALL_DIR/debs" ] || { echo "no debs/ folder next to setup.sh"; exit 1; }
  compgen -G "$BUNDLE/wheels/npyscreen-4.10.5-*.whl" >/dev/null || \
    compgen -G "$INSTALL_DIR/wheels/npyscreen-4.10.5-*.whl" >/dev/null || {
      echo "missing bundled npyscreen 4.10.5 wheel required by datto-siris-os-2"; exit 1;
    }
  if [ "$ZFS_CONFIGURE" = yes ] && ! { command -v zpool >/dev/null 2>&1 && zpool list -H "$ZFS_POOL" >/dev/null 2>&1; }; then
    local zfs_dev="$ZFS_DISK"
    [ "$zfs_dev" = auto ] && zfs_dev=$(zfs_pick_disk)
    [ -n "$zfs_dev" ] && [ "$zfs_dev" != auto ] || {
      echo "no blank disk >= ${ZFS_MIN_GB} GB found for required ZFS pool $ZFS_POOL"
      echo "attach a blank second disk (recommended), or explicitly set ZFS_CONFIGURE=auto/no for a limited troubleshooting install"
      exit 1
    }
  fi
}

stage_bundle() {   # copy the bundle to /opt/spf-datto so nothing depends on /home (which may move to ZFS)
  if [ "$BUNDLE" = "$INSTALL_DIR" ]; then return 0; fi
  local need_kb free_kb
  # Validate every required source before replacing an already-staged copy. This
  # prevents an incomplete extraction from deleting a usable offline bundle.
  [ -f "$BUNDLE/setup.sh" ] || die "missing setup.sh in bundle: $BUNDLE"
  [ -f "$BUNDLE/setup.conf" ] || die "missing setup.conf in bundle: $BUNDLE"
  [ -d "$BUNDLE/debs" ] || die "missing debs/ in bundle: $BUNDLE"
  [ -d "$BUNDLE/lists" ] || die "missing lists/ in bundle: $BUNDLE"
  [ -d "$BUNDLE/wheels" ] || die "missing wheels/ in bundle: $BUNDLE"
  [ -d "$BUNDLE/branding" ] || die "missing branding/ in bundle: $BUNDLE"
  [ -d "$BUNDLE/peer" ] || die "missing peer/ in bundle: $BUNDLE"
  [ -d "$BUNDLE/upgrade" ] || die "missing upgrade/ in bundle: $BUNDLE"
  need_kb=$(( $(du -sk "$BUNDLE" | cut -f1) + 6*1024*1024 ))   # bundle + ~6 GB for the install itself
  free_kb=$(df -Pk / | awk 'NR==2{print $4}')
  [ "$free_kb" -ge "$need_kb" ] || { echo "not enough space on /: need ~$((need_kb/1024/1024)) GB, have $((free_kb/1024/1024)) GB"; exit 1; }
  echo "staging bundle into $INSTALL_DIR ..."
  mkdir -p "$INSTALL_DIR"
  cp -a "$BUNDLE/setup.sh" "$BUNDLE/setup.conf" "$INSTALL_DIR/"
  [ -f "$BUNDLE/README.txt" ] && cp -a "$BUNDLE/README.txt" "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/wheels"; cp -a "$BUNDLE/wheels" "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/lists"; cp -a "$BUNDLE/lists" "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/branding"; cp -a "$BUNDLE/branding" "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/peer"; cp -a "$BUNDLE/peer" "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/upgrade"; cp -a "$BUNDLE/upgrade" "$INSTALL_DIR/"
  if [ -d "$BUNDLE/conffiles" ]; then rm -rf "$INSTALL_DIR/conffiles"; cp -a "$BUNDLE/conffiles" "$INSTALL_DIR/"; fi
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
  offline_run apt-get -qq "${LOCAL_ONLY[@]}" update
}

p20_dryrun() {
  local sim=$STATE_DIR/dryrun.txt rem bad rc
  local -a packages
  mkdir -p "$STATE_DIR"
  mapfile -t packages < "$INSTALL_DIR/lists/all-packages-versions.txt"
  offline_run apt-get -s "${LOCAL_ONLY[@]}" install --allow-downgrades --allow-change-held-packages \
    "${packages[@]}" > "$sim" 2>&1
  rc=$?
  [ "$rc" -eq 0 ] || { cat "$sim"; return "$rc"; }
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
  # Some appliance packages replace generic host files during installation.
  # Preserve the target VM's identity and usable system-wide shell defaults.
  mkdir -p "$STATE_DIR/target-base"
  for f in /etc/hosts /etc/bash.bashrc; do
    [ -e "$f" ] && cp -a "$f" "$STATE_DIR/target-base/$(basename "$f")"
  done
  # keep cloud-init (until it is removed) from rewriting the network config
  if [ -d /etc/cloud/cloud.cfg.d ]; then
    echo "network: {config: disabled}" > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
  fi
}

p40_install() {
  local policy=/usr/sbin/policy-rc.d policy_backup=$STATE_DIR/policy-rc.d.before-p40
  local policy_marker=$STATE_DIR/policy-rc.d.setup-state rc=0
  local -a packages
  log "installing (about 15 min: metalibvirt compiles libvirt 10.9 from source)"
  mapfile -t packages < "$INSTALL_DIR/lists/all-packages-versions.txt"
  mkdir -p "$STATE_DIR"
  restore_policy_rc
  if [ -e "$policy" ] || [ -L "$policy" ]; then
    rm -f "$policy_backup"; cp -a "$policy" "$policy_backup" || return 1
    echo original > "$policy_marker"
  else
    rm -f "$policy_backup"
    echo absent > "$policy_marker"
  fi
  trap restore_policy_rc EXIT
  printf '#!/bin/sh\nexit 101\n' > "$policy" || return 1
  chmod 755 "$policy" || return 1
  offline_run apt-get -y "${LOCAL_ONLY[@]}" -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install --allow-downgrades --allow-change-held-packages \
    "${packages[@]}" || rc=$?
  restore_policy_rc || return 1
  trap - EXIT
  [ "$rc" -eq 0 ] || return "$rc"
  local audit; audit=$(dpkg --audit)
  [ -z "$audit" ] || { echo "$audit"; return 1; }
  local want have
  want=$(wc -l < "$INSTALL_DIR/lists/all-packages-versions.txt")
  have=$(comm -12 <(sort "$INSTALL_DIR/lists/all-packages-versions.txt") \
                  <(dpkg-query -W -f='${Package}=${Version}\n' | sort) | wc -l)
  log "exact versions installed: $have/$want"
  [ "$have" -eq "$want" ] || return 1
}

restore_conf() { local f; for f in "$@"; do [ -e "$BACKUP_DIR/conffiles$f" ] && cp -a "$BACKUP_DIR/conffiles$f" "$f"; done; }

remove_cloud_client_cert_auth() {
  # A registered appliance downloads cloud-api-ca at boot and uses it for optional
  # client-certificate authentication. An air-gapped replica cannot fetch that CA;
  # snapctl otherwise leaves a zero-byte bundle which prevents Apache from starting.
  # This replica has no cloud authorization/enrollment flow, so remove the unused
  # client-auth directives and stop the boot-time downloader instead of manufacturing
  # cloud credentials. The local first-run wizard remains available.
  local f
  for f in /etc/apache2/sites-available/device.conf \
           /etc/apache2/sites-available/server.conf \
           /etc/apache2/sites-enabled/device.conf; do
    [ -f "$f" ] || continue
    sed -Ei '/^[[:space:]]*(SSLCACertificateFile|SSLVerifyClient|SSLVerifyDepth)[[:space:]]/d' "$f"
  done
  systemctl disable --now datto-apache-ca-update-boot.service >/dev/null 2>&1 || true
}

disable_online_registration_gates() {
  # The stock first-run wizard renders an online-update pane even when the
  # authorization pane is disabled. Its failure path enables Next visually but
  # its validator still rejects the click while networkConnected=false. Remove
  # that pane on this deliberately offline replica and stop its perpetual
  # connectivity poll when no online-only pane remains.
  local f
  for f in \
    /usr/lib/datto/device/templates/commonlookandfeel/Registration/Register/index.html.twig \
    /usr/lib/datto/device/templates/vintage/Registration/Register/index.html.twig; do
    [ -f "$f" ] || continue
    if ! grep -q 'spf-datto offline replica: skip online update pane' "$f"; then
      sed -i "/^{% set panes = \[\] %}$/i\\{% set updatePaneEnabled = false %} {# spf-datto offline replica: skip online update pane #}" "$f" || return 1
    fi
  done
  for f in \
    /datto/web/commonlookandfeel/js/App/Registration/RegisterWizard.js \
    /datto/web/vintage/js/App/Registration/RegisterWizard.js; do
    [ -f "$f" ] || continue
    if ! grep -q 'spf-datto offline replica: no online panes' "$f"; then
      sed -i '/^[[:space:]]*this\.checkNetworkConnectivity();$/c\        // spf-datto offline replica: no online panes, so do not poll forever\n        if (this.context.authorizationPaneEnabled || this.context.updatePaneEnabled) {\n            this.checkNetworkConnectivity();\n        } else {\n            this.networkConnected = true;\n        }' "$f" || return 1
    fi
  done
  # Production Twig caches do not check source mtimes. Invalidate only the two
  # compiled registration index templates, then let Twig rebuild them on demand.
  if [ -d /var/cache/datto/device/prod/twig ]; then
    { find /var/cache/datto/device/prod/twig -type f -name '*.php' -exec \
      grep -lZ 'Registration/Register/index.html.twig' {} + 2>/dev/null || true; } | xargs -0 -r rm -f || return 1
  fi
  systemctl restart php8.1-fpm >/dev/null 2>&1 || return 1
}

install_offline_registration_finalizer() {
  # RegistrationService performs the important local work (hostname, administrator,
  # timezone, local login, and the registration marker) only after Datto Cloud's
  # registerNow RPC succeeds. Preserve that native routine, but replace its cloud
  # clients reachable from this one flow with an in-process client that returns
  # local success without opening a network connection.
  install -d -m 0755 /datto/web/commonlookandfeel/js/App/Registration \
    /datto/web/vintage/js/App/Registration

  cat > /datto/web/offline-register.php <<'PHP'
<?php
declare(strict_types=1);

use Datto\AppKernel;
use Datto\Cloud\JsonRpcClient;
use Datto\Service\Registration\Registrant;

header('Content-Type: application/json');
header('Cache-Control: no-store');

function failOfflineRegistration(int $status, string $message): never
{
    http_response_code($status);
    echo json_encode(['ok' => false, 'error' => $message]);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    failOfflineRegistration(405, 'POST required');
}
if (strcasecmp($_SERVER['HTTP_X_REQUESTED_WITH'] ?? '', 'XMLHttpRequest') !== 0) {
    failOfflineRegistration(403, 'Invalid request');
}

$host = strtolower(preg_replace('/:\\d+$/', '', $_SERVER['HTTP_HOST'] ?? ''));
$refererHost = strtolower((string) parse_url($_SERVER['HTTP_REFERER'] ?? '', PHP_URL_HOST));
if ($host === '' || $refererHost === '' || !hash_equals($host, $refererHost)) {
    failOfflineRegistration(403, 'Invalid request origin');
}

$lock = fopen('/run/lock/spf-datto-offline-registration.lock', 'c');
if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
    failOfflineRegistration(409, 'Registration is already in progress');
}

$input = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($input)) {
    failOfflineRegistration(400, 'Invalid registration data');
}

$user = trim((string) ($input['user'] ?? ''));
$password = (string) ($input['password'] ?? '');
$hostname = trim((string) ($input['hostname'] ?? ''));
$timezone = trim((string) ($input['timezone'] ?? ''));
$email = trim((string) ($input['email'] ?? ''));
$datacenter = trim((string) ($input['datacenterLocation'] ?? ''));
$recommendedDatacenter = trim((string) ($input['recommendedDatacenter'] ?? ''));

if (!preg_match('/^[a-z_][a-z0-9_-]{0,31}$/i', $user)) {
    failOfflineRegistration(400, 'Invalid administrator username');
}
if (strlen($password) < 8 || str_contains($password, "\0")) {
    failOfflineRegistration(400, 'Invalid administrator password');
}
if (!preg_match('/^(?=.{1,63}$)[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/', $hostname)) {
    failOfflineRegistration(400, 'Invalid device name');
}
if (!in_array($timezone, timezone_identifiers_list(), true)) {
    failOfflineRegistration(400, 'Invalid timezone');
}
if (filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
    failOfflineRegistration(400, 'Invalid email address');
}

require '/usr/lib/datto/device/vendor/autoload.php';

final class SpfDattoOfflineRegistrationClient extends JsonRpcClient
{
    public function __construct()
    {
    }

    private function answer(string $method, $arguments = null)
    {
        error_log("Offline registration satisfied local cloud RPC: $method");
        switch ($method) {
            case 'v1/device/registration/registerNow':
            case 'v1/device/contactInformation/setDeviceContactInformation':
            case 'v1/device/ddns/update':
                return true;
            case 'v1/device/billing/getServiceInfo':
                return [];
            default:
                throw new RuntimeException("Offline registration blocked unexpected cloud method: $method");
        }
    }

    public function query($method, $arguments = null)
    {
        return $this->answer((string) $method, $arguments);
    }

    public function queryWithId($method, $arguments = null)
    {
        return $this->answer((string) $method, $arguments);
    }

    public function notify($method, $arguments = null)
    {
        return $this->answer((string) $method, $arguments);
    }

    public function notifyWithId($method, $arguments = null)
    {
        return $this->answer((string) $method, $arguments);
    }
}

function replaceOfflineRegistrationCloudClients(
    object $object,
    JsonRpcClient $replacement,
    SplObjectStorage $seen,
    int $depth = 0
): int {
    if ($depth > 6 || $seen->contains($object)) {
        return 0;
    }
    $seen->attach($object);
    $replaced = 0;

    for ($class = new ReflectionObject($object); $class; $class = $class->getParentClass()) {
        foreach ($class->getProperties() as $property) {
            if ($property->isStatic() || $property->getDeclaringClass()->getName() !== $class->getName()) {
                continue;
            }
            $property->setAccessible(true);
            if (method_exists($property, 'isInitialized') && !$property->isInitialized($object)) {
                continue;
            }
            try {
                $value = $property->getValue($object);
            } catch (Throwable $error) {
                continue;
            }
            if ($value instanceof JsonRpcClient) {
                $property->setValue($object, $replacement);
                ++$replaced;
                continue;
            }
            if (is_object($value) && str_starts_with(get_class($value), 'Datto\\')) {
                $replaced += replaceOfflineRegistrationCloudClients(
                    $value,
                    $replacement,
                    $seen,
                    $depth + 1
                );
            }
        }
    }
    return $replaced;
}

try {
    $kernel = AppKernel::getBootedInstance();
    $container = $kernel->getContainer();
    $controller = $container->get('Datto\\App\\Controller\\Api\\V1\\Device\\Register');

    $serviceProperty = new ReflectionProperty($controller, 'registrationService');
    $serviceProperty->setAccessible(true);
    $registrationService = $serviceProperty->getValue($controller);

    if ($registrationService->isRegistered()) {
        failOfflineRegistration(409, 'Device is already registered');
    }

    $userServiceProperty = new ReflectionProperty($registrationService, 'userService');
    $userServiceProperty->setAccessible(true);
    $userService = $userServiceProperty->getValue($registrationService);
    $pendingPath = '/datto/config/local/offline-registration.pending.json';
    $pending = null;
    if (is_file($pendingPath)) {
        $pending = json_decode((string) file_get_contents($pendingPath), true);
        if (!is_array($pending)
            || !hash_equals((string) ($pending['user'] ?? ''), $user)
            || !hash_equals((string) ($pending['hostname'] ?? ''), $hostname)) {
            failOfflineRegistration(409, 'A different incomplete registration must be cleared first');
        }
        if ($userService->exists($user)) {
            $userService->delete($user);
        }
    } elseif ($userService->exists($user)) {
        failOfflineRegistration(409, 'Administrator username already exists');
    }
    if (file_put_contents(
        $pendingPath,
        json_encode(['user' => $user, 'hostname' => $hostname], JSON_THROW_ON_ERROR),
        LOCK_EX
    ) === false) {
        throw new RuntimeException('Could not create the offline registration retry marker');
    }

    $replacement = new SpfDattoOfflineRegistrationClient();
    $replaced = replaceOfflineRegistrationCloudClients(
        $registrationService,
        $replacement,
        new SplObjectStorage()
    );
    if ($replaced < 2) {
        throw new RuntimeException('Could not isolate native registration from cloud clients');
    }

    $registrant = new Registrant(
        $user,
        $password,
        $hostname,
        $timezone,
        $email,
        $datacenter,
        $recommendedDatacenter
    );
    $registrationService->register($registrant);

    $localLoginServiceProperty = new ReflectionProperty($registrationService, 'localLoginService');
    $localLoginServiceProperty->setAccessible(true);
    $localLoginService = $localLoginServiceProperty->getValue($registrationService);
    $localLoginService->enable();
    if (!$localLoginService->isEnabled()) {
        throw new RuntimeException('Could not enable local administrator login');
    }

    if (!$registrationService->isRegistered()) {
        throw new RuntimeException('Local registration did not set the completion marker');
    }

    @unlink($pendingPath);
    @unlink('/datto/config/local/reg.error');
    echo json_encode(['ok' => true]);
} catch (Throwable $error) {
    error_log('Offline registration failed: ' . $error->getMessage());
    failOfflineRegistration(500, 'Could not complete local registration');
}
PHP
  chmod 0644 /datto/web/offline-register.php || return 1

  cat > /datto/web/commonlookandfeel/js/App/Registration/OfflineRegister.js <<'JS'
(function ($, RegisterWizard) {
    "use strict";

    // Replace only the final submission. The server-side finalizer invokes the
    // appliance's native RegistrationService with its cloud call stubbed locally.
    RegisterWizard.prototype.finish = function (done) {
        const self = this;
        const user = self.$userName.val();
        const password = self.$password.val();
        const $deviceMigrationBox = $("#deviceMigrationRedirect");

        const pass = function () {
            const params = {
                user: user,
                password: password,
                email: self.$email.val(),
                hostname: self.$deviceName.val(),
                timezone: self.$timeZone.val(),
                datacenterLocation: self.$datacenter.val(),
                recommendedDatacenter: self.recommendedDataCenter
            };

            $.ajax({
                url: '/offline-register.php',
                method: 'POST',
                contentType: 'application/json',
                dataType: 'json',
                data: JSON.stringify(params)
            }).done(function () {
                const formData = {};
                formData.username = user;
                formData.password = password;
                formData[self.context.csrfTokenId] = self.context.csrfToken;
                const redirectUrl = $deviceMigrationBox.prop('checked') ?
                    self.context.urls.successDeviceMigration : self.context.urls.success;
                $.post(self.context.loginPath, formData).always(function () {
                    self.close(redirectUrl);
                    done();
                });
            }).fail(function () {
                self.displayValidation.setError(
                    self.$navFinish,
                    self.translator.trans('registration.register.pane.review.errors.registrationFailed')
                );
                done();
            });
        };

        this.panes[this.currentPane].validate(pass, done);
    };
})(jQuery, Datto.App.RegisterWizard);
JS
  cp -a /datto/web/commonlookandfeel/js/App/Registration/OfflineRegister.js \
    /datto/web/vintage/js/App/Registration/OfflineRegister.js || return 1

  local f asset
  for f in \
    /usr/lib/datto/device/templates/commonlookandfeel/Registration/Register/index.html.twig \
    /usr/lib/datto/device/templates/vintage/Registration/Register/index.html.twig; do
    [ -f "$f" ] || continue
    if ! grep -q 'OfflineRegister.js' "$f"; then
      if [[ "$f" == *commonlookandfeel* ]]; then asset=commonlookandfeel; else asset=vintage; fi
      sed -i "/RegisterWizard\.js/a\\    <script type=\"text/javascript\" src=\"{{ asset('$asset/js/App/Registration/OfflineRegister.js') }}\"></script>" "$f" || return 1
    fi
  done

  php -l /datto/web/offline-register.php >/dev/null || return 1
  if [ -d /var/cache/datto/device/prod/twig ]; then
    { find /var/cache/datto/device/prod/twig -type f -name '*.php' -exec \
      grep -lZ 'Registration/Register/index.html.twig' {} + 2>/dev/null || true; } | xargs -0 -r rm -f || return 1
  fi
  systemctl restart php8.1-fpm >/dev/null 2>&1 || return 1
}

generate_local_tls_certificate() {
  local dir key cert cn ip san cert_cn
  dir=/etc/apache2/ssl
  key=$dir/www.key
  cert=$dir/www.crt
  cn=$(hostname -f 2>/dev/null || hostname)
  cert_cn=$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253 2>/dev/null |
    sed -n 's/^subject=.*CN=\([^,]*\).*$/\1/p')
  if [ -s "$key" ] && [ -s "$cert" ] && [ "$cert_cn" = "$cn" ] &&
     openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null 2>&1; then
    return 0
  fi

  mkdir -p "$dir"
  ip=$(ip -4 -o addr show scope global 2>/dev/null | awk '{sub(/\/.*/,"",$4); print $4; exit}')
  san="DNS:$cn"
  [ -n "$ip" ] && san="$san,IP:$ip"
  rm -f "$key" "$cert"
  openssl req -x509 -nodes -newkey rsa:3072 -sha256 -days 825 \
    -subj "/CN=$cn" -addext "subjectAltName=$san" \
    -keyout "$key" -out "$cert" >/dev/null 2>&1 || return 1
  chown root:root "$key" "$cert"
  chmod 0600 "$key"; chmod 0644 "$cert"
  log "generated a fresh local TLS certificate for $cn"
}

p45_conffiles() {
  # Packages downloaded from Ubuntu carry stock config files, but Datto's mirror ships rebuilds
  # with the same version numbers and different config files (e.g. apache2's ports.conf, whose
  # stock "Listen 80/443" duplicates device.conf's and stops Apache from binding). Apply
  # spf-datto's copy of every package config file that differs, except CONFFILE_DENY_RE.
  local src="$INSTALL_DIR/conffiles" tmp n=0 skip=0 sum f pkg cur bad_owners applied=$STATE_DIR/conffiles-applied.txt
  [ -f "$src/conffiles.tgz" ] || { log "no conffiles in bundle; skipping"; return 0; }
  bad_owners=$(tar --numeric-owner -tvzf "$src/conffiles.tgz" |
    awk '$2 != "0/0" { if (n < 5) print; n++ }')
  if [ -n "$bad_owners" ]; then
    log "refusing configuration archive with non-root ownership:"
    printf '%s\n' "$bad_owners" | tee -a "$LOG" >&2
    return 1
  fi
  tmp=$(mktemp -d)
  tar -C "$tmp" -xzf "$src/conffiles.tgz" || return 1
  mkdir -p "$BACKUP_DIR/conffiles" "$STATE_DIR"; : > "$applied"
  while IFS=$'\t' read -r sum f pkg; do
    [ -f "$tmp$f" ] || continue
    cur=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)
    [ "$cur" = "$sum" ] && continue
    if [[ "$f" =~ $CONFFILE_DENY_RE ]]; then skip=$((skip+1)); continue; fi
    if [ -e "$f" ]; then mkdir -p "$BACKUP_DIR/conffiles$(dirname "$f")"; cp -a "$f" "$BACKUP_DIR/conffiles$f"; fi
    mkdir -p "$(dirname "$f")"; cp -a "$tmp$f" "$f"
    printf '%s\t%s\n' "$f" "$pkg" >> "$applied"; n=$((n+1))
  done < "$src/manifest.tsv"
  rm -rf "$tmp"
  log "applied $n spf-datto config files ($skip withheld: identity/hardware); list in $applied"

  # Validate privileged configuration before invoking any service or helper.
  # Put the replica's original copy back if spf-datto's version does not pass.
  if grep -q '^/etc/sudoers' "$applied" && ! visudo -c >/dev/null 2>&1; then
    restore_conf $(cut -f1 "$applied" | grep '^/etc/sudoers'); log "sudoers failed visudo -c; restored"
  fi
  if grep -q '^/etc/ssh/' "$applied" && ! sshd -t >/dev/null 2>&1; then
    restore_conf $(cut -f1 "$applied" | grep '^/etc/ssh/'); log "ssh config failed sshd -t; restored"
  fi
  if grep -q '^/etc/apache2/' "$applied" && ! apache2ctl configtest >/dev/null 2>&1; then
    restore_conf $(cut -f1 "$applied" | grep '^/etc/apache2/'); log "apache config failed configtest; restored"
  fi

  # Put the Ubuntu VM's local identity and shell defaults back after appliance
  # packages/configuration have run. These are host concerns, not application
  # payload, and cloning them causes hostname lookup and interactive-shell errors.
  for f in hosts bash.bashrc; do
    [ -e "$STATE_DIR/target-base/$f" ] && cp -a "$STATE_DIR/target-base/$f" "/etc/$f"
  done

  # Telegraf was only the secondary socket owner. Apache already runs as
  # www-data, so use that group and do not retain a telemetry-only dependency.
  if [ -f /etc/php/8.1/fpm/pool.d/siris.conf ]; then
    sed -Ei 's/^([[:space:]]*listen\.group[[:space:]]*=[[:space:]]*)telegraf([[:space:]]*)$/\1www-data\2/' \
      /etc/php/8.1/fpm/pool.d/siris.conf || return 1
  fi
  rm -f /etc/default/grub.d/99-ubuntu-fips.cfg \
    /etc/init.d/falcon-sensor \
    /etc/logrotate.d/falcon-sensor \
    /etc/logrotate.d/telegraf
  rm -rf /etc/td-agent-bit

  remove_cloud_client_cert_auth
  disable_online_registration_gates || return 1
  install_offline_registration_finalizer || return 1
  generate_local_tls_certificate || return 1
  systemctl reset-failed logrotate.service 2>/dev/null || true
  systemctl start logrotate.service >/dev/null 2>&1 || return 1
  systemctl daemon-reload
  # spf-datto's firewalld.conf switches the backend (nftables -> iptables); a reload doesn't do
  # that cleanly and leaves rules half-applied until reboot, so restart instead
  grep -q '^/etc/firewalld/' "$applied" && systemctl is-active --quiet firewalld && systemctl restart firewalld
  systemctl reset-failed apache2 2>/dev/null; systemctl restart apache2 2>/dev/null
  log "apache2: $(systemctl is-active apache2); listening: $(ss -Hltn '( sport = :80 or sport = :443 )' | awk '{print $4}' | sort -u | xargs)"
  return 0
}

p50_boot() {
  if [ "$FIPS_OFF" = yes ]; then
    cat > /etc/default/grub.d/99z-match-spf-datto.cfg <<'EOF'
# The VM payload contains only the supported 6.8 HWE generic kernel.
GRUB_FLAVOUR_ORDER="generic"
GRUB_CMDLINE_LINUX_DEFAULT="$(echo "$GRUB_CMDLINE_LINUX_DEFAULT" | sed "s/ *fips=1//g")"
EOF
  fi
  update-grub >/dev/null 2>&1 || return 1
  log "default boot: $(awk '/^\tlinux/ {print $2; exit}' /boot/grub/grub.cfg), fips=1 entries: $(grep -c 'fips=1' /boot/grub/grub.cfg)"
}

purge_pruned_packages() {
  local list="$INSTALL_DIR/lists/pruned-packages.txt" installed="" removed="" package
  [ -f "$list" ] || return 0
  while IFS= read -r package; do
    case "$package" in ''|'#'*) continue ;; esac
    dpkg-query -W -f='${db:Status-Abbrev}' "$package" 2>/dev/null | grep -q '^ii' && \
      installed="$installed $package"
  done < "$list"
  [ -n "$installed" ] || return 0

  # A stale pre-sanitization install may still contain these packages. Refuse
  # the purge if apt proposes removing anything outside the reviewed list.
  removed=$(apt-get -s "${LOCAL_ONLY[@]}" purge $installed 2>/dev/null | \
    awk '/^Remv / { print $2 }')
  for package in $removed; do
    grep -Fxq "$package" "$list" || {
      log "refusing pruned-package cleanup because apt would also remove $package"
      return 1
    }
  done
  offline_run apt-get -y -q "${LOCAL_ONLY[@]}" purge $installed >/dev/null || return 1
  systemctl daemon-reload
  systemctl reset-failed >/dev/null 2>&1 || true
  log "removed stale source-appliance-only packages:$installed"
}

p60_cleanup() {
  if [ "$REMOVE_SNAPD" = yes ] && dpkg -s snapd >/dev/null 2>&1; then
    offline_run apt-get -y -q "${LOCAL_ONLY[@]}" purge snapd >/dev/null || return 1
    log "snapd purged"
  fi
  if [ "$REMOVE_CLOUD_INIT" = yes ] && dpkg -s cloud-init >/dev/null 2>&1; then
    offline_run apt-get -y -q "${LOCAL_ONLY[@]}" purge cloud-init >/dev/null || return 1
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
  [ "$ZFS_CONFIGURE" != no ] || { log "ZFS disabled in setup.conf"; return 0; }
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
      if [ "$ZFS_CONFIGURE" = auto ]; then
        log "no blank disk >= ${ZFS_MIN_GB} GB found; continuing without ZFS"
        return 0
      fi
      warn "no blank disk >= ${ZFS_MIN_GB} GB found; attach one and re-run setup.sh"
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
    zfs set overlay=on "$P/home" || return 1 # original /home stays underneath as a fallback
    zfs set mountpoint=/home "$P/home" || return 1
    rmdir /mnt/spf-newhome 2>/dev/null || true
  fi
  # Enforce this on resumed runs too. Some appliance ZFS defaults reset overlay,
  # and a populated fallback /home must not make zfs-mount.service fail at boot.
  zfs set overlay=on "$P/home" || return 1
  # Datto's boot-time ZFS policy may reset the dataset property to inherited/off.
  # Make the systemd mount operation itself overlay-safe so a populated fallback
  # /home cannot fail zfs-mount.service before the pool is mounted.
  mkdir -p /etc/systemd/system/zfs-mount.service.d
  cat > /etc/systemd/system/zfs-mount.service.d/90-spf-overlay.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/zfs mount -a -O
EOF
  systemctl daemon-reload
  zfs list "$P/home/agents"       >/dev/null 2>&1 || zfs create "$P/home/agents"
  zfs list "$P/home/configBackup" >/dev/null 2>&1 || zfs create "$P/home/configBackup"
  local home; home="$(getent passwd "$LOGIN_USER" | cut -d: -f6)"
  [ -s "$home/.ssh/authorized_keys" ] || warn "$home/.ssh/authorized_keys missing after /home move"
  zpool list -H -o name,size,health "$P" | sed 's/^/  pool: /'
}

p75_protection_engine() {
  [ "$REQUIRE_KVM" = yes ] || { log "KVM protection-engine check disabled in setup.conf"; return 0; }
  kvm_ready || { log "KVM is not available; agentless VM protection cannot run"; return 1; }
  local test_log=/var/log/spf-datto-libguestfs-test.log
  log "testing the libguestfs/KVM disk-inspection engine (log: $test_log)"
  timeout 180 libguestfs-test-tool > "$test_log" 2>&1 || {
    tail -n 40 "$test_log"
    return 1
  }
  grep -q 'TEST FINISHED OK' "$test_log" || {
    tail -n 40 "$test_log"
    return 1
  }
  install -d -m 0755 /var/lib/recovera
  touch /var/lib/recovera/libguestfs-self-test-passed
  log "libguestfs/KVM disk-inspection engine passed"
}

p76_backup_admin() {
  local helper="$INSTALL_DIR/peer/recovera-backup-admin" policy dropin firewall_dropin
  [ -f "$helper" ] || { log "Recovera backup administrator helper is missing"; return 1; }
  policy="$INSTALL_DIR/peer/recovera-sshd-policy"
  dropin="$INSTALL_DIR/peer/datto-sshd-configure-recovera.conf"
  firewall_dropin="$INSTALL_DIR/peer/datto-firewall-share-sync-recovera.conf"
  [ -f "$policy" ] && [ -f "$dropin" ] && [ -f "$firewall_dropin" ] || {
    log "Recovera service policy hook is missing"
    return 1
  }
  install -m 0755 "$helper" /usr/local/sbin/recovera-backup-admin || return 1
  install -m 0755 "$policy" /usr/local/sbin/recovera-sshd-policy || return 1
  install -d -m 0755 /etc/systemd/system/datto-sshd-configure.service.d || return 1
  install -m 0644 "$dropin" \
    /etc/systemd/system/datto-sshd-configure.service.d/recovera.conf || return 1
  install -d -m 0755 /etc/systemd/system/datto-firewall-share-sync.service.d || return 1
  install -m 0644 "$firewall_dropin" \
    /etc/systemd/system/datto-firewall-share-sync.service.d/recovera.conf || return 1
  /usr/local/sbin/recovera-backup-admin install || return 1
  chown root:root /etc/recovera/backup-admin.json || return 1
  chmod 0600 /etc/recovera/backup-admin.json || return 1
  # Allow password SSH only for the appliance recovery administrator. Ubuntu's
  # cloud-image drop-in disables it globally, while peer transport remains
  # key-only under its own Match block.
  # The appliance package may replace sshd_config with a file that has no
  # Include directive at all. In that case every policy below would be ignored,
  # leaving OpenSSH's default PasswordAuthentication=yes in effect globally.
  systemctl daemon-reload || return 1
  /usr/local/sbin/recovera-sshd-policy --validate || return 1
  systemctl reload ssh || return 1
  log "backup-admin local appliance account is ready; retrieve it from Appliance Access or with: sudo recovera-backup-admin show"
}

ensure_recovera_device_id() {
  python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

target = Path('/datto/config/deviceID')
try:
    current = int(target.read_text().strip())
except (FileNotFoundError, ValueError):
    current = 0
if current > 0:
    raise SystemExit(0)

peer_config = Path('/etc/recovera-peer/config.json')
value = 0
try:
    value = int(json.loads(peer_config.read_text()).get('numeric_id', 0))
except (FileNotFoundError, ValueError, json.JSONDecodeError):
    pass
if value < 1:
    machine_id = Path('/etc/machine-id').read_bytes().strip()
    value = 1_000_000_000 + int.from_bytes(hashlib.sha256(machine_id).digest()[:8], 'big') % 8_000_000_000

target.parent.mkdir(parents=True, exist_ok=True)
temporary = target.with_name('.deviceID.recovera')
temporary.write_text(str(value) + '\n')
temporary.chmod(0o644)
os.replace(temporary, target)
PY
}

p77_recovera_branding() {
  [ -f "$INSTALL_DIR/branding/apply-branding.py" ] || { log "Recovera branding script is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/recovera-logo.png" ] || { log "Recovera logo is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/recovera-ascii.logo" ] || { log "Recovera console logo is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/recovera-motd" ] || { log "Recovera login banner is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/RecoveraTargetController.php" ] || { log "Recovera off-site target controller is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/recovera-access.html.twig" ] || { log "Recovera appliance-access page is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/RecoveraAccess.js" ] || { log "Recovera appliance-access script is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/RecoveraProtectSystem.js" ] || { log "Recovera protection-wizard bridge is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/RecoveraProtectStatus.js" ] || { log "Recovera native replication-status bridge is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/apply-peer-ui.py" ] || { log "Recovera native peer-control installer is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/RecoveraRecoveryPoints.js" ] || { log "Recovera recovery-point bridge is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/RecoveraHome.js" ] || { log "Recovera home-page bridge is missing"; return 1; }
  ensure_recovera_device_id || return 1
  python3 "$INSTALL_DIR/branding/apply-branding.py" \
    "$INSTALL_DIR/branding/recovera-logo.png" || return 1
  python3 "$INSTALL_DIR/branding/apply-peer-ui.py" || return 1
  install -d -m 0755 /usr/local/share/recovera || return 1
  install -m 0644 "$INSTALL_DIR/branding/recovera-ascii.logo" \
    /usr/local/share/recovera/recovera-ascii.logo || return 1
  if [ -d /usr/lib/datto/statusshell/logo ]; then
    rm -f /usr/lib/datto/statusshell/logo/*.logo || return 1
    install -m 0644 "$INSTALL_DIR/branding/recovera-ascii.logo" \
      /usr/lib/datto/statusshell/logo/0.logo || return 1
  fi
  if [ -e /etc/update-motd.d/25-datto ]; then
    chmod a-x /etc/update-motd.d/25-datto || return 1
  fi
  install -m 0755 "$INSTALL_DIR/branding/recovera-motd" \
    /etc/update-motd.d/25-recovera || return 1
  systemctl restart php8.1-fpm >/dev/null 2>&1 || return 1
  log "Recovera WebUI, console, and login branding installed"
}

p78_peer_replication() {
  [ "$PEER_REPLICATION" = yes ] || { log "peer replication disabled in setup.conf"; return 0; }
  [ -f "$INSTALL_DIR/peer/recovera-peer" ] || { log "peer replication payload is missing"; return 1; }
  zpool list -H "$ZFS_POOL" >/dev/null 2>&1 || {
    warn "peer replication needs ZFS pool $ZFS_POOL; attach storage and re-run setup"
    return 2
  }

  systemctl disable --now backops-peer.service backops-peer-sync.timer >/dev/null 2>&1 || true
  if id backops-repl >/dev/null 2>&1 && ! id recovera-repl >/dev/null 2>&1; then
    usermod -l recovera-repl -d /var/lib/recovera-peer -m backops-repl || return 1
    if getent group backops-repl >/dev/null 2>&1; then
      groupmod -n recovera-repl backops-repl || return 1
    fi
  fi
  if [ -d /etc/backops-peer ] && [ ! -e /etc/recovera-peer ]; then
    mv /etc/backops-peer /etc/recovera-peer || return 1
  fi
  if [ -d /var/lib/backops-peer ] && [ ! -e /var/lib/recovera-peer ]; then
    mv /var/lib/backops-peer /var/lib/recovera-peer || return 1
  fi

  getent group remote-users >/dev/null || groupadd --system remote-users
  if ! id recovera-repl >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/recovera-peer --shell /bin/bash recovera-repl || return 1
  fi
  usermod -aG remote-users recovera-repl || return 1
  passwd -l recovera-repl >/dev/null 2>&1 || true

  [ -f "$INSTALL_DIR/peer/recovera-auth.php" ] || { log "Recovera authentication helper is missing"; return 1; }
  [ -f "$INSTALL_DIR/branding/recovera-logo.png" ] || { log "Recovera logo is missing"; return 1; }
  install -m 0755 "$INSTALL_DIR/peer/recovera-peer" /usr/local/sbin/recovera-peer
  install -m 0644 "$INSTALL_DIR/peer/recovera-peer.service" /etc/systemd/system/recovera-peer.service
  install -m 0644 "$INSTALL_DIR/peer/recovera-peer-sync.service" /etc/systemd/system/recovera-peer-sync.service
  install -m 0644 "$INSTALL_DIR/peer/recovera-peer-sync.timer" /etc/systemd/system/recovera-peer-sync.timer
  install -m 0644 "$INSTALL_DIR/peer/recovera-peer-gateway.conf" /etc/apache2/conf-available/recovera-peer-gateway.conf
  install -m 0644 "$INSTALL_DIR/peer/sshd-recovera-peer.conf" /etc/ssh/sshd_config.d/91-recovera-peer.conf
  install -m 0440 "$INSTALL_DIR/peer/sudoers-recovera-peer" /etc/sudoers.d/recovera-peer
  install -d -m 0755 /usr/local/lib/recovera /usr/local/share/recovera
  install -m 0644 "$INSTALL_DIR/peer/recovera-auth.php" /usr/local/lib/recovera/authenticate.php
  install -m 0644 "$INSTALL_DIR/branding/recovera-logo.png" /usr/local/share/recovera/recovera-logo.png

  if [ -f /var/lib/recovera-peer/.ssh/authorized_keys ]; then
    sed -i 's|/usr/local/sbin/backops-peer|/usr/local/sbin/recovera-peer|g; s/backops-source=/recovera-source=/g' \
      /var/lib/recovera-peer/.ssh/authorized_keys || return 1
  fi
  rm -f /etc/recovera-peer/admin.token /usr/local/sbin/backops-peer \
    /etc/systemd/system/backops-peer.service /etc/systemd/system/backops-peer-sync.service \
    /etc/systemd/system/backops-peer-sync.timer /etc/ssh/sshd_config.d/91-backops-peer.conf \
    /etc/sudoers.d/backops-peer

  visudo -cf /etc/sudoers.d/recovera-peer >/dev/null || return 1
  local sshd_active sshd_backup
  sshd_active=$(readlink -f /etc/ssh/sshd_config)
  sshd_backup="$BACKUP_DIR/$(basename "$sshd_active").before-recovera-peer"
  if ! grep -qF 'Include /etc/ssh/sshd_config.d/*.conf' "$sshd_active"; then
    mkdir -p "$BACKUP_DIR"
    cp -a "$sshd_active" "$sshd_backup" || return 1
    if grep -q '^Match ' "$sshd_active"; then
      sed -i '0,/^Match /s|^Match |Include /etc/ssh/sshd_config.d/*.conf\nMatch |' "$sshd_active"
    else
      printf '\nInclude /etc/ssh/sshd_config.d/*.conf\n' >> "$sshd_active"
    fi
  fi
  if ! sshd -t; then
    [ -f "$sshd_backup" ] && cp -a "$sshd_backup" "$sshd_active"
    log "peer SSH configuration failed validation and was rolled back"
    return 1
  fi
  /usr/local/sbin/recovera-peer init || return 1
  python3 - <<PY || return 1
import json
from pathlib import Path
p = Path('/etc/recovera-peer/config.json')
c = json.loads(p.read_text())
c.pop('port', None)
c.pop('listen', None)
c['pool'] = '$ZFS_POOL'
c['source_root'] = '$ZFS_POOL/home/agents'
device_id = Path('/datto/config/deviceID')
local_numeric_id = int(device_id.read_text().strip())
if local_numeric_id < 1:
    raise ValueError('invalid local Recovera device ID')
c['numeric_id'] = local_numeric_id
p.write_text(json.dumps(c, indent=2, sort_keys=True) + '\n')
p.chmod(0o600)
PY

  rm -f /etc/recovera-peer/tls.crt /etc/recovera-peer/tls.key
  a2enmod proxy proxy_http >/dev/null || return 1
  a2enconf recovera-peer-gateway >/dev/null || return 1
  apache2ctl configtest >/dev/null || return 1
  if systemctl is-active --quiet firewalld && firewall-cmd --get-zones 2>/dev/null | grep -qw datto; then
    firewall-cmd --zone=datto --remove-port="9443/tcp" >/dev/null 2>&1 || true
    firewall-cmd --permanent --zone=datto --remove-port="9443/tcp" >/dev/null 2>&1 || true
  fi
  systemctl daemon-reload
  systemctl restart ssh.service || return 1
  systemctl enable recovera-peer.service recovera-peer-sync.timer >/dev/null || return 1
  systemctl restart recovera-peer.service recovera-peer-sync.timer || return 1
  systemctl reload apache2 || return 1
  log "Recovera pairing is available through HTTPS 443; replication uses restricted SSH and the internal API uses a Unix socket"
}

p79_image_updater() {
  local source="$INSTALL_DIR/upgrade" baseline
  [ -x "$source/recovera-upgrade" ] || { log "Recovera updater is missing"; return 1; }
  [ -f "$source/keys/recovera-release-signers" ] || { log "Recovera release signer list is missing"; return 1; }
  install -d -m 0755 /etc/recovera /usr/local/lib/recovera-upgrade \
    /usr/local/share/recovera-upgrade /host/recovera || return 1
  install -m 0755 "$source/recovera-upgrade" /usr/local/sbin/recovera-upgrade || return 1
  install -m 0755 "$source/recovera-image-boot" \
    /usr/local/lib/recovera-upgrade/recovera-image-boot || return 1
  install -m 0755 "$source/recovera-migrate-config" \
    /usr/local/lib/recovera-upgrade/recovera-migrate-config || return 1
  install -m 0644 "$source/keys/recovera-release-signers" \
    /usr/local/share/recovera-upgrade/release-signers || return 1
  if [ ! -f /etc/recovera/upgrade.conf ]; then
    install -m 0600 "$source/recovera-upgrade.conf" /etc/recovera/upgrade.conf || return 1
  fi
  install -m 0644 "$source/recovera-upgrade-check.service" \
    /etc/systemd/system/recovera-upgrade-check.service || return 1
  install -m 0644 "$source/recovera-upgrade-check.timer" \
    /etc/systemd/system/recovera-upgrade-check.timer || return 1
  install -m 0644 "$source/recovera-upgrade-validate.service" \
    /etc/systemd/system/recovera-upgrade-validate.service || return 1
  if [ -f /etc/recovera/image-layout.json ]; then
    install -m 0755 "$source/07_recovera_images" /etc/grub.d/07_recovera_images || return 1
    install -m 0644 "$source/99_recovera_images.cfg" /etc/default/grub.d/99_recovera_images.cfg || return 1
    install -m 0755 "$source/initramfs-hook-recovera" /etc/initramfs-tools/hooks/recovera-image || return 1
    install -m 0755 "$source/initramfs-local-top-recovera" /etc/initramfs-tools/scripts/local-top/recovera-image || return 1
    install -m 0755 "$source/initramfs-local-bottom-recovera" /etc/initramfs-tools/scripts/local-bottom/recovera-image || return 1
    update-initramfs -u || return 1
    update-grub || return 1
  fi
  systemctl daemon-reload || return 1
  systemctl enable recovera-upgrade-check.timer recovera-upgrade-validate.service >/dev/null || return 1
  baseline=$(find "$INSTALL_DIR/debs" -maxdepth 1 -type f -name 'recovera-appliance_*.deb' -print -quit 2>/dev/null)
  if [ -n "$baseline" ] && ! dpkg-query -W -f='${db:Status-Abbrev}' recovera-appliance 2>/dev/null | grep -q '^ii'; then
    dpkg -i "$baseline" >/dev/null || return 1
    log "installed Recovera application package rollback baseline"
  fi
  log "signed Recovera package updater installed; full-image activation remains disabled until an image-layout marker is provisioned"
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
  local ifc mac cidr gw dns zone ipv4 address_line
  ifc="${NET_IFACE:-$(primary_iface)}"
  [ -n "$ifc" ] && [ -e "/sys/class/net/$ifc" ] || { log "cannot find the primary interface"; return 1; }
  mac=$(cat "/sys/class/net/$ifc/address")
  cidr=$(ip -4 -o addr show dev "$ifc" | awk '{print $4; exit}')
  gw="${NET_GATEWAY:-$(ip route show default dev "$ifc" | awk '{print $3; exit}')}"
  dns="${NET_DNS:-$(resolvectl dns "$ifc" 2>/dev/null | cut -d: -f2- | xargs)}"
  [ "$gw" = none ] && gw=""
  [ "$dns" = none ] && dns=""
  dns="${dns:-$gw}"
  case "$NET_IP" in
    dhcp)    ipv4=$'method=auto' ;;
    current) [ -n "$cidr" ] || { log "no current IPv4 on $ifc"; return 1; }
             address_line="address1=$cidr${gw:+,$gw}"
             ipv4="method=manual"$'\n'"$address_line"
             [ -z "$dns" ] || ipv4+=$'\n'"dns=$(echo "$dns" | tr ' ' ';');" ;;
    *)       address_line="address1=$NET_IP${gw:+,$gw}"
             ipv4="method=manual"$'\n'"$address_line"
             [ -z "$dns" ] || ipv4+=$'\n'"dns=$(echo "$dns" | tr ' ' ';');" ;;
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
  # Package service starts are suppressed during the offline install, so NetworkManager
  # may be enabled without running yet. Start it before the first nmcli operation.
  systemctl enable --now NetworkManager.service >/dev/null 2>&1 || {
    log "NetworkManager did not start; reverting to the previous netplan config"
    net_revert "$ifc"
    return 2
  }
  ip addr flush dev "$ifc"
  nmcli connection reload
  nmcli connection up "$ifc" >/dev/null 2>&1
  nmcli connection up br0 >/dev/null 2>&1

  local ok="" i
  for i in $(seq 1 45); do
    if ip -4 -o addr show dev br0 | grep -q inet; then
      if [ -z "$gw" ] || ping -c1 -W2 "$gw" >/dev/null 2>&1; then ok=1; break; fi
    fi
    sleep 2
  done
  if [ -z "$ok" ]; then
    log "br0 did not become usable${gw:+ or reach gateway $gw}; reverting to the previous netplan config"
    net_revert "$ifc"
    warn "network left on netplan/networkd; see $LOG"
    return 2
  fi
  if [ -n "$gw" ]; then
    log "br0 up: $(ip -4 -o addr show dev br0 | awk '{print $4}'), gateway $gw reachable"
  else
    log "br0 up: $(ip -4 -o addr show dev br0 | awk '{print $4}'), no gateway configured"
  fi
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
  offline_run apt-get -qq "${LOCAL_ONLY[@]}" update 2>/dev/null || true
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
  local fails=0 failed unexpected cyc want have sshlink mem_kb mem_gb
  check() { if eval "$2" >/dev/null 2>&1; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
  echo "spf-datto replica verification $(ts) on $(hostname)"
  echo "  kernel $(uname -r), fips_enabled=$(cat /proc/sys/crypto/fips_enabled 2>/dev/null || echo n/a)"
  want=$(wc -l < "$INSTALL_DIR/lists/all-packages-versions.txt")
  have=$(comm -12 <(sort "$INSTALL_DIR/lists/all-packages-versions.txt") <(dpkg-query -W -f='${Package}=${Version}\n' | sort) | wc -l)
  cyc=$(journalctl -b -o cat 2>/dev/null | grep -c 'Found ordering cycle')
  sshlink=$(readlink /etc/ssh/sshd_config)
  mem_kb=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
  mem_gb=$(( (mem_kb + 1024*1024 - 1) / 1024 / 1024 ))
  check "packages at spf-datto versions: $have/$want"      "[ $have -eq $want ]"
  check "dpkg --audit clean"                               "[ -z \"\$(dpkg --audit)\" ]"
  check "no systemd ordering cycles this boot ($cyc)"      "[ $cyc -eq 0 ]"
  check "sshd active, config -> ${sshlink:-regular file}"  "systemctl is-active ssh"
  check "$LOGIN_USER in remote-users"                      "id -nG $LOGIN_USER | grep -qw remote-users"
  check "backup-admin has persistent appliance access"     "id -nG backup-admin | grep -qw remote-users && id -nG backup-admin | grep -qw sudo && test -s /etc/recovera/backup-admin.json && test \"\$(stat -c %a /etc/recovera/backup-admin.json)\" = 600"
  check "password SSH is enabled only for backup-admin"     "[ \"\$(sshd -T -C user=backup-admin,host=localhost,addr=127.0.0.1 | awk '/^passwordauthentication /{print \$2}')\" = yes ] && [ \"\$(sshd -T -C user=root,host=localhost,addr=127.0.0.1 | awk '/^passwordauthentication /{print \$2}')\" = no ]"
  check "snapctl works"                                    "snapctl --version"
  check "SpeedSync recognizes the local Recovera device"   "timeout 10 speedsync version"
  check "php8.1-fpm active (/run/php)"                     "systemctl is-active php8.1-fpm"
  # libvirtd is socket-activated with --timeout 120, so "inactive" is normal; ask it instead
  check "libvirt answers (virsh version)"                  "virsh -c qemu:///system version"
  check "RAM for recovery verification: ${mem_gb} GB >= ${MIN_RAM_GB} GB" \
                                                            "[ $mem_gb -ge $MIN_RAM_GB ]"
  if [ "$REQUIRE_KVM" = yes ]; then
    check "hardware virtualization available (/dev/kvm)"  "kvm_ready"
    check "libguestfs/KVM self-test passed"                "test -f /var/lib/recovera/libguestfs-self-test-passed || grep -q 'TEST FINISHED OK' /var/log/spf-datto-libguestfs-test.log"
  fi
  if [ "$ZFS_CONFIGURE" != no ] && zpool list -H "$ZFS_POOL" >/dev/null 2>&1; then
    check "$ZFS_POOL ONLINE"                               "[ \"\$(zpool list -H -o health $ZFS_POOL)\" = ONLINE ]"
    check "zfs-mount active"                               "systemctl is-active zfs-mount"
    [ "$ZFS_MOVE_HOME" = yes ] && check "/home on $ZFS_POOL/home" "[ \"\$(findmnt -no SOURCE /home)\" = $ZFS_POOL/home ]"
  else
    echo "  --    ZFS pool not present"
  fi
  if [ "$NET_CONFIGURE" = yes ]; then
    check "br0 managed by NetworkManager: $(ip -4 -o addr show dev br0 2>/dev/null | awk '{print $4}')" "nmcli -t -f DEVICE,STATE dev | grep -q '^br0:connected'"
  fi
  if [ "$PEER_REPLICATION" = yes ]; then
    local peer_code gateway_code peer_socket=/run/recovera-peer/http.sock
    peer_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --unix-socket "$peer_socket" "http://localhost/v1/info" 2>/dev/null)
    gateway_code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1/recovera-peer/info" 2>/dev/null)
    check "peer replication service active"                 "systemctl is-active recovera-peer.service"
    check "peer scheduler enabled"                          "systemctl is-enabled recovera-peer-sync.timer"
    check "peer API Unix socket answers (HTTP $peer_code)"     "[ '$peer_code' = 200 ]"
    check "pairing gateway on HTTPS 443 answers (HTTP $gateway_code)" "[ '$gateway_code' = 200 ]"
    check "peer API socket is restricted to root:www-data" "[ -S '$peer_socket' ] && [ \"\$(stat -c '%U:%G:%a' '$peer_socket')\" = root:www-data:770 ]"
    check "legacy TCP 9443 listener is absent" "! ss -Hltn '( sport = :9443 )' | grep -q ."
  fi
  # Apache / Datto web UI
  local dup ip code
  dup=$(grep -rhoE '^\s*Listen\s+\S+' /etc/apache2/ports.conf /etc/apache2/sites-enabled/ /etc/apache2/conf-enabled/ 2>/dev/null \
        | awk '{print $2}' | sed -E 's/.*://' | sort | uniq -d | xargs)
  ip=$(ip -4 -o addr show dev br0 2>/dev/null | awk '{sub(/\/.*/,"",$4); print $4; exit}')
  [ -n "$ip" ] || ip=$(ip -4 -o addr show dev "$(primary_iface)" 2>/dev/null | awk '{sub(/\/.*/,"",$4); print $4; exit}')
  for _ in 1 2 3 4; do   # the first request after an Apache/PHP restart can be slow
    code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://$ip/" 2>/dev/null)
    case "$code" in 200|301|302|303) break ;; esac; sleep 5
  done
  check "apache2 active"                                   "systemctl is-active apache2"
  check "no duplicate Apache Listen ports${dup:+ (duplicated: $dup)}" "[ -z \"$dup\" ]"
  check "apache bound to :80 and :443"                     "ss -Hltn '( sport = :80 )' | grep -q . && ss -Hltn '( sport = :443 )' | grep -q ."
  check "web UI https://$ip/ answers (HTTP $code)"         "case '$code' in 200|301|302|303) true;; *) false;; esac"
  [ "$NET_CONFIGURE" = yes ] || EXPECTED_FAILED="$EXPECTED_FAILED NetworkManager-wait-online.service datto-network-repair.service"
  if [ "$ZFS_CONFIGURE" = no ] || ! zpool list -H "$ZFS_POOL" >/dev/null 2>&1; then
    # These jobs query homePool and fail by design on a VM intentionally
    # installed without a second data disk. They become required as soon as
    # the configured pool exists.
    EXPECTED_FAILED="$EXPECTED_FAILED datto-zfs-cache-update.service datto-zfs-check.service datto-metrics-statistics-collect.service"
  fi
  failed=$(systemctl --failed --no-legend --plain | awk '{print $1}')
  unexpected=$(for u in $failed; do echo " $EXPECTED_FAILED " | grep -q " $u " || echo "$u"; done)
  echo "  expected failures for this VM profile: $(for u in $failed; do echo " $EXPECTED_FAILED " | grep -q " $u " && echo -n "$u "; done)"
  if [ -n "$unexpected" ]; then echo "  FAIL  unexpected failed units: $(echo $unexpected)"; fails=$((fails+1)); else echo "  ok    no unexpected failed units"; fi
  echo "RESULT: $([ $fails -eq 0 ] && echo PASS || echo "$fails check(s) failed")"
  return $fails
}

# ----------------------------------------------------------------------------- main
run_all() {
  load_conf
  validate_conf
  log "spf-datto replica setup starting on $(hostname) ($(. /etc/os-release; echo "$PRETTY_NAME"), kernel $(uname -r))"
  log "config: login=$LOGIN_USER offline=$OFFLINE_MODE net=$NET_CONFIGURE/$NET_IP zfs=$ZFS_CONFIGURE/$ZFS_DISK fips_off=$FIPS_OFF freeze=$APT_FREEZE"
  phase p10 "local apt repo from $INSTALL_DIR/debs"           p10_repo
  phase p20 "dry run"                                         p20_dryrun
  phase p30 "SSH guard (remote-users) and cloud-init network" p30_prep
  phase p40 "install all packages at exact versions"          p40_install
  phase p42 "remove stale source-appliance-only packages"      purge_pruned_packages
  phase p45 "spf-datto config files (apache, sudoers, audit, ...)" p45_conffiles
  phase p50 "boot config (FIPS off)"                          p50_boot
  phase p60 "remove snapd + cloud-init, restore snapctl"      p60_cleanup
  phase p70 "ZFS $ZFS_POOL"                                   p70_zfs
  phase p75 "libguestfs/KVM protection engine"                 p75_protection_engine
  phase p76 "persistent backup administrator"                  p76_backup_admin
  phase p77 "Recovera application branding"                    p77_recovera_branding
  phase p78 "offline appliance-to-appliance replication"       p78_peer_replication
  phase p79 "signed package and image upgrade client"           p79_image_updater
  phase p80 "NetworkManager bridge br0"                       p80_network
  phase p85 "apt sources"                                     p85_apt
  log "== p90: post-boot verification timer (re-armed every run)"
  p90_verify_timer
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
      # The timer already waits three minutes after boot. Polling
      # is-system-running here deadlocks on this verification job itself.
      verify > "$VERIFY_LOG" 2>&1; rc=$?
      systemctl disable spf-datto-verify.timer >/dev/null 2>&1
      exit $rc
    fi
    verify ;;
  repair-registration)
    [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
    install_offline_registration_finalizer
    echo "offline registration finalizer repaired" ;;
  install-peer)
    [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
    load_conf; validate_conf; p76_backup_admin; p77_recovera_branding; p78_peer_replication
    echo "peer replication service installed" ;;
  install-updater)
    [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
    p79_image_updater || exit 1
    echo "signed image updater installed" ;;
  apply-branding)
    [ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
    p77_recovera_branding
    echo "Recovera branding applied" ;;
  *) sed -n '2,15p' "$SELF"; exit 1 ;;
esac
