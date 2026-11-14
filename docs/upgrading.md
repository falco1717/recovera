# Recovera package and image upgrades

Recovera uses two signed release formats. **Package releases are the normal
update path** and contain only changed application `.deb` files. **Image
releases are reserved for Ubuntu base, kernel, bootloader, ZFS, and other major
platform transitions.** Both use the same reviewed channel, monotonic sequence,
Ed25519 trust root, and GitHub Release storage.

## Routine package releases

Schema-2 package releases are offline-complete and transactional. The signed
manifest describes the channel's current application package set, like an APT
repository snapshot. An appliance compares that index with installed versions
and downloads only packages that differ, so it may safely skip intermediate
releases without downloading unchanged packages.

- APT receives only the verified local release files; repository access and
  downloads are disabled.
- The transaction is simulated first, and any proposed package removal aborts.
- Package name, version, architecture, size, and SHA-256 are compared with the
  signed manifest and the `.deb` control data.
- Kernel, GRUB, shim, initramfs, systemd, libc, and ZFS packages are rejected;
  those changes must use an image release.
- Exact prior packages are copied from the original installer or Recovera
  cache before any change. Missing rollback material aborts safely.
- Installed versions, Apache configuration, and required services are checked.
  Failure reinstalls the prior packages automatically.
- A reboot-required package release stays pending until post-boot validation.

Build from a directory containing the channel's complete current application
package set and all offline dependencies. Release storage contains that package
snapshot, while each appliance downloads only its changed subset:

```bash
tools/build-package-release.sh \
  --packages /srv/recovera-current-debs \
  --version 0.7.1 --sequence 2 --channel stable \
  --output /srv/recovera-release-0.7.1 \
  --signing-key /secure/recovera-upgrade-signing-key

tools/publish-package-release.sh /srv/recovera-release-0.7.1 0.7.1 2 stable
```

Use `--reboot-required` only when necessary. Review the publisher's JSON and
merge it into `upgrade/channels/stable.json`; uploading assets alone does not
expose a release. Successful packages are retained in
`/var/cache/recovera-upgrade/packages`, transactions in
`/var/lib/recovera-upgrade/transactions`, and the original baseline remains in
`/opt/recovera/debs`.

Fresh installer bundles include `recovera-appliance` as a versioned package so
its files have a rollback baseline from the beginning. An older development
appliance must install the matching baseline package through
`setup.sh install-updater` before its package channel is enabled; the updater
refuses to treat the control plane as an untracked new package.

## Platform image releases

Recovera uses signed, versioned root images published as GitHub Release assets.
The data pool and appliance-specific configuration stay outside the root image.
An update is downloaded into an inactive image, verified, and selected for one
boot. It becomes the default only after its services pass post-boot validation.

Current conventionally installed development appliances can check signed
manifests, but cannot activate an image. This is deliberate: the final OVA will
provision `/host`, the GRUB loop-image integration, and
`/etc/recovera/image-layout.json`. Until that marker exists, `install` fails
before downloading or changing boot state.

The layout marker also records `boot_root_uuid`, the UUID of the conventional
root containing the GRUB configuration and environment. When an appliance is
running from a loop image, staging, commit, and rollback mount that boot root
explicitly so all three operations update the files firmware actually reads.

## Moving an existing appliance to a new Ubuntu release

From Recovera 0.6.39 the upgrade is delivered like any other release, through
the update gateway, and an administrator only approves it:

1. Build the image once with `--channel jammy-noble-transition
   --also-channel jammy-noble-candidate-transition`, sign it, and publish it
   on the candidate channel first; a test appliance whose token lists that
   channel (and whose `TRANSITION_CHANNEL` names it) runs the whole upgrade
   through both gateways. Then point `jammy-noble-transition`
   (`upgrade/channels/jammy-noble-transition.json`) at the **same release**.
   Appliances never install from either channel on their own.
2. On each appliance, **Configure → Device → Operating System Upgrade** shows
   the available upgrade, its download size and a readiness checklist (starting
   release, Recovera version, pool health, disk space, replication, restores).
3. **Install in the next update window** approves it; **Install now** starts it
   at once in its own `recovera-os-upgrade` unit. Either way it then runs
   unattended (`recovera-upgrade install-transition`): it converts the boot
   layout if needed, pauses replication and waits up to three hours for running
   transfers (otherwise it releases the hold and retries in the next window),
   downloads and verifies the image from the gateway, and reboots into it.
   Image parts are kept in `/host/recovera/downloads/image-<sequence>-<digest>`
   until the image is staged. An interrupted download (a dropped connection, a
   gateway restart, a power cut) resumes each part from where it stopped, from
   either gateway, and each part's SHA-256 is checked before it is used.
