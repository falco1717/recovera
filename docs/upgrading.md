# Image upgrades and rollback

Recovera uses signed, versioned root images published as GitHub Release assets.
The data pool and appliance-specific configuration stay outside the root image.
An update is downloaded into an inactive image, verified, and selected for one
boot. It becomes the default only after its services pass post-boot validation.

Current conventionally installed development appliances can check signed
manifests, but cannot activate an image. This is deliberate: the final OVA will
provision `/host`, the GRUB loop-image integration, and
`/etc/recovera/image-layout.json`. Until that marker exists, `install` fails
before downloading or changing boot state.

## Appliance commands

```bash
sudo recovera-upgrade status
sudo recovera-upgrade check
sudo recovera-upgrade install
sudo recovera-upgrade install --reboot
```

The daily timer only checks for availability. It never downloads, installs, or
reboots automatically. For a private repository, place a fine-grained,
read-only GitHub token in `/etc/recovera/github-token`, owned by root with mode
`0600`. The token needs only repository Contents and Releases read access.

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
administrator accounts, and Recovera replication configuration into the
inactive candidate. It does not copy recovery points, logs, caches, package
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

The signing private key is not in Git. It is currently stored on the maintainer
workstation at `F:\Users\jfarmer\Documents\Recovera Secrets\recovera-upgrade-signing-key`.
Back it up into an access-controlled secret store before publishing the first
production image. Losing it prevents new releases; exposing it requires a
public-key rotation delivered through an already trusted release.

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
