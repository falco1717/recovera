#!/bin/bash
# Rebuild every installed package that has no .deb yet from the files on disk (dpkg-repack).
# dpkg-repack is unpacked into $TOOLS, never installed. Reads the system, writes only into $D/debs.
set -u
TOOLS="$(cd "$(dirname "$0")" && pwd)"
D="$HOME/pkgexport-$(hostname)"
R="$TOOLS/aptroot"
ME="$(id -u):$(id -g)"

# Wait for the public-mirror pass to finish
until grep -qxE 'DONE|FAILED' "$D/status" 2>/dev/null; do sleep 15; done
grep -qx DONE "$D/status" || exit 1
echo "REPACKING" > "$D/status"

# Fetch and unpack dpkg-repack (no install)
if [ ! -x "$TOOLS/repack/usr/bin/dpkg-repack" ]; then
  (cd "$TOOLS" && apt-get -q -o "Dir=$R" -o "Dir::State::status=$R/var/lib/dpkg/status" download dpkg-repack \
     && dpkg-deb -x dpkg-repack_*.deb repack) || { echo "could not get dpkg-repack"; echo FAILED > "$D/status"; exit 1; }
fi

cd "$D/debs" || exit 1
: > ../repack.log
: > ../lists/repacked.txt
tail -n +2 ../lists/missing-debs.tsv | cut -f1 | while read -r p; do
  [ -n "$p" ] || continue
  if sudo -n "$TOOLS/repack/usr/bin/dpkg-repack" "$p" >> ../repack.log 2>&1; then
    echo "$p" >> ../lists/repacked.txt
  else
    echo "FAIL $p" >> ../repack.log
  fi
done
sudo -n chown "$ME" ./*.deb
sudo -n rm -rf ./dpkg-repack.* 2>/dev/null

# Integrity for the repacked files (same check as the downloaded ones)
while read -r p; do
  f=$(ls "${p}"_*.deb 2>/dev/null | head -1); [ -n "$f" ] || continue
  inst=/var/lib/dpkg/info/$p.md5sums; [ -f "$inst" ] || inst=/var/lib/dpkg/info/$p:amd64.md5sums
  if [ ! -f "$inst" ]; then r="no-file-list"
  elif diff -q <(dpkg-deb --ctrl-tarfile "$f" | tar xO --wildcards '*md5sums' 2>/dev/null | sort) <(sort "$inst") >/dev/null; then r="MATCH"
  else r="DIFFERS"; fi
  printf '%s\t%s\trepacked\n' "$f" "$r" >> ../lists/integrity.tsv
done < ../lists/repacked.txt
cd ..
python3 -I "$TOOLS/pkgplan2.py" verify "$D"

(cd debs && dpkg-scanpackages . /dev/null 2>/dev/null | gzip -9 > Packages.gz)
echo "repacked: $(wc -l < lists/repacked.txt)  failed: $(grep -c '^FAIL' repack.log)"
echo "debs: $(ls debs/*.deb | wc -l)  size: $(du -sh debs | cut -f1)"
echo "DONE" > status
