# Release checklist

Releases are created from a reviewed pull request into `main`. The installation
payload is private and must not be copied into the Git repository.

1. Run the unit and integration tests and confirm a clean worktree.
2. Confirm `setup/release.env` pins the intended private payload tag, asset, and
   SHA-256 digest.
3. Generate `SHA256SUMS` for the small release metadata files:

   ```bash
   sha256sum install.sh setup/release.env > SHA256SUMS
   ```

4. Open a pull request to `main`, obtain review, and merge it without bypassing
   branch protection.
5. Tag the merge commit (for example `v0.6.0`) and push the tag.
6. Create a GitHub release for the tag and attach `SHA256SUMS`. The release notes
   must identify the pinned payload tag and link to the upgrade/rollback guide.
7. On two clean Ubuntu 22.04 VMs, install from the tag, pair the appliances,
   replicate a recovery point, and run `setup.sh verify` on both systems.
8. Build an unregistered appliance, run `sudo tools/prepare-ova.sh`, power it
   off without rebooting it, and export the OVA. Import the exported OVA twice
   and confirm the deployments have different TLS fingerprints, peer appliance
   IDs, ZFS pool GUIDs, SSH host keys, and `backup-admin` passwords.
9. Publish the OVA and its SHA-256 digest as release assets when the OVA fits
   the release host's per-file limit. Never commit the binary image to Git.

## Routine appliance package release

Normal releases expose a current application package index and appliances
download only entries whose installed versions differ. Follow
[Recovera package and image upgrades](upgrading.md), then:

1. Put the channel's complete current application `.deb` set and every offline
   dependency in a clean directory. The appliance will skip unchanged files.
2. Increment the human version and the global monotonic release sequence.
3. Build the schema-2 manifest with `tools/build-package-release.sh`.
4. Sign the manifest on the isolated release workstation and verify every
   digest on a second machine.
5. Test installation and forced rollback on both disposable appliances.
6. Create the immutable Git tag and publish with
   `tools/publish-package-release.sh`.
7. Merge the reviewed stable-channel pointer only after the tests pass.

Platform, boot, kernel, libc, systemd, and ZFS packages are not valid routine
updates. Ship those through the image path.

## Appliance image release

Image updates are a separate release artifact from the installation payload,
package releases, and OVA. Follow [Recovera package and image upgrades](upgrading.md), then:

1. Increment both the human version and the monotonic image sequence.
2. Build from a clean root tree and keep all appliance identity, protected
   systems, recovery points, peer credentials, TLS keys, and GitHub tokens out
   of the image.
3. Verify the manifest signature and every digest on a second machine.
4. Boot the image as a one-time candidate on two disposable appliances.
5. Test successful commit and forced validation failure/automatic rollback.
6. Publish immutable split assets under `image-v<version>`.
7. Merge the reviewed channel pointer only after those tests pass.

The signing private key must never be copied into the repository, release
assets, installation payload, root image, or OVA.

Follow [release security and key rotation](release-security.md) for key
custody, independent verification, planned rotation, emergency recovery, and
release retention. Private-repository delivery without a gateway is documented
in [private updates](private-updates.md).

Consumers must verify the payload downloaded by `install.sh`; the script checks
it against `BUNDLE_SHA256` before extraction. `SHA256SUMS` additionally protects
the bootstrap script and release metadata copied outside Git.
