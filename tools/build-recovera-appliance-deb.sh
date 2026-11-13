#!/bin/bash
# Package Recovera-owned services, WebUI integration, branding, and updater.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=
OUTPUT=

usage() { echo "usage: $0 --version DEBIAN_VERSION --output DIR" >&2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) VERSION=$2; shift 2;;
    --output) OUTPUT=$2; shift 2;;
    *) usage; exit 2;;
  esac
done
[ -n "$VERSION" ] && [ -n "$OUTPUT" ] || { usage; exit 2; }
dpkg --validate-version "$VERSION" >/dev/null 2>&1 || { echo "invalid Debian version: $VERSION" >&2; exit 2; }
for command in dpkg-deb install python3; do command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }; done

work=$(mktemp -d "${TMPDIR:-/tmp}/recovera-appliance-deb.XXXXXX")
trap 'rm -rf "$work"' EXIT
stage=$work/stage
mkdir -p "$stage/DEBIAN" "$stage/usr/local/sbin" "$stage/usr/local/lib/recovera" \
  "$stage/usr/local/lib/recovera-upgrade" "$stage/usr/local/share/recovera-upgrade" \
  "$stage/usr/local/share/recovera" "$stage/usr/local/share/recovera/isolation" \
  "$stage/usr/share/recovera/agents/linux" \
  "$stage/usr/lib/recovera/branding" \
  "$stage/usr/share/recovera/defaults" "$stage/usr/share/recovera/setup" \
  "$stage/etc/systemd/system" \
  "$stage/etc/apache2/conf-available" "$stage/etc/ssh/sshd_config.d" \
  "$stage/etc/sudoers.d" "$stage/etc/update-motd.d" \
  "$stage/etc/sysctl.d" "$stage/etc/modules-load.d" \
  "$stage/etc/systemd/system/datto-sshd-configure.service.d" \
  "$stage/etc/systemd/system/datto-firewall-share-sync.service.d"

cat > "$stage/DEBIAN/control" <<EOF
Package: recovera-appliance
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Maintainer: Recovera Project <noreply@recovera.local>
Depends: python3, openssh-client, openssh-server, sudo, apache2, php8.1-fpm | php8.3-fpm, xz-utils, zfsutils-linux, gdisk, cloud-guest-utils, parted, util-linux, udev
Description: Recovera appliance control plane
 Recovera branding, private replication, administrator integration, and signed
 package/image upgrade client for an already provisioned Recovera appliance.
EOF

install -m 0755 "$ROOT/setup/peer/recovera-peer" "$stage/usr/local/sbin/recovera-peer"
install -m 0755 "$ROOT/setup/peer/recovera-backup-admin" "$stage/usr/local/sbin/recovera-backup-admin"
install -m 0755 "$ROOT/setup/peer/recovera-sshd-policy" "$stage/usr/local/sbin/recovera-sshd-policy"
install -m 0644 "$ROOT/setup/peer/recovera-auth.php" "$stage/usr/local/lib/recovera/authenticate.php"
install -m 0644 "$ROOT/setup/peer/recovera-peer.service" "$stage/etc/systemd/system/"
install -m 0644 "$ROOT/setup/peer/recovera-peer-sync.service" "$stage/etc/systemd/system/"
install -m 0644 "$ROOT/setup/peer/recovera-peer-sync.timer" "$stage/etc/systemd/system/"
install -m 0644 "$ROOT/setup/peer/recovera-peer-gateway.conf" "$stage/etc/apache2/conf-available/"
install -m 0644 "$ROOT/setup/peer/sshd-recovera-peer.conf" "$stage/etc/ssh/sshd_config.d/91-recovera-peer.conf"
install -m 0644 "$ROOT/setup/peer/sysctl-recovera-replication.conf" "$stage/etc/sysctl.d/90-recovera-replication.conf"
install -m 0644 "$ROOT/setup/peer/modules-load-recovera-bbr.conf" "$stage/etc/modules-load.d/recovera-bbr.conf"
install -m 0440 "$ROOT/setup/peer/sudoers-recovera-peer" "$stage/etc/sudoers.d/recovera-peer"
install -m 0644 "$ROOT/setup/peer/recovera-sshd-service.conf" \
  "$stage/etc/systemd/system/datto-sshd-configure.service.d/recovera.conf"
install -m 0644 "$ROOT/setup/peer/recovera-firewall-service.conf" \
  "$stage/etc/systemd/system/datto-firewall-share-sync.service.d/recovera.conf"

cp -a "$ROOT/setup/branding/." "$stage/usr/lib/recovera/branding/"
install -m 0644 "$ROOT/setup/branding/recovera-logo.png" "$stage/usr/local/share/recovera/recovera-logo.png"
install -m 0644 "$ROOT/setup/branding/recovera-ascii.logo" "$stage/usr/local/share/recovera/recovera-ascii.logo"
install -m 0644 "$ROOT/VERSION" "$stage/usr/local/share/recovera/VERSION"
install -m 0755 "$ROOT/setup/branding/recovera-motd" "$stage/etc/update-motd.d/25-recovera"
install -m 0755 "$ROOT/setup/migrate-layout.sh" "$stage/usr/local/lib/recovera/migrate-layout"
install -m 0755 "$ROOT/setup/setup.sh" "$stage/usr/share/recovera/setup/setup.sh"
install -m 0755 "$ROOT/setup/migrate-layout.sh" "$stage/usr/share/recovera/setup/migrate-layout.sh"
install -m 0644 "$ROOT/setup/README.txt" "$stage/usr/share/recovera/setup/README.txt"
install -m 0644 "$ROOT/setup/recovera-dnsmasq.conf" \
  "$stage/usr/share/recovera/setup/recovera-dnsmasq.conf"