4. The new system boots once and becomes the default only after validation. A
   failure or crash returns the appliance to its previous system and clears the
   approval, so it does not retry until approved again. The page shows the last
   attempt.

The command-line equivalents are `recovera-upgrade check-transition`,
`approve-transition --version V [--start now]`, `cancel-transition` and
`install-transition`. The manual procedure below remains available.

### Manual procedure

An appliance installed from the OVA runs from a conventional ext4 root. It can
still move to a new Ubuntu release (22.04 to 24.04) without a hypervisor
snapshot, because the new release arrives as a loop image and the 22.04 root
is never modified:

1. **Prepare the layout once** (Recovera 0.6.37 or newer). This changes nothing
   about the next boot: the conventional GRUB entry stays the default and is
   recorded as the fallback.

   ```bash
   sudo recovera-upgrade prepare-image-layout --dry-run
   sudo recovera-upgrade prepare-image-layout
   ```

   It bind-mounts the root filesystem at `/host` (an `/etc/fstab` line), moves
   the updater state from `/host/recovera` to `/recovera` on the same
   filesystem (the same path through the bind), installs the GRUB image menu
   script, writes `/etc/recovera/image-layout.json` with the root UUID and the
   `gnulinux-simple-<uuid>` fallback entry, and sets that entry as the saved
   default. `revert-image-layout` undoes it while no image is staged.
2. **Drain replication** so no transfer is cut by the reboot:
   `sudo recovera-peer maintenance on --reason "OS transition" --wait 21600`.
3. **Install the transition image** from its own channel. Transition images
   are never published on `stable`, and the automatic update window never
   passes `--channel`:

   ```bash
   sudo recovera-upgrade check --channel jammy-noble-transition
   sudo recovera-upgrade install --channel jammy-noble-transition --reboot
   ```

   Before downloading anything, the updater requires the starting Ubuntu
   release and minimum Recovera version named in the signed manifest
   (`from`), a healthy `homePool`, paused and idle replication, no restore
   virtual machines or iSCSI targets, and room on the root disk for the
   compressed and uncompressed image. `--allow-busy` skips only the
   replication and restore checks.
4. The appliance boots the 24.04 image **once**. If Apache, PHP-FPM and
   Recovera replication come up, the validation service makes it the default.
   Otherwise, and after any crash or reset before validation, the next boot is
   the untouched 22.04 installation. `sudo recovera-upgrade rollback --reboot`
   returns to 22.04 later on request.
5. On 24.04 the `stable` channel is read as `noble-stable`. End the hold with
   `sudo recovera-peer maintenance off` (a reboot also clears it).

The image carries this appliance's identity and configuration from the 22.04
root (see the migration list above), including `/var/lib/datto`,
`/etc/zfs/zpool.cache` and `/etc/hostid` so `homePool` imports without `-f`.
Its `/etc/fstab` root line is rewritten to the image label. Administrator-made
`/etc/sudoers.d` rules (root-owned files not installed by a package, such as a
rule for `backup-admin`) are carried with the local accounts; each must pass
`visudo -c`, otherwise it is left behind and the migration says so.
cloud-init's `90-cloud-init-users` is not carried.

Recovery points, logs and configuration changed while running the image stay
in `homePool`, but a fallback to 22.04 uses the 22.04 copy of `/datto/config`
from before the transition. Both releases use the same OpenZFS 2.2 kernel
module, so the pool imports on either.

## Appliance commands

The updater is `recovera-upgradectl`; `recovera-upgrade` is the same program.

```bash
sudo recovera-upgradectl status                          # phase, current / target / rollback versions
sudo recovera-upgradectl check
sudo recovera-upgradectl query --channel noble-stable    # what a channel offers
sudo recovera-upgradectl query --alias 0.6.45-noble.1    # which channel offers a version
sudo recovera-upgradectl upgrade 0.6.45-noble.1 --dry-run   # every check and the plan; changes nothing
sudo recovera-upgradectl download 0.6.45-noble.1         # fetch and verify an image only
sudo recovera-upgradectl stage 0.6.45-noble.1            # stage it for the next boot
sudo recovera-upgradectl upgrade 0.6.45-noble.1 --reboot
sudo recovera-upgradectl install                         # the channel's latest release
sudo recovera-upgradectl rollback
```

