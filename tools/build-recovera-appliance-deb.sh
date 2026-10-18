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
  "$stage/usr/lib/recovera/branding" \
  "$stage/usr/share/recovera/defaults" "$stage/usr/share/recovera/setup" \
  "$stage/etc/systemd/system" \
  "$stage/etc/apache2/conf-available" "$stage/etc/ssh/sshd_config.d" \
  "$stage/etc/sudoers.d" "$stage/etc/update-motd.d" \
  "$stage/etc/systemd/system/datto-sshd-configure.service.d" \
  "$stage/etc/systemd/system/datto-firewall-share-sync.service.d"

cat > "$stage/DEBIAN/control" <<EOF
Package: recovera-appliance
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Maintainer: Recovera Project <noreply@recovera.local>
Depends: python3, openssh-client, openssh-server, sudo, apache2, php8.1-fpm, xz-utils
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
install -m 0440 "$ROOT/setup/peer/sudoers-recovera-peer" "$stage/etc/sudoers.d/recovera-peer"
install -m 0644 "$ROOT/setup/peer/recovera-sshd-service.conf" \
  "$stage/etc/systemd/system/datto-sshd-configure.service.d/recovera.conf"
install -m 0644 "$ROOT/setup/peer/recovera-firewall-service.conf" \
  "$stage/etc/systemd/system/datto-firewall-share-sync.service.d/recovera.conf"

cp -a "$ROOT/setup/branding/." "$stage/usr/lib/recovera/branding/"
install -m 0644 "$ROOT/setup/branding/recovera-logo.png" "$stage/usr/local/share/recovera/recovera-logo.png"
install -m 0644 "$ROOT/setup/branding/recovera-ascii.logo" "$stage/usr/local/share/recovera/recovera-ascii.logo"
install -m 0755 "$ROOT/setup/branding/recovera-motd" "$stage/etc/update-motd.d/25-recovera"
install -m 0755 "$ROOT/setup/migrate-layout.sh" "$stage/usr/local/lib/recovera/migrate-layout"
install -m 0755 "$ROOT/setup/setup.sh" "$stage/usr/share/recovera/setup/setup.sh"
install -m 0755 "$ROOT/setup/migrate-layout.sh" "$stage/usr/share/recovera/setup/migrate-layout.sh"
install -m 0644 "$ROOT/setup/README.txt" "$stage/usr/share/recovera/setup/README.txt"

install -m 0755 "$ROOT/upgrade/recovera-upgrade" "$stage/usr/local/sbin/recovera-upgrade"
install -m 0755 "$ROOT/upgrade/recovera-upgrade-schedule" "$stage/usr/local/sbin/recovera-upgrade-schedule"
install -m 0755 "$ROOT/upgrade/recovera-image-boot" "$stage/usr/local/lib/recovera-upgrade/"
install -m 0755 "$ROOT/upgrade/recovera-migrate-config" "$stage/usr/local/lib/recovera-upgrade/"
install -m 0644 "$ROOT/upgrade/keys/recovera-release-signers" "$stage/usr/local/share/recovera-upgrade/release-signers"
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
fi
install -d -m 0755 /etc/recovera /var/cache/recovera-upgrade/packages /var/lib/recovera-upgrade/transactions
if [ ! -f /etc/recovera/upgrade.conf ]; then
  install -m 0600 /usr/share/recovera/defaults/upgrade.conf /etc/recovera/upgrade.conf
fi
if [ -d /var/www/siris ] || [ -d /var/www/html ]; then
  python3 /usr/lib/recovera/branding/apply-branding.py /usr/local/share/recovera/recovera-logo.png
fi
if [ -d /usr/lib/datto/statusshell/logo ]; then
  rm -f /usr/lib/datto/statusshell/logo/*.logo
  install -m 0644 /usr/local/share/recovera/recovera-ascii.logo /usr/lib/datto/statusshell/logo/0.logo
fi
[ ! -e /etc/update-motd.d/25-datto ] || chmod a-x /etc/update-motd.d/25-datto
systemctl daemon-reload
systemctl enable recovera-upgrade-check.timer recovera-upgrade-validate.service recovera-cloud-isolation.service >/dev/null
/usr/local/sbin/recovera-cloud-isolation apply
systemctl try-restart recovera-upgrade-check.timer >/dev/null || true
if id recovera-repl >/dev/null 2>&1 && [ -f /etc/recovera-peer/config.json ]; then
  python3 /usr/lib/recovera/branding/apply-peer-ui.py
  visudo -cf /etc/sudoers.d/recovera-peer >/dev/null
  sshd -t
  a2enmod proxy proxy_http >/dev/null
  a2enconf recovera-peer-gateway >/dev/null
  apache2ctl configtest >/dev/null
  systemctl enable recovera-peer.service recovera-peer-sync.timer >/dev/null
  if [ "${RECOVERA_DEFER_SERVICE_RESTART:-0}" != 1 ]; then
    systemctl restart php8.1-fpm recovera-peer.service recovera-peer-sync.timer
    systemctl reload apache2
  fi
fi
exit 0
POSTINST
chmod 0755 "$stage/DEBIAN/postinst"

mkdir -p "$OUTPUT"
package=$OUTPUT/recovera-appliance_${VERSION}_all.deb
dpkg-deb --root-owner-group --build "$stage" "$package" >/dev/null
echo "$package"
