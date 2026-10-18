#!/bin/bash
# Build the self-contained, sanitized setup bundle (run on Ubuntu/Linux).
#   tools/make-bundle.sh [export-dir] [out-dir]
# export-dir: the pkgexport folder with debs/ (SHA256SUMS and package indexes) and lists/
# Produces <out-dir>/recovera-setup/ and <out-dir>/recovera-setup.tar.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
EXPORT="${1:-/f/Users/jfarmer/Desktop/pkgexport-recovera}"
OUT="${2:-$REPO/dist}"
B="$OUT/recovera-setup"
PRUNE="$REPO/setup/prune-packages.txt"

for command in dpkg-deb dpkg-scanpackages fakeroot gzip python3 sha256sum tar; do
  command -v "$command" >/dev/null 2>&1 || { echo "missing required command: $command"; exit 1; }
done

[ -f "$EXPORT/debs/SHA256SUMS" ] || { echo "no $EXPORT/debs/SHA256SUMS"; exit 1; }
[ -f "$EXPORT/lists/all-packages-versions.txt" ] || { echo "no $EXPORT/lists/all-packages-versions.txt"; exit 1; }

echo "checking export checksums..."
(cd "$EXPORT/debs" && sha256sum -c --quiet SHA256SUMS)

rm -rf "$B"; mkdir -p "$B/lists" "$B/debs"
cp "$REPO/setup/setup.sh" "$REPO/setup/migrate-layout.sh" \
  "$REPO/setup/setup.conf" "$REPO/setup/README.txt" "$B/"
cp -r "$REPO/setup/wheels" "$B/wheels"
cp -r "$REPO/setup/peer" "$B/peer"
cp -r "$REPO/setup/branding" "$B/branding"
cp -r "$REPO/setup/isolation" "$B/isolation"
cp -r "$REPO/upgrade" "$B/upgrade"
sed -i 's/\r$//' "$B/setup.sh" "$B/setup.conf" "$B/README.txt"
chmod 755 "$B/setup.sh" "$B/migrate-layout.sh"
cp "$EXPORT/lists/manual.txt" "$EXPORT/lists/portable.txt" \
   "$EXPORT/lists/local-debs.txt" "$EXPORT/lists/repacked.txt" "$B/lists/"
cp "$PRUNE" "$B/lists/pruned-packages.txt"
if [ -f "$EXPORT/conffiles/conffiles.tgz" ] && [ -f "$EXPORT/conffiles/manifest.tsv" ]; then
  mkdir -p "$B/conffiles"
  cp "$EXPORT/conffiles/conffiles.tgz" "$EXPORT/conffiles/manifest.tsv" "$B/conffiles/"
else
  echo "WARNING: no $EXPORT/conffiles export; Apache etc. will keep stock configs"
fi
echo "copying $(find "$EXPORT/debs" -maxdepth 1 -name '*.deb' | wc -l) source packages..."
cp "$EXPORT"/debs/*.deb "$B/debs/"

echo "removing source-appliance-only packages..."
while IFS= read -r package; do
  case "$package" in ''|'#'*) continue ;; esac
  rm -f "$B/debs/${package}_"*.deb
done < "$PRUNE"

# Make Recovera-owned files a real versioned package. Fresh installations then
# establish the exact rollback baseline required by routine package updates.
recovera_version=$(tr -d '[:space:]' < "$REPO/VERSION")
[ -n "$recovera_version" ] || { echo "VERSION is empty"; exit 1; }
bash "$REPO/tools/build-recovera-appliance-deb.sh" \
  --version "${recovera_version}-1" --output "$B/debs" >/dev/null

source_deb=$(find "$B/debs" -maxdepth 1 -name 'datto-siris-os-2_*.deb' -print -quit)
[ -n "$source_deb" ] || { echo "required base application package not found"; exit 1; }
tmp=$(mktemp -d)
cleanup() {
  # The source package contains deliberately non-traversable config directories
  # (for example /etc/apache2 mode 0600). Make only the temporary extraction
  # user-traversable so an unprivileged build can remove its workspace.
  chmod -R u+rwX "$tmp" 2>/dev/null || true
  rm -rf -- "$tmp"
}
trap cleanup EXIT

# systemd-logind may remove a user's SysV IPC objects when an SSH session ends.
# A large dpkg-deb repack outlives that session and the default fakeroot backend
# then dies with semop(EINVAL). Prefer the installed TCP backend when available.
FAKEROOT_ARGS=()
fakeroot_tcp_lib=$(find /usr/lib -type f -path '*/libfakeroot/libfakeroot-tcp.so' -print -quit 2>/dev/null || true)
if command -v faked-tcp >/dev/null 2>&1 && [ -n "$fakeroot_tcp_lib" ]; then
  FAKEROOT_ARGS=(-l "$fakeroot_tcp_lib" -f "$(command -v faked-tcp)")
