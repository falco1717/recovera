# Changelog

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
