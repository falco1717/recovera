#!/bin/bash
# Publish already-built image assets, then print the channel pointer to review.
set -euo pipefail
[ "$#" -eq 4 ] || { echo "usage: $0 ASSET_DIR VERSION SEQUENCE CHANNEL" >&2; exit 2; }
DIR=$1 VERSION=$2 SEQUENCE=$3 CHANNEL=$4
TAG=image-v$VERSION
MANIFEST=$DIR/recovera-image-manifest.json
SIGNATURE=$MANIFEST.sig
[ -f "$MANIFEST" ] && [ -f "$SIGNATURE" ] || { echo "manifest/signature missing" >&2; exit 1; }
jq -e --arg version "$VERSION" --arg channel "$CHANNEL" --argjson sequence "$SEQUENCE" \
  '.version==$version and .channel==$channel and .sequence==$sequence' "$MANIFEST" >/dev/null
mapfile -t assets < <(jq -r '.image.parts[].name' "$MANIFEST")
files=("$MANIFEST" "$SIGNATURE")
for asset in "${assets[@]}"; do [ -f "$DIR/$asset" ] || exit 1; files+=("$DIR/$asset"); done
gh release create "$TAG" "${files[@]}" --verify-tag --title "Recovera image $VERSION" \
  --notes "Signed Recovera $CHANNEL appliance image sequence $SEQUENCE."
jq -n --arg channel "$CHANNEL" --arg tag "$TAG" --arg version "$VERSION" \
  --argjson sequence "$SEQUENCE" \
  '{schema:1,channel:$channel,release_tag:$tag,manifest_asset:"recovera-image-manifest.json",signature_asset:"recovera-image-manifest.json.sig",sequence:$sequence,version:$version}'
echo "Review the pointer above, update upgrade/channels/$CHANNEL.json, and merge it to make the image discoverable."
