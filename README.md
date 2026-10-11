# backops

One command turns an existing Ubuntu 22.04 amd64 VM into a locally usable,
offline-capable SIRIS replica. This branch does not deploy, modify, or require
vCenter/ESXi.

## Install on an existing Ubuntu VM

The VM needs Ubuntu 22.04 amd64, a normal user with `sudo` access, and about
12 GB free on `/`. A blank second disk of at least 20 GB is optional for ZFS.

```bash
gh auth login
gh repo clone falco1717/backops
cd backops
git switch offline/air-gapped-setup
./install.sh --check   # optional preflight and package simulation
./install.sh
```

`install.sh` prompts for `sudo`, downloads the pinned installation payload from
this repository's private GitHub Release, verifies its checksum, and runs the
setup workflow. The installation continues as a systemd unit if SSH disconnects
and reboots automatically when finished.

The defaults preserve the VM's current IP address. Edit `setup/setup.conf` first
to change networking, disable the automatic reboot, or require/disable ZFS.
`ZFS_CONFIGURE=auto` uses a suitable blank disk when present and otherwise
completes installation without ZFS.

After reboot, open `https://<VM-IP>/`, finish the local registration wizard, and
sign in with the local administrator. Initial setup and local login do not need
Internet. Datto enrollment, licensing, updates, and cloud services are not
emulated.

## Fully air-gapped install

Copy this repository and `spf-datto-setup.tar` to the VM, then run:

```bash
./install.sh --bundle /path/to/spf-datto-setup.tar --check
./install.sh --bundle /path/to/spf-datto-setup.tar
```

All package and registration steps then run without network access. Apt uses
only the bundle's local repository and pip uses only vendored wheels.

## Status and verification

```bash
sudo /opt/spf-datto/setup.sh status
sudo /opt/spf-datto/setup.sh verify
sudo cat /var/log/spf-datto-verify.log
```

A successful build reports `RESULT: PASS`. Re-running the installer resumes
safely; completed phases are skipped.

## Maintainer notes

- `setup/setup.sh` contains the idempotent installation phases.
- `setup/setup.conf` contains user-editable defaults.
- `setup/release.env` pins the private release payload and checksum.
- `tools/make-bundle.sh` builds the payload from the package export.
- `scripts/export/` and `scripts/vm/` preserve lower-level tooling but are not
  needed for the normal install.
- `docs/datto-siris-registration-flow.md` documents the registration changes.

The payload contains repacked appliance packages and configuration files. Keep
the repository and release private and treat the payload as sensitive.
