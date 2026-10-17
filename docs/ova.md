# Recovera virtual appliance

The Recovera OVA contains a complete, unregistered Ubuntu 22.04 appliance. It
is an alternative to running `install.sh` on an existing VM; both deployment
paths produce the same application and offline registration workflow.

Release OVAs must be no larger than 2,000,000,000 bytes (2 GB), which keeps a
single file under GitHub's 2 GiB release-asset limit. The validated v0.6.11
artifact is `Recovera-Virtual-Appliance-v0.6.11.ova`, 1,681,838,080 bytes
(1.566 GiB), with SHA-256
`5925B96B30A6F7C688074FCB7D82ACBAAB25B8452C6E29937FAD50F7B9122076`.
Verify the downloaded image against its published digest before import.

## Import and register

1. Import the OVA into vCenter or ESXi and choose the destination datastore and
   port group.
2. Allocate at least 4 vCPUs and 8 GB RAM. Keep the included application and
   data disks, and expose hardware-assisted virtualization to the guest.
3. Power on the VM. The first boot uses DHCP and may take several minutes while
   clone-specific identities are created.
4. Find the assigned address in vCenter or from DHCP, then open
   `https://<VM-IP>/` and complete registration.
5. Sign in and open **Configure → Appliance Access** to retrieve the stable
   `backup-admin` SSH credential.

The browser certificate is locally generated, so a certificate warning is
expected until the appliance is configured with a certificate trusted by your
environment.

## Credential behavior

`backup-admin` is a local sudo administrator intended for appliance recovery
and support. Its 28-character password is randomly generated once per deployed
VM, is stored root-only at `/etc/recovera/backup-admin.json`, and does not age or
rotate on a timer. It can be displayed locally with:

```bash
sudo recovera-backup-admin show
```

Rotate it explicitly with `sudo recovera-backup-admin reset`. Do not copy the
credential between appliances or publish it with diagnostic output.

## Clone safety

The exported image contains no registration, protected-system data, recovery
points, peer relationships, administrator password, private TLS/SSH identity,
or builder authorized key. On its first boot each deployment regenerates:

- system machine ID, SSH host keys, and host ID;
- web TLS private key and certificate;
- ZFS `homePool` GUID;
- Recovera peer keys, appliance ID, numeric device ID, and web token;
- the `backup-admin` account and password.

The first-boot service completes before SSH, Apache, and the Recovera peer
service are allowed to start.

## Maintainer build procedure

Build only from a clean, unregistered appliance with no protected systems or
peer relationships. From the repository checkout on that appliance, run:

```bash
sudo tools/prepare-ova.sh
```

The script refuses unsafe source state, stops network-facing services, removes
clone-sensitive data and logs, purges the unused 5.15 cloud kernel, drops the
`linux-firmware` payload that VMware virtual hardware never loads, rebuilds
the empty ZFS data pool, zeroes and
trims unused system-disk space, installs the one-time initializer, and tells
you when preparation is complete. Power the VM off immediately and export it
as stream-optimized VMDKs without booting it again. Booting the prepared
builder consumes its one-time initializer and makes it unsuitable for export
until it is prepared again.

If the builder's system disk is thick-provisioned, make a powered-off thin
clone after preparation and export that clone. Zero filling makes the clone
sparse; exporting the original thick disk can still force vCenter to read the
entire provisioned capacity even though the resulting VMDK is compressed.

Validate the exported artifact before publication. The check rejects images
over 2 GB, unexpected archive members, an incorrect disk count, and disks
that were not exported in VMware stream-optimized format:

```bash
tools/check-ova.sh /path/to/Recovera-VERSION.ova
```

Build from the clean Ubuntu base image. Do not use a vendor appliance image as
the redistributable base: it can contain third-party proprietary packages,
identities, or licensing state that Recovera is not authorized to publish.

Always import the resulting OVA twice and verify that the two instances report
different peer appliance IDs and TLS fingerprints. Complete registration on a
validation instance, confirm **Appliance Access** reveals its credential, test
SSH and sudo with that credential, run `sudo /opt/recovera/setup.sh verify`,
and compare the checksum with the published SHA-256 value.
