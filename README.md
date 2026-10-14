# Recovera

Recovera is a self-hosted backup and recovery appliance for Ubuntu. It provides
local system protection, recovery-point management, and encrypted replication
between paired Recovera appliances. Registration, administration, backup, and
replication can operate without Internet access.

## Requirements

- Ubuntu 22.04 LTS on an amd64 system
- 8 GB RAM minimum; allocate more for larger recovery workloads
- A user account with `sudo` access
- Approximately 12 GB of free space on the system disk
- A blank secondary disk of at least 20 GB for backup storage
- Hardware virtualization, including nested virtualization when running in a VM

## Install on Ubuntu

```bash
gh auth login
gh repo clone falco1717/recovera
cd recovera
./install.sh --check
./install.sh
```

The preflight check is optional but recommended. The installer validates the
host, downloads the pinned private release payload, verifies its checksum, and
completes setup automatically. Installation continues in the background if the
SSH connection closes and the appliance reboots when setup is complete.

After the reboot, browse to:

```text
https://<appliance-ip>/
```

Complete the local registration wizard and sign in with the administrator
account created during registration.

## Deploy the virtual appliance

A prebuilt OVA can be imported into VMware vCenter or ESXi. Select the target
datastore and network, power on the VM, and use the DHCP address displayed on
the console to open the registration page.

Each deployed appliance generates unique machine, SSH, TLS, storage, device,
peer, and administrator identities before network services become available.
See [OVA deployment](docs/ova.md) for detailed import and validation guidance.

## Appliance access

Setup creates a local `backup-admin` account with `sudo` access. Its random
password is generated once and remains stable until an administrator rotates
it. The password is available after registration under
**Configure → Appliance Access**.

Password-based SSH access is restricted to this account. Other accounts
continue to require SSH keys.

## Appliance replication

Recovera can replicate recovery points directly to another Recovera appliance:

1. Open **Configure → Off-site Target** on the destination appliance.
2. Generate a one-time pairing code.
3. On the source appliance, enter the destination IP address.
4. Verify the displayed TLS fingerprint and submit the pairing code.
5. Select the authorized target under
   **Protect a System → Replication & Retention**.
6. Choose the replication schedule and target retention period.

Replication uses HTTPS on TCP 443 for pairing and status, and SSH on TCP 22 for
encrypted, resumable ZFS streams. Use a site-to-site VPN when appliances are in
different locations and restrict access to the paired appliance addresses.

**Configure → Off-site Synchronization** controls replication windows and
the upload-speed limit. Additional operational details are available in
[appliance replication](docs/peer-replication.md).

## Fully offline installation

Copy the repository and its prepared installation bundle to the Ubuntu system,
then run:

```bash
./install.sh --bundle /path/to/offline-bundle.tar --check
./install.sh --bundle /path/to/offline-bundle.tar
```

The bundle supplies the local package repository and vendored Python
dependencies, so installation and registration do not require Internet access.

## Configuration and maintenance

- Edit `setup/setup.conf` before installation to customize networking, storage,
  or reboot behavior.
- Re-running the installer safely resumes an interrupted setup and skips
  completed phases.
- Review [upgrades and rollback](docs/upgrading.md) before updating an appliance.
- Maintainers should follow the [release checklist](docs/releasing.md).

## Security

- Pairing codes are single-use.
- Target TLS fingerprints are verified before pairing.
- SSH host keys are pinned for replication.
- The internal peer API uses a restricted Unix-domain socket.
- No additional public replication port is required.
- Appliance credentials and private keys are generated independently on every
  installation.

Keep the repository and release payload private. Confirm that you have the
necessary rights to use and distribute all packaged software in your
environment.