`stage` and `upgrade` of an operating-system transition count as the
administrator's approval and run the same unattended flow (replication paused
and drained first). `upgrade --dry-run` exits 0 when ready and 3 when blocked,
listing each blocker. See [the architecture document](image-update-architecture.md)
for the update phases.

The hourly timer checks for availability while the configured Update Window is
open and the Update Channel is set to Stable. When a newer signed release is
available, it installs automatically. If the signed manifest requires a reboot,
the appliance reboots within the configured window. The WebUI's Update Now
section remains available for an immediate administrator-initiated update.
For a private repository, place a fine-grained,
read-only GitHub token in `/etc/recovera/github-token`, owned by root with mode
`0600`. The token needs only read-only repository **Contents** access.
An interactive GitHub CLI login is not required. See
[private updates without a hosted gateway](private-updates.md) for token and
manual signed-update procedures.

An image is accepted only when all of these checks pass:

- The manifest has a valid Ed25519 signature from the pinned Recovera key.
- The channel pointer, signed manifest, architecture, version, and monotonic
  release sequence agree.
- Every GitHub asset part, the recombined compressed file, and the decompressed
  image match their SHA-256 values and sizes.
- The ext4 filesystem is clean and its embedded release identity matches.
- The image contains its kernel, initramfs, and upgrade client.

After base-image verification, a constrained migration step copies this
appliance's registration, TLS and SSH identity, network configuration,
administrator accounts, Recovera replication configuration, device state
(`/var/lib/datto`), firewall zones, share accounts, the ZFS pool cache and
host ID into the inactive candidate. It does not copy recovery points, logs, caches, package
state, or arbitrary root files. The candidate filesystem is checked again after
this migration.

After staging, GRUB boots the candidate exactly once. The prior image remains
the default. When Apache, PHP-FPM, and Recovera replication are active, the
validation service commits the candidate as the default. A validation failure
selects the previous image and reboots. A kernel-level failure also falls back
on the next reset because the candidate was only a one-time GRUB selection.
During the first conversion from a conventional installation, the image-layout
marker records that installation's GRUB entry as the fallback until the first
candidate has passed validation.

The signing private key is not in Git and must not be named or located in
public release documentation. Back it up into an access-controlled secret
store before publishing a production image. Losing it prevents new releases;
exposing it requires the rotation or recovery procedure in
[release security and key rotation](release-security.md).

## Release format

Each `image-v<version>` GitHub Release contains:

- `recovera-image-manifest.json`
- `recovera-image-manifest.json.sig`
- one or more `recovera-<version>.img.xz.part-NNN` assets

The image is split so large appliances do not depend on a single oversized
GitHub asset. `upgrade/channels/stable.json` is the small channel pointer. A
release is not discoverable until that reviewed pointer is merged.

## Build and publish

Build from a clean, fully configured root tree rather than a live production
appliance containing customer state:

```bash
sudo tools/build-upgrade-image.sh \
  --root /srv/recovera-image-root \
  --version 0.7.0 --sequence 1 --channel stable \
  --output /srv/recovera-release-0.7.0 \
  --signing-key /secure/recovera-upgrade-signing-key
```

The builder defaults to XZ level 6. A validation build may use
`--compression-level 1` to shorten the build without changing the signed
manifest, hash-verification, staging, or boot workflow; production releases
should retain the default unless storage and build-time measurements justify a
different level.

After minimizing the ext4 filesystem, the builder expands it with 2 GiB of
writable headroom. This is required for appliance-specific configuration
migration, initramfs regeneration, package metadata, and a small future update;
the empty blocks compress to almost nothing in the release asset.

The signing key is optional during the image-build step. Omitting
`--signing-key` produces the image parts and manifest without a signature so a
build appliance never needs access to the release private key. Copy only the
manifest to the isolated release workstation, sign it there with
`ssh-keygen -Y sign -f /secure/recovera-upgrade-signing-key -n recovera-upgrade
recovera-image-manifest.json`, and return only the resulting `.sig` file to the
release assets.

The builder creates an ext4 root image, installs the loop-root initramfs logic,
shrinks it, compresses it with XZ, splits it, creates SHA-256 metadata,
and signs the manifest using the `recovera-upgrade` SSH signature namespace.

After importing and testing the image locally, create and push the matching Git
tag, then publish the assets:

```bash
tools/publish-upgrade-release.sh /srv/recovera-release-0.7.0 0.7.0 1 stable
```

Review the printed channel pointer and merge it into
`upgrade/channels/stable.json`. Never reuse a sequence number or replace assets
on a published image release.
