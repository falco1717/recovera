#!/bin/bash
# Publish an immutable package release and print its reviewed channel pointer.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ "$#" -eq 4 ] || { echo "usage: $0 ASSET_DIR VERSION SEQUENCE CHANNEL" >&2; exit 2; }
DIR=$1 VERSION=$2 SEQUENCE=$3 CHANNEL=$4
TAG=package-v$VERSION
MANIFEST=$DIR/recovera-package-manifest.json
SIGNATURE=$MANIFEST.sig
[ -f "$MANIFEST" ] && [ -f "$SIGNATURE" ] || { echo "manifest/signature missing" >&2; exit 1; }
jq -e --arg version "$VERSION" --arg channel "$CHANNEL" --argjson sequence "$SEQUENCE" \
  '.schema==2 and .type=="package" and .version==$version and .channel==$channel and .sequence==$sequence' \
  "$MANIFEST" >/dev/null
mapfile -t assets < <(jq -r '.packages[].asset' "$MANIFEST")
files=("$MANIFEST" "$SIGNATURE")
for asset in "${assets[@]}"; do [ -f "$DIR/$asset" ] || exit 1; files+=("$DIR/$asset"); done
python3 "$ROOT/tools/verify-release.py" \
  --directory "$DIR" \
  --manifest "$(basename "$MANIFEST")" \
  --signers "$ROOT/upgrade/keys/recovera-release-signers" >/dev/null
gh release create "$TAG" "${files[@]}" --verify-tag --title "Recovera $VERSION" \
  --notes "Signed Recovera $CHANNEL application package release sequence $SEQUENCE."
jq -n --arg channel "$CHANNEL" --arg tag "$TAG" --arg version "$VERSION" \
  --argjson sequence "$SEQUENCE" \
  '{schema:1,channel:$channel,type:"package",release_tag:$tag,manifest_asset:"recovera-package-manifest.json",signature_asset:"recovera-package-manifest.json.sig",sequence:$sequence,version:$version}'
echo "Review the pointer above, update upgrade/channels/$CHANNEL.json, and merge it to make the release discoverable."
