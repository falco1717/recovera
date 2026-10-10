Package export: spf-datto (10.0.3.147)
Datto SIRIS OS 2 5.6.3 on Ubuntu 22.04.5 LTS (jammy), amd64
Exported 2026-10-09

WHAT'S HERE
  debs\              one .deb for every installed package: 1,351 files, about 1.6 GB
  debs\Packages.gz   index so the folder works as an offline apt source
  debs\SHA256SUMS    checksum for every file in debs\
  lists\             package lists (see below)
  apt-sources.tgz    the box's /etc/apt sources and keys (no credential files)
  *.log              download and repack logs

WHERE EACH .deb CAME FROM
    986  Ubuntu public mirror (archive/security.ubuntu.com). Original, signature-verified files.
    269  Launchpad (Ubuntu's archive of every published build). These are versions that are no
         longer on the mirror. Datto's mirror is a frozen Ubuntu snapshot. Listed in lists\from-launchpad.txt.
      1  filebeat, from Elastic (sha512 verified against Elastic's published hash)
     95  rebuilt from the installed files with dpkg-repack. Listed in lists\repacked.txt.
         These are the Datto packages, Falcon, Wiz, the FIPS/Ubuntu Pro packages, plus
         zbar (Launchpad only had the 24.04 build) and td-agent-bit (built by hand: its
         parsers.conf conffile is now owned by fluent-bit, so it was dropped from the package).

  Every file's checksums were compared against what dpkg says is installed on spf-datto.
  All 1,351 match (lists\integrity.tsv).

!! The repacked files contain spf-datto's CURRENT config files, including local settings and
!! possibly keys or tokens. Treat this folder as sensitive. They are also not byte-identical
!! to the vendor originals and are unsigned.

LISTS
  manual.txt               265 explicitly installed packages
  portable.txt             245 of those that are safe on a normal Ubuntu 22.04 box
                           (no Datto, kernel/boot, or local-only packages)
  auto.txt, selections.txt full install state, for an exact rebuild
  all-packages*.tsv/txt    all 1,351 with versions
  local-debs.txt           the 43 that were installed from a local .deb (never from a repo)
  repacked.txt, from-launchpad.txt, integrity.tsv, missing-debs.tsv (empty = nothing missing)

INSTALLING ON ANOTHER UBUNTU 22.04 amd64 BOX (no internet or repos needed)
  sudo cp -r debs /opt/localdebs
  echo 'deb [trusted=yes] file:/opt/localdebs ./' | sudo tee /etc/apt/sources.list.d/localdebs.list
  sudo apt-get update
  xargs -a portable.txt sudo apt-get install -y

  Use portable.txt, not the full list. Installing the kernel, grub, firmware or FIPS packages
  from another machine can leave the target unbootable or only partly in FIPS mode.
  The Datto packages will install but won't work without Datto device registration, and
  copying them to another machine is probably against Datto's license terms.
  Falcon and Wiz need re-registration with your tenant ID / CID. Use the vendor installers.
