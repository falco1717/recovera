# Changelog

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
