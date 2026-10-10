#!/bin/bash
# Build the self-contained setup bundle (run on the workstation, Git Bash or Linux).
#   tools/make-bundle.sh [export-dir] [out-dir]
# export-dir: the pkgexport folder with debs/ (SHA256SUMS + Packages.gz) and lists/
# Produces <out-dir>/spf-datto-setup/ and <out-dir>/spf-datto-setup.tar (~1.6 GB).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
EXPORT="${1:-/f/Users/jfarmer/Desktop/pkgexport-spf-datto}"
OUT="${2:-$REPO/dist}"
B="$OUT/spf-datto-setup"

[ -f "$EXPORT/debs/SHA256SUMS" ] || { echo "no $EXPORT/debs/SHA256SUMS"; exit 1; }
[ -f "$EXPORT/lists/all-packages-versions.txt" ] || { echo "no $EXPORT/lists/all-packages-versions.txt"; exit 1; }

echo "checking export checksums..."
(cd "$EXPORT/debs" && sha256sum -c --quiet SHA256SUMS)

rm -rf "$B"; mkdir -p "$B/lists"
cp "$REPO/setup/setup.sh" "$REPO/setup/setup.conf" "$REPO/setup/README.txt" "$B/"
sed -i 's/\r$//' "$B/setup.sh" "$B/setup.conf" "$B/README.txt"
chmod 755 "$B/setup.sh"
cp "$EXPORT/lists/all-packages-versions.txt" "$EXPORT/lists/manual.txt" "$EXPORT/lists/portable.txt" \
   "$EXPORT/lists/local-debs.txt" "$EXPORT/lists/repacked.txt" "$B/lists/"
sed -i 's/\r$//' "$B"/lists/*.txt
if [ -f "$EXPORT/conffiles/conffiles.tgz" ] && [ -f "$EXPORT/conffiles/manifest.tsv" ]; then
  mkdir -p "$B/conffiles"
  cp "$EXPORT/conffiles/conffiles.tgz" "$EXPORT/conffiles/manifest.tsv" "$B/conffiles/"
  echo "included $(wc -l < "$B/conffiles/manifest.tsv") spf-datto config files"
else
  echo "WARNING: no $EXPORT/conffiles (scripts/export/export-conffiles.sh); Apache etc. will keep stock configs"
fi
echo "copying $(ls "$EXPORT"/debs/*.deb | wc -l) packages..."
cp -r "$EXPORT/debs" "$B/debs"
rm -f "$B/debs/.verified"

(cd "$OUT" && tar -cf spf-datto-setup.tar spf-datto-setup)
echo
echo "bundle: $OUT/spf-datto-setup.tar  ($(du -h "$OUT/spf-datto-setup.tar" | cut -f1))"
echo "sha256: $(sha256sum "$OUT/spf-datto-setup.tar" | cut -d' ' -f1)"
echo
echo "next:"
echo "  scp $OUT/spf-datto-setup.tar ubuntu@VM:"
echo "  ssh ubuntu@VM 'tar xf spf-datto-setup.tar && cd spf-datto-setup && sudo ./setup.sh'"
