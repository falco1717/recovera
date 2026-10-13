# Recovera virtual appliance

The Recovera OVA contains a complete, unregistered Ubuntu 22.04 appliance. It
is an alternative to running `install.sh` on an existing VM; both deployment
paths produce the same application and offline registration workflow.

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
clone-sensitive data and logs, installs the one-time initializer, and tells you
when preparation is complete. Power the VM off immediately and export it
without booting it again. Booting the prepared builder consumes its one-time
initializer and makes it unsuitable for export until it is prepared again.

Always import the resulting OVA twice and verify that the two instances report
different peer appliance IDs and TLS fingerprints. Complete registration on a
validation instance, confirm **Appliance Access** reveals its credential, test
SSH and sudo with that credential, run `sudo /opt/spf-datto/setup.sh verify`,
and compare the checksum with the published SHA-256 value.
