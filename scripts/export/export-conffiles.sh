#!/bin/bash
# Run on spf-datto (as roseadmin; uses sudo). Captures the current content of every package
# config file (dpkg "Conffiles"), because Datto's mirror ships rebuilt Ubuntu packages with the
# same version numbers but different config files (apache2 ports.conf etc.), so the .debs alone
# don't reproduce spf-datto's configuration.
# Output: ~/spf-conffiles/conffiles.tgz + manifest.tsv (md5<TAB>path<TAB>package)
# Copy that folder to <export>/conffiles before running tools/make-bundle.sh.
# Contains secrets (TLS key, sudoers, root's authorized_keys); setup.sh withholds identity files.
set -euo pipefail
OUT="$HOME/spf-conffiles"; mkdir -p "$OUT"

dpkg-query -W -f='${Package}\n${Conffiles}\n' \
  | awk '/^[^ ]/{p=$1; next} NF>=2 && $3!="obsolete" {print p"\t"$1}' \
  | while IFS=$'\t' read -r p f; do
      if sudo test -f "$f" && ! sudo test -L "$f"; then
        printf '%s\t%s\t%s\n' "$(sudo md5sum "$f" | cut -d' ' -f1)" "$f" "$p"
      fi
    done | sort -t$'\t' -k2,2 -u > "$OUT/manifest.tsv"

cut -f2 "$OUT/manifest.tsv" | sed 's#^/##' > "$OUT/.paths"
sudo tar -C / -czf "$OUT/conffiles.tgz" -T "$OUT/.paths"
sudo chown "$(id -u):$(id -g)" "$OUT/conffiles.tgz"; rm -f "$OUT/.paths"
echo "$(wc -l < "$OUT/manifest.tsv") config files -> $OUT/conffiles.tgz ($(du -h "$OUT/conffiles.tgz" | cut -f1))"
