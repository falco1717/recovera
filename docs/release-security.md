# Release security and signing-key lifecycle

Recovera treats the release-signing key as the authority for appliance code.
GitHub, an update mirror, or a network attacker may withhold or replay files,
but an appliance accepts a new release only when its manifest is signed by a
trusted Recovera key and its monotonic sequence and asset digests validate.

## Key custody

- Keep the active private key off appliances, OVAs, build images, GitHub,
  Actions, installer payloads, and ordinary development workstations.
- Store it in an encrypted secret manager or encrypted removable medium used
  only on the isolated release workstation. Keep one separately encrypted,
  offline backup and test restoration at least annually.
- Generate a distinct offline recovery key before production distribution.
  Add only its public key to `upgrade/keys/recovera-release-signers`; never put
  either private key in this repository.
- Record who authorized each signature, the source commit, manifest SHA-256,
  tag, CI URL, and independent verification result.
- Never reuse GitHub access credentials as signing credentials.

Run an independent local audit before publication:

```bash
python3 tools/verify-release.py \
  --directory /srv/recovera-release-0.7.0 \
  --manifest recovera-package-manifest.json \
  --signers upgrade/keys/recovera-release-signers
```

For image releases, supply the image manifest name and
`--verify-uncompressed` to validate both the split compressed stream and its
uncompressed filesystem digest.

## Planned key rotation

The allowed-signers format supports multiple public keys for the same
`recovera-release` identity. Rotate keys in three separately reviewed releases:

1. **Bridge release:** sign with the old key and add the new public key beside
   the old public key. Do not use the new key yet.
2. **Overlap release:** after the bridge release is installed broadly, sign
   with the new key while both public keys remain trusted. Verify rollback and
   update installation on appliances from every supported starting version.
3. **Retirement release:** sign with the new key and remove the old public key.
   Retain the old public key and release records in the security archive, not
   in the appliance trust file.

The package containing a changed signer list must itself be accepted under the
trust state that existed before installation. Never replace the key and signer
list in a single release that old appliances cannot authenticate.

## Compromise and recovery

A pre-staged recovery key is the only unattended way to recover trust after
the active signing key is compromised. Stop publishing, remove the compromised
operator's GitHub access, and freeze the stable channel. Use the offline
recovery key to publish a higher-sequence release that removes the compromised
public key and installs a new active public key. Appliances that never received
the recovery public key must be repaired using a manually delivered, locally
verified recovery package; they must not trust a network update signed by the
compromised key.

If GitHub or an update host is compromised but the signing key is safe, do not
rotate the signing key automatically. Disable publication, compare immutable
tags and locally archived manifests, restore the release assets, and resume
only after an independent signature and checksum audit.

## Retention and immutability

- Never overwrite a release asset, manifest, signature, or tag. Publish a new
  version and a higher monotonic sequence.
- Retain all package releases still referenced by supported installations and
  the exact prior packages needed for rollback.
- Keep release tags protected from update and deletion.
- Store an offline copy of manifests, signatures, packages, checksums, release
  notes, and CI evidence for every production release.
