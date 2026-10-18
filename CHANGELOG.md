# Changelog

## v0.6.18 - 2026-10-18

- Isolated the remaining legacy cloud asset-reconciliation and bandwidth-
  schedule jobs discovered during the live post-0.6.17 appliance audit.
- Kept Off-Site Sync scheduling and upload-rate enforcement entirely local in
  the Recovera replication worker, which evaluates the configured schedule on
  every five-minute replication pass and before each transfer.

## v0.6.17 - 2026-10-18

- Isolated the remaining legacy network-connectivity test, automatic DDNS and
  HTTPS repair, and Apache cloud-CA refresh jobs discovered during the live
  post-0.6.16 appliance audit.

## v0.6.16 - 2026-10-18

- Isolated confirmed legacy cloud check-in, telemetry, licensing, remote
  management, VPN, and package-feed paths while preserving the complete local
  backup, restore, ZFS, Web UI, and Recovera private-replication data plane.
- Added boot-time enforcement and an administrator verification command:
  `sudo recovera-cloud-isolation verify`.

## v0.6.15 - 2026-10-17

- Changed the configured Update Window to automatically check for and install
  the latest signed build from the selected channel. Updates that require a
  reboot now reboot automatically within that window.

## v0.6.14 - 2026-10-17

- Published a no-impact maintenance release to validate authenticated appliance
  updates through the redundant Recovera gateway cluster and a private source
  repository.

## Unreleased

- Renamed Recovera-owned installer, bundle, service, state, cache, log, backup,
  and verification paths; upgrades migrate the previous layout without losing
  setup progress or the offline package cache.
- Renamed the offline installer payload to `recovera-setup.tar` and removed
  legacy branding from Recovera-owned setup documentation and helper names.
- Added signed schema-2 package repositories as the default appliance update
  path, with installed-version filtering, changed-package-only downloads, offline APT transactions, strict
  platform-package separation, cached rollback packages, service validation,
  monotonic channels, and optional post-reboot commit/rollback.
- Added package release build and GitHub publication tooling. Full root images
  remain available for kernel, bootloader, base-OS, ZFS, and recovery upgrades.
- Added a signed, image-based appliance upgrade client with GitHub Release
  channels, split image assets, layered SHA-256 verification, monotonic
  downgrade protection, one-time GRUB candidate boots, health validation, and
  automatic fallback.
- Added root-image build/sign/publish tooling while leaving the stable channel
  dormant until the final OVA supplies the required image-host layout.

## v0.6.0 - 2026-10-13

- Added a persistent local `backup-admin` account whose high-entropy password
  changes only through an explicit administrator reset.
- Added **Configure → Appliance Access** for authenticated password reveal and
  copy, backed by a non-cacheable internal API.
- Added hardened OVA preparation and first-boot initialization that remove
  builder credentials and regenerate every clone-specific machine, SSH, TLS,
  ZFS, device, replication, and administrative identity.
- Made OVA first-boot initialization independent of early-boot D-Bus services
  and forced every prepared image to re-arm the one-time initializer.
- Made clean-clone first boot create TLS before peer initialization and import
  the local ZFS pool before assigning its clone-specific GUID.
- Replaced the vendor ASCII artwork on the local VM console and SSH login
  banner with consistent Recovera branding.
- Made the global SSH password denial take precedence over Ubuntu cloud-init
  defaults while retaining the explicit `backup-admin` exception.
- Documented OVA import, validation, publication, and recovery procedures.

## v0.5.1 - 2026-10-13

- Replaced the internal loopback TCP/TLS listener on port 9443 with a
  root-owned Unix-domain socket accessible only to Apache and PHP-FPM.
- Removed obsolete peer TLS keys and the configurable internal peer port.

## v0.5.0 - 2026-10-13

- Integrated private appliance targets into the Recovera WebUI and protection
  workflow.
- Added one-time pairing, certificate fingerprint verification, pinned SSH
  transport, resumable ZFS replication, target retention, and recovery-readiness
  reporting.
- Mapped native off-site queue state to paired Recovera targets.
- Routed appliance pairing through the normal HTTPS site on port 443 and kept
  the peer API loopback-only on port 9443.
- Added replication capacity, retry, installation, and integration safeguards.
- Removed the obsolete standalone peer administration page.