install -m 0644 "$ROOT/setup/target-recovera.conf" \
  "$stage/usr/share/recovera/setup/target-recovera.conf"
for file in install-recovera-agent.sh install-recovera-agent-transfer.sh \
            datto-cow-reserve-fix.sh recovera-agent-transfer; do
  install -m 0755 "$ROOT/agents/linux/$file" "$stage/usr/share/recovera/agents/linux/$file"
done
for file in datto-cow-reserve-fix.service recovera-agent-transfer.service; do
  install -m 0644 "$ROOT/agents/linux/$file" "$stage/usr/share/recovera/agents/linux/$file"
done

install -m 0755 "$ROOT/upgrade/recovera-upgrade" "$stage/usr/local/sbin/recovera-upgrade"
install -m 0755 "$ROOT/upgrade/recovera-upgrade-schedule" "$stage/usr/local/sbin/recovera-upgrade-schedule"
install -m 0755 "$ROOT/upgrade/recovera-image-boot" "$stage/usr/local/lib/recovera-upgrade/"
install -m 0755 "$ROOT/upgrade/recovera-migrate-config" "$stage/usr/local/lib/recovera-upgrade/"
install -m 0644 "$ROOT/upgrade/keys/recovera-release-signers" "$stage/usr/local/share/recovera-upgrade/release-signers"
# Installed into /etc only by `recovera-upgrade prepare-image-layout`.
install -m 0644 "$ROOT/upgrade/07_recovera_images" "$stage/usr/local/share/recovera-upgrade/07_recovera_images"
install -m 0644 "$ROOT/upgrade/99_recovera_images.cfg" "$stage/usr/local/share/recovera-upgrade/99_recovera_images.cfg"
install -m 0644 "$ROOT/upgrade/recovera-upgrade.conf" "$stage/usr/share/recovera/defaults/upgrade.conf"
install -m 0644 "$ROOT/upgrade/recovera-upgrade-check.service" "$stage/etc/systemd/system/"
install -m 0644 "$ROOT/upgrade/recovera-upgrade-check.timer" "$stage/etc/systemd/system/"
install -m 0644 "$ROOT/upgrade/recovera-upgrade-validate.service" "$stage/etc/systemd/system/"
install -m 0755 "$ROOT/setup/isolation/recovera-cloud-isolation" "$stage/usr/local/sbin/"
install -m 0644 "$ROOT/setup/isolation/cloud-units.txt" "$stage/usr/local/share/recovera/isolation/"
install -m 0644 "$ROOT/setup/isolation/cloud-hosts.txt" "$stage/usr/local/share/recovera/isolation/"
install -m 0644 "$ROOT/setup/isolation/recovera-cloud-isolation.service" "$stage/etc/systemd/system/"

cat > "$stage/DEBIAN/preinst" <<'PREINST'
#!/bin/sh
set -e
# dpkg unpacks payload files before postinst runs.  Some source appliances do
# not retain these vendor service drop-in directories, so ensure their parents
# exist before dpkg creates the new conffiles within them.
install -d -m 0755 \
  /usr/local/sbin \
  /usr/local/lib/recovera \
  /usr/local/lib/recovera-upgrade \
  /usr/local/share/recovera-upgrade \
  /usr/local/share/recovera \
  /usr/local/share/recovera/isolation \
  /usr/lib/recovera/branding \
  /usr/share/recovera/defaults \
  /etc/systemd/system \
  /etc/systemd/system/datto-sshd-configure.service.d \
  /etc/systemd/system/datto-firewall-share-sync.service.d \
  /etc/apache2/conf-available \
  /etc/ssh/sshd_config.d \
  /etc/sudoers.d \
  /etc/update-motd.d
exit 0
PREINST
chmod 0755 "$stage/DEBIAN/preinst"

cat > "$stage/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
[ "$1" = configure ] || exit 0
/usr/local/lib/recovera/migrate-layout
if [ -d /opt/recovera ]; then
  install -m 0755 /usr/share/recovera/setup/setup.sh /opt/recovera/setup.sh
  install -m 0755 /usr/share/recovera/setup/migrate-layout.sh /opt/recovera/migrate-layout.sh
  install -m 0644 /usr/share/recovera/setup/README.txt /opt/recovera/README.txt
  install -m 0644 /usr/share/recovera/setup/recovera-dnsmasq.conf /opt/recovera/recovera-dnsmasq.conf
  install -m 0644 /usr/share/recovera/setup/target-recovera.conf /opt/recovera/target-recovera.conf
