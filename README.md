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

The installer creates a local `backup-admin` account with `sudo` access. Its
random password is generated once and does not expire or rotate automatically.
An authorized administrator can reveal it at **Configure → Appliance Access**,
or from the appliance console with `sudo recovera-backup-admin show`. The page
does not cache the credential. Rotate it only when required with
`sudo recovera-backup-admin reset`; the UI immediately shows the new value.

## Deploy the virtual appliance

The release OVA is the fastest deployment path when a suitable Ubuntu VM does
not already exist. Import it into vCenter or ESXi, select the destination
network and datastore, and power it on. The image uses DHCP on first boot and
then opens the same offline registration wizard at `https://<VM-IP>/`.

Every OVA deployment creates its own machine ID, SSH host keys, browser TLS
certificate, ZFS pool GUID, Recovera peer identity, device ID, and
`backup-admin` password before network-facing services start. No builder login
key, registration, protected system, recovery point, pairing relationship, or
credential is embedded in the image. See [`docs/ova.md`](docs/ova.md) for import,
verification, and image-maintainer instructions.

## Offline appliance replication

The installer also provides SIRIS-Private-style replication between Recovera
appliances. It uses a one-time pairing code and a manually verified TLS
fingerprint, then pins the target's SSH host key. Full ZFS streams are sent for
new assets; subsequent recovery points use incremental, resumable ZFS streams.
The target receives protected-system metadata and invokes the appliance's local
replication-received hook so recovery points remain locally discoverable.

Sign in to the normal Recovera WebUI and open **Configure → Off-site Target**.
On the target, generate a one-time code. On the source, enter the target IP,
verify its TLS fingerprint, and enter that code. The paired appliance then appears
as an authorized target in **Protect a System → Replication & Retention**, where
you select the destination, replication frequency, and target-side retention.
The Off-site Target page can also create or revise a policy after protection.
**Configure → Off-site Synchronization** controls the weekly replication windows
and upload-speed limit. The CLI workflow is documented in
[`docs/peer-replication.md`](docs/peer-replication.md).

Individual recovery points can also be queued from the native recovery-points
page. The existing **Exists in Cloud** column is retained for SIRIS Private
compatibility: **Queued**, **Streaming**, and the completed green indicator refer
to the paired Recovera target, and the state survives normal page refreshes.

Only TCP 443 (pairing/status through the normal Recovera site) and TCP 22
(encrypted backup streams) are used. The internal peer API uses a restricted
Unix-domain socket and does not open another TCP listener. For different sites,
expose 443 and 22 only across a site-to-site VPN and restrict them to the two
appliance addresses. Internet connectivity is not required.

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
- [`docs/upgrading.md`](docs/upgrading.md) documents upgrades and rollback.
- [`docs/releasing.md`](docs/releasing.md) is the maintainer release checklist.

The payload still contains proprietary/repacked appliance packages and selected
configuration files. Keep the repository and release private and treat the
payload as sensitive even though source-appliance credentials are removed.
