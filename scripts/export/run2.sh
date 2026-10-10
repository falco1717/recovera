#!/bin/bash
# Export via public mirrors. Uses a private apt root under $TOOLS; installs nothing, needs no root.
set -u
TOOLS="$(cd "$(dirname "$0")" && pwd)"
D="$HOME/pkgexport-$(hostname)"
R="$TOOLS/aptroot"
cd "$D" || exit 1
echo "RUNNING" > status

# Private apt root pointed at the public Ubuntu archive
mkdir -p "$R"/etc/apt/{trusted.gpg.d,apt.conf.d,preferences.d,sources.list.d} \
         "$R"/var/lib/apt/lists/partial "$R"/var/cache/apt/archives/partial "$R"/var/lib/dpkg
cp /etc/apt/trusted.gpg.d/ubuntu-keyring-2018-archive.gpg "$R/etc/apt/trusted.gpg.d/"
cp /var/lib/dpkg/status "$R/var/lib/dpkg/status"
cat > "$R/etc/apt/sources.list" <<'EOF'
deb [arch=amd64] http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse
deb [arch=amd64] http://archive.ubuntu.com/ubuntu jammy-updates main restricted universe multiverse
deb [arch=amd64] http://security.ubuntu.com/ubuntu jammy-security main restricted universe multiverse
EOF
APT=(apt-get -q -o "Dir=$R" -o "Dir::State::status=$R/var/lib/dpkg/status")
"${APT[@]}" update > apt-update.log 2>&1 || { echo "apt update failed"; tail apt-update.log; echo FAILED > status; exit 1; }

# 1. Exact versions still on the public mirror (signature-verified by apt)
python3 -I "$TOOLS/pkgplan2.py" plan "$R" "$D"
cd debs
xargs -a ../lists/pub-downloadable.txt -n 100 "${APT[@]}" download > ../download-ubuntu.log 2>&1

# 2. Superseded versions: Launchpad keeps every published build
: > ../download-launchpad.log
awk -F'\t' 'NR==FNR{skip[$1]=1;next} NF==3 && !($1 in skip)' ../lists/local-debs.txt ../lists/pub-missing.tsv \
  | while IFS=$'\t' read -r name ver arch; do
      local_ver="${ver#*:}"
      f="${name}_${local_ver}_${arch}.deb"
      [ -s "$f" ] && continue
      if curl -fsSL --max-time 120 -o "$f" "https://launchpad.net/ubuntu/+archive/primary/+files/$f" 2>/dev/null; then
        echo "OK   $f" >> ../download-launchpad.log
      else
        rm -f "$f"; echo "MISS $f" >> ../download-launchpad.log
      fi
    done

# 3. filebeat comes from Elastic, not Ubuntu
FB=$(dpkg-query -W -f='${Version}' filebeat 2>/dev/null)
if [ -n "$FB" ]; then
  curl -fsSL --max-time 300 -o "filebeat_${FB}_amd64.deb" "https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-${FB}-amd64.deb" \
    && curl -fsSL -o /tmp/fb.sha512 "https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-${FB}-amd64.deb.sha512" \
    && [ "$(cut -d' ' -f1 /tmp/fb.sha512)" = "$(sha512sum "filebeat_${FB}_amd64.deb" | cut -d' ' -f1)" ] \
    && echo "OK   filebeat ${FB} (sha512 verified)" >> ../download-launchpad.log \
    || { rm -f "filebeat_${FB}_amd64.deb"; echo "MISS filebeat ${FB}" >> ../download-launchpad.log; }
  rm -f /tmp/fb.sha512
fi

# 4. Integrity: every .deb's file checksums must match what is installed on this box
: > ../lists/integrity.tsv
for f in *.deb; do
  p=$(dpkg-deb -f "$f" Package)
  inst=/var/lib/dpkg/info/$p.md5sums; [ -f "$inst" ] || inst=/var/lib/dpkg/info/$p:amd64.md5sums
  if [ ! -f "$inst" ]; then r="no-file-list"
  elif diff -q <(dpkg-deb --ctrl-tarfile "$f" | tar xO --wildcards '*md5sums' 2>/dev/null | sort) <(sort "$inst") >/dev/null; then r="MATCH"
  else r="DIFFERS"; fi
  printf '%s\t%s\n' "$f" "$r" >> ../lists/integrity.tsv
done
cd ..
python3 -I "$TOOLS/pkgplan2.py" verify "$D"

# Index so the folder works as an offline apt source
(cd debs && dpkg-scanpackages . /dev/null 2>/dev/null | gzip -9 > Packages.gz)

echo "integrity: $(cut -f2 lists/integrity.tsv | sort | uniq -c | tr '\n' ' ')"
echo "debs: $(ls debs/*.deb | wc -l)  size: $(du -sh debs | cut -f1)"
echo "DONE" > status
