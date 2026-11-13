#!/usr/bin/env bash
set -euo pipefail

version=1.4.1
source_sha=7567187df63adb1d008cb2d2405a47efe5959f9c691f8e974f156174109c6fab
out=${1:-"$PWD/php-xattr_${version}-1recovera1_amd64.deb"}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for command in curl dpkg-deb make php-config phpize sha256sum tar; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

curl -fsSL "https://pecl.php.net/get/xattr-${version}.tgz" -o "$work/xattr.tgz"
echo "$source_sha  $work/xattr.tgz" | sha256sum -c -
tar -xzf "$work/xattr.tgz" -C "$work"
cd "$work/xattr-$version"
phpize
./configure --with-php-config="$(command -v php-config)"
make -j"$(nproc)"

stage="$work/stage"
extension_dir=$(php-config --extension-dir)
install -D -m 0644 modules/xattr.so "$stage$extension_dir/xattr.so"
install -D -m 0644 /dev/stdin "$stage/etc/php/8.3/mods-available/xattr.ini" <<'EOF'
extension=xattr.so
EOF
install -d -m 0755 "$stage/DEBIAN"
cat > "$stage/DEBIAN/control" <<EOF
Package: php-xattr
Version: ${version}-1recovera1
Architecture: amd64
Maintainer: Recovera Appliance
Depends: php8.3-common
Section: php
Priority: optional
Description: xattr extension for Recovera on PHP 8.3
 Provides the PECL xattr extension required by Recovera filesystem metadata operations.
EOF
cat > "$stage/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
phpenmod xattr >/dev/null 2>&1 || true
exit 0
EOF
cat > "$stage/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
phpdismod xattr >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$stage/DEBIAN/postinst" "$stage/DEBIAN/prerm"
dpkg-deb --root-owner-group --build "$stage" "$out" >/dev/null
dpkg-deb --info "$out"
sha256sum "$out"
