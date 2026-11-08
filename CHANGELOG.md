# Changelog

## v0.6.34 - 2026-11-07

- Faster replication over WAN links: the package enables BBR congestion control
  (sysctl drop-in, `tcp_bbr` loaded at boot). On a 133 ms, ~0.7%-loss link the
  default CUBIC had collapsed to ~100 KB/s; BBR sustains ~3.4 MB/s.
- New full and incremental replication streams use `zfs send -c`, sending blocks
  as already compressed on disk. Resumed streams keep their original format, and
  their progress is now measured from the resume token (bytes already received
  plus `zfs send -nP -t` remaining), so totals stay exact either way.
- Cloud isolation retires leftover SpeedSync (vendor off-site) registrations for
  datasets that no longer exist or whose asset is set to no off-site
  replication. Their one-minute cron otherwise queried the blocked vendor master
  server for them and logged about 1,200–1,700 errors an hour. `speedsync remove`
  cannot finish offline (it needs the master to acknowledge), so the registration
  folder is moved to `/datto/config/recovera-speedsync-unregistered/`, which keeps
  it restorable. Registrations are never judged missing unless the agent dataset
  root is visible.

## v0.6.33 - 2026-11-07

- **Configure → Networking → Run Outbound Connectivity Check** now runs
  Recovera's own check instead of probing vendor endpoints (heartbeat, off-site
  cloud, speedtest and update servers, BMC) that an offline appliance must not
  contact. It tests the default gateway, unfragmented 1472-byte packets, DNS
  and reachability of the update source, time synchronization, and HTTPS/SSH
  to every paired target and HTTPS to every paired source, in parallel. The
  page shows Recovera's last result, adds failure details on hover, and drops
  the vendor knowledge-base link.
- Appliances now advertise their current device name (the hostname set by
  **Name the Device**) instead of the first-boot name ("recovera" on OVA
  deployments), and refresh each other's stored names on every transfer, so a
  target shows its source by its real name.
- Documented replication monitoring, the background **Synchronize now**, and
  the new connectivity check in `docs/peer-replication.md`.

## v0.6.32 - 2026-11-07

- The Synchronize page's replication panel shows an animated progress bar when
  a transfer's total size is unknown (for example a transfer started before the
  sending appliance reported its size estimate), instead of a static, faded
  full-width bar that looked idle. The amount now reads "received so far" and
  notes that the total was not reported for that transfer. Users who prefer
  reduced motion see a static bar.

## v0.6.31 - 2026-11-07

- Includes all 0.6.30 changes (background **Synchronize now** and total
  progress for resumed transfers); 0.6.30 was published but not promoted.
- The updater suspends Ubuntu's `needrestart` hook during package installs and
  rollbacks. needrestart restarts services whose Python scripts apt replaced,
  which could restart `recovera-peer-sync.service` in the middle of a long
  replication. Recovera already restarts its own services after an update.
  This protects the updates that follow 0.6.31; the 0.6.31 install itself is
  performed by the previously installed updater.

## v0.6.30 - 2026-11-07

- **Synchronize now** (Configure → Off-site Target) starts replication in the
  dedicated `recovera-peer-sync.service` and returns immediately, instead of
  running the whole transfer inside the WebUI's `recovera-peer.service`. A
  multi-day seed started from that button was cut off whenever the web
  service restarted, such as after an update. The scheduled sync service is
  not restarted by updates, and progress is shown on the Synchronize page.
- The receiving appliance now shows total progress for a resumed transfer:
  the bytes already received (read from the ZFS `receive_resume_token`) plus
  the current run, instead of restarting the count at zero.
- The sending appliance passes its stream-size estimate with the replication
  metadata, so the receiving appliance can show percentage and time remaining.

## v0.6.29 - 2026-11-07

- The native **Synchronize** page now shows Recovera appliance-to-appliance
  replication, which runs outside SpeedSync and was previously invisible
  there. A live panel lists each active transfer in either direction with the
  protected system, the paired appliance (name and address), recovery point,
  transfer type, bytes moved, total size and percentage when known, current
  speed, and estimated time remaining, plus interrupted transfers and the last
  completed or failed replication per asset. It refreshes every five seconds.
- `recovera-peer` records in-flight sends and receives and serves them at the
  admin-only `/v1/admin/replication-activity` endpoint. Progress is read from
  the `zfs send`/`zfs receive` process I/O counters, so the replication stream
  itself is unchanged. Transfers started by older versions are discovered too,
  and a resumed send counts the bytes already on the target.

## v0.6.28 - 2026-11-07

- Backup-storage expansion now reconciles an already-expanded GPT with the
  kernel's stale partition view using `partx`, allowing expansion to continue
  when `growpart` changed the disk successfully but reported an `lp_update`
  failure for the live ZFS partition.