fi

package_ownership_map() {
  dpkg-deb --fsys-tarfile "$1" | tar --numeric-owner -tvf - |
    awk '$6 != "./etc/apache2/ssl/www.key" &&
         $6 != "./etc/apache2/ssl/www.crt" &&
         $6 !~ "^./etc/(filebeat|fluent-bit|telegraf)(/|$)" &&
         $6 != "./etc/rsyslog.d/60-fluent-bit.conf" &&
         $6 != "./etc/sudoers.d/telegraf" &&
         $6 !~ "^./lib/systemd/system/(al-agent|falcon-sensor|filebeat|fluent-bit|telegraf|wiz-sensor)\\.service\\.d(/|$)" &&
         $6 !~ "^./lib/systemd/system/datto-(configure-wiz-sensor-on-startup|filebeat-configure|telegraf-configure)\\.service$" {
           print $2 "\t" $6
         }' |
    sort
}

echo "sanitizing base application package..."
package_ownership_map "$source_deb" > "$tmp/ownership.before"
fakeroot "${FAKEROOT_ARGS[@]}" -- bash -euo pipefail -c '
  mkdir -p "$2/source/DEBIAN"
  dpkg-deb --fsys-tarfile "$1" | tar --numeric-owner -xpf - -C "$2/source"
  dpkg-deb --ctrl-tarfile "$1" | tar --numeric-owner -xpf - -C "$2/source/DEBIAN"
  python3 "$3" "$2/source" "$4"
  dpkg-deb -b "$2/source" "$2/source-package.deb" >/dev/null
' _ "$source_deb" "$tmp" "$REPO/tools/sanitize-source-package.py" "$PRUNE"
package_ownership_map "$tmp/source-package.deb" > "$tmp/ownership.after"
if ! cmp -s "$tmp/ownership.before" "$tmp/ownership.after"; then
  echo "sanitized package changed file ownership metadata"
  diff -u "$tmp/ownership.before" "$tmp/ownership.after" | head -n 80 || true
  exit 1
fi
mv "$tmp/source-package.deb" "$source_deb"