fi
. /etc/os-release
if [ "${VERSION_ID:-}" = 24.04 ]; then
  # Ubuntu 24.04 runtime fixes: dnsmasq beside systemd-resolved, and the target
  # (iSCSI) service loading target_core_mod itself. They take effect when those
  # services next start; an update never restarts target.service, because
  # stopping it clears the iSCSI targets of a running restore.
  install -d -m 0755 /etc/dnsmasq.d /etc/systemd/system/target.service.d
  install -m 0644 /usr/share/recovera/setup/recovera-dnsmasq.conf /etc/dnsmasq.d/recovera.conf
  install -m 0644 /usr/share/recovera/setup/target-recovera.conf \
    /etc/systemd/system/target.service.d/zz-recovera.conf
  rm -f /etc/systemd/system/target.service.d/recovera.conf
fi
install -d -m 0755 /etc/recovera /var/cache/recovera-upgrade/packages /var/lib/recovera-upgrade/transactions
if [ ! -f /etc/recovera/upgrade.conf ]; then
  install -m 0600 /usr/share/recovera/defaults/upgrade.conf /etc/recovera/upgrade.conf
fi
# Existing configurations predate the update gateway. Add it (it is used once a
# gateway access token is installed; until then GitHub remains the source) and
# the opt-in operating-system upgrade channel. Explicit values are kept.
conf=/etc/recovera/upgrade.conf
grep -q '^GATEWAY_TOKEN_FILE=' "$conf" || echo 'GATEWAY_TOKEN_FILE=/etc/recovera/gateway-token' >> "$conf"
if ! grep -q '^UPDATE_ORIGINS=.' "$conf"; then
  sed -i '/^UPDATE_ORIGINS=/d' "$conf"
  echo 'UPDATE_ORIGINS=https://recoveragw.rjproductionsut.com' >> "$conf"
fi
grep -q '^TRANSITION_CHANNEL=' "$conf" || echo 'TRANSITION_CHANNEL=jammy-noble-transition' >> "$conf"
if [ -d /var/www/siris ] || [ -d /var/www/html ]; then
  python3 /usr/lib/recovera/branding/apply-branding.py /usr/local/share/recovera/recovera-logo.png
fi
if [ -d /usr/lib/datto/statusshell/logo ]; then
  rm -f /usr/lib/datto/statusshell/logo/*.logo
  install -m 0644 /usr/local/share/recovera/recovera-ascii.logo /usr/lib/datto/statusshell/logo/0.logo
fi
[ ! -e /etc/update-motd.d/25-datto ] || chmod a-x /etc/update-motd.d/25-datto
# BBR for replication over lossy WAN links. New connections pick it up; an
# unavailable module must never fail the package install.
modprobe tcp_bbr 2>/dev/null || true
sysctl -q -p /etc/sysctl.d/90-recovera-replication.conf 2>/dev/null || true
systemctl daemon-reload
systemctl enable recovera-upgrade-check.timer recovera-upgrade-validate.service recovera-cloud-isolation.service >/dev/null
/usr/local/sbin/recovera-cloud-isolation apply
systemctl try-restart recovera-upgrade-check.timer >/dev/null || true
if id recovera-repl >/dev/null 2>&1 && [ -f /etc/recovera-peer/config.json ]; then
  python3 /usr/lib/recovera/branding/apply-peer-ui.py
  # The flat (5.12.x) web UI compiles routes into Symfony's production cache;
  # rebuild it so the Recovera pages resolve at once. Never fail the update.
  if [ ! -d /usr/lib/datto/device/templates/commonlookandfeel ] && \
     [ -f /usr/lib/datto/device/app/console.php ]; then
    (
      cd /usr/lib/datto/device &&
        php app/console.php cache:clear --env=prod --no-warmup >/dev/null &&
        php app/console.php cache:warmup --env=prod >/dev/null
    ) || echo "recovera-appliance: Symfony cache rebuild failed; it rebuilds on first use" >&2
  fi
  visudo -cf /etc/sudoers.d/recovera-peer >/dev/null
  sshd -t
  a2enmod proxy proxy_http >/dev/null
  a2enconf recovera-peer-gateway >/dev/null
  apache2ctl configtest >/dev/null
  systemctl enable recovera-peer.service recovera-peer-sync.timer >/dev/null
  if [ "${RECOVERA_DEFER_SERVICE_RESTART:-0}" != 1 ]; then
    php_fpm=$(systemctl list-unit-files --no-legend --plain 'php*-fpm.service' 2>/dev/null \
      | awk '{print $1}' | sort -V | tail -n 1)
    systemctl restart "${php_fpm:-php8.1-fpm.service}" recovera-peer.service recovera-peer-sync.timer
    systemctl reset-failed apache2.service >/dev/null 2>&1 || true
    systemctl restart apache2.service
  fi
fi
exit 0
POSTINST
chmod 0755 "$stage/DEBIAN/postinst"

mkdir -p "$OUTPUT"
package=$OUTPUT/recovera-appliance_${VERSION}_all.deb
dpkg-deb --root-owner-group --build "$stage" "$package" >/dev/null
echo "$package"
