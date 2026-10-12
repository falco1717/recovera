# Recovera

One command turns an existing Ubuntu 22.04 amd64 VM into a locally usable,
offline-capable Recovera backup appliance. This branch does not deploy, modify, or require
vCenter/ESXi.

The installation payload contains 1,329 packages. The bundle builder removes
22 source-appliance-only security, telemetry, debug, and legacy FIPS-kernel
packages while preserving the complete dependency closure needed by the local
application. It also removes copied appliance credentials and private keys.

## Install on an existing Ubuntu VM

The VM needs Ubuntu 22.04 amd64, at least 8 GB RAM, a normal user with `sudo`
access, about 12 GB free on `/`, and a blank second disk of at least 20 GB for `homePool`.
Hardware virtualization must be available. If the appliance runs as a VM,
enable nested virtualization before powering it on (in VMware, expose
hardware-assisted virtualization to the guest).

Eight GB supports screenshot/boot verification of small protected VMs. Size the
appliance with additional RAM when recovery VMs need more memory.

```bash
gh auth login
gh repo clone falco1717/recovera
cd recovera
git switch feature/recovera-rebrand
./install.sh --check   # optional preflight and package simulation
./install.sh
```

`install.sh` prompts for `sudo`, downloads the pinned installation payload from
this repository's private GitHub Release, verifies its checksum, and runs the
setup workflow. The installation continues as a systemd unit if SSH disconnects
and reboots automatically when finished.

The defaults preserve the VM's current IP address and require both KVM and a
blank disk for ZFS. Edit `setup/setup.conf` first to change networking or disable
the automatic reboot. `REQUIRE_KVM=no` and `ZFS_CONFIGURE=auto/no` are available
only for limited troubleshooting installs; agentless protection or core UI and
storage features will not be fully functional without them.

After reboot, open `https://<VM-IP>/`, finish the local registration wizard, and
sign in with the local administrator. Initial setup and local login do not need
Internet. Legacy vendor enrollment, licensing, updates, and cloud services are not
emulated.

## Offline appliance replication

The installer also provides SIRIS-Private-style replication between Recovera
appliances. It uses a one-time pairing code and a manually verified TLS
fingerprint, then pins the target's SSH host key. Full ZFS streams are sent for
new assets; subsequent recovery points use incremental, resumable ZFS streams.
The target receives protected-system metadata and invokes the appliance's local
replication-received hook so recovery points remain locally discoverable.

Open `https://<appliance-IP>:9443/` and sign in with the same local administrator
username and password created during device registration. On the target,
generate a one-time code. On the source, enter the target IP, verify its TLS
fingerprint, enter that code, and choose the protected asset and replication
interval. The CLI workflow is documented in
[`docs/peer-replication.md`](docs/peer-replication.md).

Only TCP 9443 (pairing/status) and TCP 22 (encrypted backup streams) are used.
For different sites, expose them only across a site-to-site VPN and restrict
them to the two appliance addresses. Internet connectivity is not required.

## Fully air-gapped install

Copy this repository and `spf-datto-setup.tar` to the VM, then run:

```bash
./install.sh --bundle /path/to/spf-datto-setup.tar --check
./install.sh --bundle /path/to/spf-datto-setup.tar
```

All package and registration steps then run without network access. Apt uses
only the bundle's local repository and pip uses only vendored wheels.

Each installed VM generates its own local TLS key and certificate. The source
appliance's web and log-shipping identities, active factory password hashes,
and configuration for excluded telemetry agents are not included.

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
- `setup/prune-packages.txt` is the reviewed source-appliance-only exclusion list.
- `tools/make-bundle.sh` builds and validates the sanitized payload from the
  package export; `tools/sanitize-datto-package.py` removes embedded identity.

The payload still contains proprietary/repacked appliance packages and selected
configuration files. Keep the repository and release private and treat the
payload as sensitive even though source-appliance credentials are removed.
