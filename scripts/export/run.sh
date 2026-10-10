#!/bin/bash
# Full package export. Read-only on the system: downloads .debs into $D, installs nothing.
set -u
TOOLS="$(cd "$(dirname "$0")" && pwd)"
D="$HOME/pkgexport-$(hostname)"
mkdir -p "$D/debs" "$D/lists"
cd "$D" || exit 1
echo "RUNNING" > status

# Package lists
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n' > lists/all-packages.tsv
dpkg-query -W -f='${Package}=${Version}\n' > lists/all-packages-versions.txt
apt-mark showmanual > lists/manual.txt
apt-mark showauto > lists/auto.txt
dpkg --get-selections > lists/selections.txt
apt list --installed 2>/dev/null | tail -n +2 > lists/apt-list-installed.txt
grep ',local]' lists/apt-list-installed.txt | cut -d/ -f1 > lists/local-debs.txt
# Portable = manual minus Datto, kernel/boot, and locally-installed (.deb-only) packages
grep -vxFf lists/local-debs.txt lists/manual.txt \
  | grep -vE '^(datto-|plymouth-theme-datto$|metalibvirt$|linux-(fips|image|headers|generic|modules|tools)|grub|shim|efibootmgr$)' \
  > lists/portable.txt

# Repo definitions and keys (never auth.conf, which holds repo credentials)
tar czf apt-sources.tgz --exclude='auth.conf*' -C / \
  etc/apt/sources.list etc/apt/sources.list.d etc/apt/trusted.gpg.d etc/apt/keyrings etc/apt/trusted.gpg 2>/dev/null

# Work out what can be downloaded, then fetch in batches
python3 -I "$TOOLS/pkgplan.py" plan "$D"
cd debs
xargs -a ../lists/downloadable.txt -n 100 apt-get download -q > ../download.log 2>&1
cd ..
python3 -I "$TOOLS/pkgplan.py" verify "$D"

# Index so the folder works as an offline apt source
(cd debs && dpkg-scanpackages . /dev/null 2>/dev/null | gzip -9 > Packages.gz)

echo "debs: $(ls debs/*.deb | wc -l)  size: $(du -sh debs | cut -f1)"
echo "DONE" > status