# Remove source identity and configuration for packages intentionally excluded.
if [ -f "$B/conffiles/conffiles.tgz" ]; then
  mkdir -p "$tmp/conffiles"
  tar -C "$tmp/conffiles" -xzf "$B/conffiles/conffiles.tgz"
  rm -rf "$tmp/conffiles/etc/filebeat" "$tmp/conffiles/etc/fluent-bit" \
         "$tmp/conffiles/etc/telegraf"
  rm -f "$tmp/conffiles/etc/apache2/ssl/www.key" \
        "$tmp/conffiles/etc/apache2/ssl/www.crt" \
        "$tmp/conffiles/etc/rsyslog.d/60-fluent-bit.conf" \
        "$tmp/conffiles/etc/sudoers.d/telegraf" \
        "$tmp/conffiles/lib/systemd/system/datto-configure-wiz-sensor-on-startup.service" \
        "$tmp/conffiles/lib/systemd/system/datto-filebeat-configure.service" \
        "$tmp/conffiles/lib/systemd/system/datto-telegraf-configure.service"
  rm -rf "$tmp/conffiles/lib/systemd/system/al-agent.service.d" \
         "$tmp/conffiles/lib/systemd/system/falcon-sensor.service.d" \
         "$tmp/conffiles/lib/systemd/system/filebeat.service.d" \
         "$tmp/conffiles/lib/systemd/system/fluent-bit.service.d" \
         "$tmp/conffiles/lib/systemd/system/telegraf.service.d" \
         "$tmp/conffiles/lib/systemd/system/wiz-sensor.service.d"
  # Remove every config file attributed to a package we removed, including
  # paths outside that package's usual /etc subtree (FIPS boot fragments,
  # Falcon init/logrotate files, and td-agent-bit configuration).
  while IFS= read -r package; do
    case "$package" in ''|'#'*) continue ;; esac
    awk -F '\t' -v package="$package" '$3 == package { print $2 }' \
      "$B/conffiles/manifest.tsv" |
      while IFS= read -r f; do rm -f "$tmp/conffiles$f"; done
  done < "$PRUNE"

  # The application pool used Telegraf only as the secondary owner of its Unix
  # socket. Apache already runs as www-data, so keep the socket usable without
  # retaining a telemetry-only system group.
  fpm_pool="$tmp/conffiles/etc/php/8.1/fpm/pool.d/siris.conf"
  if [ -f "$fpm_pool" ]; then
    sed -Ei 's/^([[:space:]]*listen\.group[[:space:]]*=[[:space:]]*)telegraf([[:space:]]*)$/\1www-data\2/' "$fpm_pool"
  fi

  awk -F '\t' '
    NR == FNR { if ($0 !~ /^[[:space:]]*(#|$)/) prune[$1] = 1; next }
    !($3 in prune) &&
    $2 !~ "^/root/" &&
    $2 !~ "^/etc/(filebeat|fluent-bit|telegraf)/" &&
    $2 !~ "^/etc/apache2/ssl/www\\.(key|crt)$" &&
    $2 != "/etc/bash.bashrc" &&
    $2 != "/etc/hosts" &&
    $2 != "/etc/hostname" &&
    $2 != "/etc/machine-id" &&
    $2 != "/etc/watchdog.conf" &&
    $2 !~ "^/etc/ssh/ssh_host_" &&
    $2 != "/etc/rsyslog.d/60-fluent-bit.conf" &&
    $2 != "/etc/sudoers.d/telegraf" &&
    $2 !~ "^/lib/systemd/system/(al-agent|falcon-sensor|filebeat|fluent-bit|telegraf|wiz-sensor)\\.service\\.d/" &&
    $2 !~ "^/lib/systemd/system/datto-(configure-wiz-sensor-on-startup|filebeat-configure|telegraf-configure)\\.service$"
  ' "$PRUNE" "$B/conffiles/manifest.tsv" > "$tmp/manifest.filtered.tsv"

  : > "$tmp/manifest.tsv"
  while IFS=$'\t' read -r sum f package; do
    [ -f "$tmp/conffiles$f" ] || continue
    sum=$(md5sum "$tmp/conffiles$f" | cut -d' ' -f1)
    printf '%s\t%s\t%s\n' "$sum" "$f" "$package" >> "$tmp/manifest.tsv"
  done < "$tmp/manifest.filtered.tsv"
  mv "$tmp/manifest.tsv" "$B/conffiles/manifest.tsv"
  find "$tmp/conffiles" -depth -type d -empty -delete

  # The archive is rebuilt by the unprivileged bundle author. Without explicit
  # ownership, tar records that user's UID/GID and cp -a later installs critical
  # files such as /etc/sudoers with the wrong owner. All exported paths are
  # system configuration under /etc or /root and must be root-owned.
  tar --owner=0 --group=0 --numeric-owner -C "$tmp/conffiles" \
    -czf "$B/conffiles/conffiles.tgz" .
  echo "included $(wc -l < "$B/conffiles/manifest.tsv") sanitized config files"
fi

echo "regenerating package lists and repository metadata..."
: > "$B/lists/all-packages-versions.txt"
: > "$tmp/package-names.txt"
for deb in "$B"/debs/*.deb; do
  package=$(dpkg-deb -f "$deb" Package)
  version=$(dpkg-deb -f "$deb" Version)
  printf '%s=%s\n' "$package" "$version" >> "$B/lists/all-packages-versions.txt"
  printf '%s\n' "$package" >> "$tmp/package-names.txt"
done
sort -u -o "$B/lists/all-packages-versions.txt" "$B/lists/all-packages-versions.txt"
sort -u -o "$tmp/package-names.txt" "$tmp/package-names.txt"
for list in manual.txt portable.txt local-debs.txt repacked.txt; do
  grep -Fxf "$tmp/package-names.txt" "$B/lists/$list" > "$tmp/$list" || true
  mv "$tmp/$list" "$B/lists/$list"
done
sed -i 's/\r$//' "$B"/lists/*.txt

(cd "$B/debs" && {
  dpkg-scanpackages -m . /dev/null > Packages
  gzip -9c Packages > Packages.gz
})
(cd "$B/debs" && {
  find . -maxdepth 1 -type f \( -name '*.deb' -o -name Packages -o -name Packages.gz \) -printf '%f\n' |
    sort | xargs sha256sum > SHA256SUMS
})
[ -s "$B/debs/Packages" ] && [ -s "$B/debs/Packages.gz" ] || {
  echo "failed to generate local apt repository indexes"; exit 1;
}

# Fail closed if a removed package, source private key, or active factory
# password hash survived the rebuild.
for package in $(grep -Ev '^\s*(#|$)' "$PRUNE"); do
  ! grep -q "^${package}=" "$B/lists/all-packages-versions.txt" || {
    echo "excluded package survived: $package"; exit 1;
  }
done
if [ -f "$B/conffiles/conffiles.tgz" ]; then
  bad_conf_owners=$(tar --numeric-owner -tvzf "$B/conffiles/conffiles.tgz" |
    awk '$2 != "0/0" { if (n < 5) print; n++ }')
  if [ -n "$bad_conf_owners" ]; then
    echo "configuration archive contains non-root ownership:" >&2
    printf '%s\n' "$bad_conf_owners" >&2
    exit 1
  fi
  if awk -F '\t' '
      NR == FNR { if ($0 !~ /^[[:space:]]*(#|$)/) prune[$1] = 1; next }
      $3 in prune { found = 1 }
      END { exit !found }
    ' "$PRUNE" "$B/conffiles/manifest.tsv"; then
    echo "configuration from an excluded package survived" >&2
    exit 1
  fi
  if awk -F '\t' '
      $2 ~ "^/root/" ||
      $2 ~ "^/etc/apache2/ssl/" ||
      $2 == "/etc/bash.bashrc" ||
      $2 == "/etc/hosts" ||
      $2 == "/etc/hostname" ||
      $2 == "/etc/machine-id" ||
      $2 == "/etc/watchdog.conf" ||
      $2 ~ "^/etc/ssh/ssh_host_" { found = 1 }
      END { exit !found }
    ' "$B/conffiles/manifest.tsv"; then
    echo "source host identity or unused host configuration survived" >&2
    exit 1
  fi
  if tar -xOzf "$B/conffiles/conffiles.tgz" ./etc/php/8.1/fpm/pool.d/siris.conf 2>/dev/null |
     grep -Eq '^[[:space:]]*listen\.group[[:space:]]*=[[:space:]]*telegraf[[:space:]]*$'; then
    echo "Telegraf PHP-FPM socket group survived" >&2
    exit 1
  fi
fi
rm -rf "$tmp/check"; mkdir -p "$tmp/check"
dpkg-deb --fsys-tarfile "$source_deb" | tar --no-same-owner -xpf - -C "$tmp/check"
for excluded in \
  etc/apache2/ssl/www.key etc/apache2/ssl/www.crt \
  etc/filebeat etc/fluent-bit etc/telegraf \
  etc/rsyslog.d/60-fluent-bit.conf etc/sudoers.d/telegraf \
  lib/systemd/system/al-agent.service.d \
  lib/systemd/system/datto-configure-wiz-sensor-on-startup.service \
  lib/systemd/system/datto-filebeat-configure.service \
  lib/systemd/system/datto-telegraf-configure.service \
  lib/systemd/system/falcon-sensor.service.d \
  lib/systemd/system/filebeat.service.d \
  lib/systemd/system/fluent-bit.service.d \
  lib/systemd/system/telegraf.service.d \
  lib/systemd/system/wiz-sensor.service.d; do
  [ ! -e "$tmp/check/$excluded" ] || { echo "excluded path survived: $excluded"; exit 1; }
done
! grep -Eq '^[[:space:]]*listen\.group[[:space:]]*=[[:space:]]*telegraf[[:space:]]*$' \
  "$tmp/check/etc/php/8.1/fpm/pool.d/siris.conf" || {
    echo "Telegraf PHP-FPM socket group survived in application package"; exit 1;
  }
! grep -Eq '(telegraf package file list not found|systemctl preset[[:space:]\\]*(fluent-bit|telegraf|al-agent|filebeat))' \
  "$tmp/source/DEBIAN/postinst" || { echo "excluded-agent postinst hook survived"; exit 1; }
if awk -F: '$2 !~ /^(!|\*|!!)?$/ { found=1 } END { exit found ? 0 : 1 }' \
    "$tmp/check/datto/def-configs/shadow"; then
  echo "active factory password hash survived"; exit 1
fi

echo "payload contains $(wc -l < "$B/lists/all-packages-versions.txt") packages"

(cd "$OUT" && tar -cf recovera-setup.tar recovera-setup)
echo
echo "bundle: $OUT/recovera-setup.tar  ($(du -h "$OUT/recovera-setup.tar" | cut -f1))"
echo "sha256: $(sha256sum "$OUT/recovera-setup.tar" | cut -d' ' -f1)"
echo
echo "next:"
echo "  ./install.sh --bundle $OUT/recovera-setup.tar --check"
echo "  ./install.sh --bundle $OUT/recovera-setup.tar"