- Appliances with multi-device or otherwise unsupported `homePool` layouts now
  show a disabled, explanatory **not eligible** state instead of repeatedly
  displaying a red "exactly one data device" status error.

## v0.6.27 - 2026-11-07

- Fixed backup-disk expansion failing with `Read-only file system` when writing
  the SCSI rescan control. Rescans now run through a short-lived systemd unit
  that exposes only the validated disk's rescan file as writable, preserving
  the stricter kernel-tunable sandbox on the long-running Recovera WebUI
  service.

## v0.6.26 - 2026-11-07

- Added **Configure → Device → Expand Backup Storage**. The authenticated UI
  rescans the dedicated backup disk and expands the single-disk `homePool` ZFS
  volume to all newly assigned virtual-disk capacity without deleting or
  recreating existing backups.
- Storage expansion validates that the pool is ONLINE, refuses the operating
  system disk and unsupported multi-device/partition layouts, serializes
  concurrent requests, saves a private GPT backup before changing the
  partition table, and enables future ZFS auto-expansion.

## v0.6.25 - 2026-11-06

- The global update banner now compares the cached release with the installed
  package and sequence, and package installation clears the cached available
  release. An already-installed update is no longer advertised indefinitely.
- Protect-a-System removes duplicate agent or VM selections by stable identity
  before submitting the native pairing request, while preserving different VMs
  that happen to share a display name.
- Added mutually authenticated agent ownership transfer. Updated Linux agents
  can be released safely by their owning appliance before removal, allowing a
  replacement Recovera appliance to pair them without manually editing the
  agent database. Active backup snapshots block release, the database is backed
  up first, and forced/offline removal shows an explicit recovery path.

## v0.6.24 - 2026-11-06

- Protect-a-System now translates the agent's otherwise opaque
  `:25567/pair: Empty reply from server` failure into an actionable explanation:
  the agent rejected this appliance's certificate, normally because it is
  already paired with another Recovera appliance or uses a different pairing
  CA. The message explains that an agent can be protected by only one appliance
  and directs administrators to Off-site Target replication for the second
  appliance.

## v0.6.23 - 2026-11-06

- Added **Off-site Target** and **Appliance Access** reliably to both desktop
  and mobile Configure menus. The branding patch now tolerates navigation and
  whitespace changes between appliance image versions instead of depending on
  one exact stock-template layout.
- Added regression coverage that renders representative desktop and mobile
  Configure dropdowns and verifies both Recovera links are present exactly
  once.
- Pairing now ignores obsolete `ssh-dss` host keys advertised by older target
  appliances while still requiring and pinning at least one supported modern
  key, fixing the "target returned an invalid SSH host key" error with 0.6.12
  targets.
- The peer discovery API now reports the installed Recovera package version
  instead of the stale hard-coded 0.6.12 value.

## v0.6.22 - 2026-11-04

- Protect-a-System wizard: when no replication peer is paired, the
  "Target Recovera appliance" option is now grayed out and disabled (replacing
  the empty-state note), with an info (i) icon whose tooltip explains how to
  pair a target under Configure → Off-site Target.
- Registration: after a freshly deployed appliance is named and registered, it
  now checks for and installs any signed Recovera update before finishing, so
  new deployments start current instead of waiting for the nightly window.

## v0.6.21 - 2026-11-04

- Protect-a-System wizard: the per-asset Recovera replication policy editor was
  appended unconditionally to `Assets/Configure/cloud.backup.html.twig`, so it
  also rendered inside the Set Replication & Retention wizard step as a second,
  always-on form stacked on the native No-Replication/Target toggle — shown even
  under "No Replication". Guarded it with `{% if not inWizard %}` so it only
  appears on the per-asset Configure page; the wizard now uses the native
  replication step (relabeled, peer-populated and save-hooked by
  `RecoveraProtectSystem.js`), matching native SIRIS behavior.
- Protect-a-System wizard: when "Target Recovera appliance" is selected with no
  replication peer paired, the native empty-state message was hidden inside the
  collapsed target container, leaving a blank area. Added a visible note that
  explains a target must be paired under Configure → Off-site Target.

## v0.6.20 - 2026-10-18

- Replaced the retained vendor NTP configuration with Recovera-managed neutral
  time sources (`time.cloudflare.com` and `ntp.ubuntu.com`) and public pool
  fallbacks.
- Added the retired vendor NTP hostname to the legacy-cloud isolation blocklist
  and restart time synchronization when the policy is applied.

## v0.6.19 - 2026-10-18

- Disabled the legacy remote Partner Portal relay client after live packet
  captures confirmed it was still sending periodic HTTP heartbeats to Datto.
- Blocked all six observed Datto relay-tracker hostnames as a second isolation
  layer while preserving local SSH, console access, and Recovera replication.

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
