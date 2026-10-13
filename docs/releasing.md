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
5. Tag the merge commit (for example `v0.5.0`) and push the tag.
6. Create a GitHub release for the tag and attach `SHA256SUMS`. The release notes
   must identify the pinned payload tag and link to the upgrade/rollback guide.
7. On two clean Ubuntu 22.04 VMs, install from the tag, pair the appliances,
   replicate a recovery point, and run `setup.sh verify` on both systems.

Consumers must verify the payload downloaded by `install.sh`; the script checks
it against `BUNDLE_SHA256` before extraction. `SHA256SUMS` additionally protects
the bootstrap script and release metadata copied outside Git.
