# Changelog

## v0.6.46 - 2026-11-13

The image-update architecture work: one updater with explicit phases, a dry
run, and more safety checks. See `docs/image-update-architecture.md`.

- The updater installs as `recovera-upgradectl`; `recovera-upgrade` remains a
  link to it, so timers, the peer service and the web UI are unchanged.
- New commands: `query --channel C` / `query --alias VERSION`,
  `download VERSION`, `stage VERSION`, `upgrade VERSION [--reboot] [--dry-run]`.
  The dry run resolves the release, verifies its signature, chooses the
  artifact, runs every check, estimates download and disk space (counting any
  partial download) and changes nothing; it exits 3 when blocked.
- Update phases (`DOWNLOADING`, `VERIFYING`, `STAGING`, `READY_TO_REBOOT`,
  `REBOOTING`, `VERIFYING_BOOT`, `COMPLETE`, `FAILED`, `ROLLED_BACK`,
  `BLOCKED`) are recorded in `/host/recovera/phase.json` with the target,
  artifact and download progress, and `/run/recovera-upgrade/status.json` is
  rebuilt for the UI on every run. `AVAILABLE` and `IDLE` are derived from the
  cached checks, so a check never overwrites a staged update.
  `recovera-upgradectl status` shows the phase and the rollback version.
- New checks before an install: a backup that is not idle
  (`snapctl asset:backup:list`), dpkg/apt holding its lock, a device migration
  holding `/datto/config/migration.lock`, and a missing default route. A
  blocked operating-system upgrade is recorded as `BLOCKED` (not failed) and
  retried in the next window.
- `upgrade/schema/image-manifest.schema.json` (JSON Schema 2020-12) documents
  the image manifest, including reserved fields for release notes, key ID,
  required space, rollback target, expiry, rollout rules and deltas.

## v0.6.45 - 2026-11-13

Large-image delivery for the Ubuntu 22.04 → 24.04 transition, and two findings
from the second end-to-end test (the `0.6.44-noble.1` candidate on a paired
test appliance: transition with a transfer in flight, post-upgrade replication
both ways, and an administrator rollback to 22.04).

- **Resumable image downloads.** Parts are kept in a per-release directory
  under `/host/recovera/downloads` until the image is staged. An interrupted
  part resumes with one HTTP byte range (from either gateway); an origin that
  ignores ranges restarts only that part; a complete part with the wrong digest
  is discarded. A dropped connection is now a retryable error, so the updater
  moves on to the other gateway instead of stopping. The verified parts stream
  straight into `xz` (no combined copy), so a power cut during decompression
  does not need a new download.
- **Gateway:** release assets honour one byte range per request (206/416,
  never multi-part); the cache is checked for space before a release is
  downloaded; a verified release is re-hashed only when its files change;
  releases no channel uses are removed after a fully successful sync (each
  channel keeps one previous release, `RECOVERA_GATEWAY_KEEP_PREVIOUS`); and
  `recovera-gateway status` reports each channel's cached release, last
  success and error, and free cache space.
- The OS transition carries administrator-made `/etc/sudoers.d` rules (for
  example a `backup-admin` rule) along with the local accounts, when they are
  root-owned, not from a package and pass `visudo`. cloud-init's
  `90-cloud-init-users` rule for the cloud image's default account is not
  carried: the image disables cloud-init and locks that account.
- After a reboot ends a maintenance hold, the replication event log records
  that replication resumed instead of ending on "paused for maintenance".
- A failed validation of an operating-system image now clears the staged
  image from the updater state. The appliance already returned to its previous
  system, but the stale entry made `cancel-transition` (and the UI) treat the
  upgrade as still staged. Found by forcing a validation failure (Apache
  unable to start) on the test appliance, which otherwise fell back correctly.
- If the one-time boot of a staged image never reaches validation (power loss,
  reset or crash), the previous system now records the attempt as interrupted
  and clears it on its next boot. It used to treat this as a failed validation
  of itself and reboot once more.

## v0.6.44 - 2026-11-13

Fixes from the first end-to-end Ubuntu 22.04 → 24.04 transition on a test
appliance (Recovera-Builder): the unattended upgrade completed, the 24.04 image
passed validation with its hostname, host ID, MAC/IP, time zone, registration
and pool intact, and the GRUB fallback returned it to the untouched 22.04 root.

- `recovera-upgrade rollback` on the first image now boots the previous system.
  It used to find the 22.04 package transaction still in the shared state and
  try to reinstall packages whose files exist only on the 22.04 root. Staging an
  image clears that transaction, and a boot rollback records the previous system
  as installed and ends the transition approval.
- The image keeps its own software-version markers (`/datto/config/os2Version`,
  `sirisUIVersion`, `syncVersion`); the migration had overwritten 5.12.2 with the
  22.04 appliance's 5.6.3.
- Image builder: copies a separately mounted `/boot` (Ubuntu 24.04 cloud images
  keep the kernels there, so the first build had none), leaves out files under
  `/home` (the backup pool's mountpoint) and the builder's journal and apt
  archives, and keeps only `recovera-appliance` from the 2 GB offline installer
  package set.
- Readiness checks that pass now say so instead of showing their failure text.

## v0.6.43 - 2026-11-13

- The operating-system image migration also carries NetworkManager's
  `secret_key` (with the already-carried machine ID it determines `br0`'s
  stable cloned MAC address, so the appliance keeps its MAC and DHCP lease),
  the time zone (`/etc/localtime`, `/etc/timezone`) set at registration, and
  time-synchronization settings.

## v0.6.42 - 2026-11-13

Fixes found installing the current 5.12.x bundle over an existing Ubuntu 24.04
appliance.

- The web layout is detected from a stock 5.6.x template
  (`templates/commonlookandfeel/Default/layout.base.html.twig`) instead of the
  `commonlookandfeel/` directory. A 24.04 test appliance running a pre-0.6.36
  updater had pulled a 22.04 release, whose branding created Recovera-only
  `commonlookandfeel/` trees before the install rolled back; later 24.04
  package installs then took the 5.6.x paths and failed. On the flat layout,
  such Recovera-only leftovers are now removed.
- `setup.sh` re-stages the bundle's packages when their `SHA256SUMS` differ
  from the staged set; a newer bundle run over an existing install kept the
  older packages.

## v0.6.41 - 2026-11-13

- OS images no longer carry the build machine's network or login identity:
  Ubuntu 24.04 keeps NetworkManager connections as netplan files
  (`/etc/netplan/90-NM-*.yaml`), and the builder's static `br0` with a fixed
  MAC would have come up beside every appliance's own connection. The builder
  also removes root's `authorized_keys`, NetworkManager's secret key and
  leases, any gateway token, and locks the cloud image's `ubuntu` account;
  cloud-init is disabled if present.
- The configuration migration carries a 24.04 appliance's netplan-stored
  NetworkManager connections into a newer image.
- `check-transition`, `approve-transition` and `install-transition` accept
  `--channel-file` and `--source-dir` to test a transition from local files
  before it is published.

## v0.6.40 - 2026-11-13

- Both update gateways are configured: `recoveragw` (gateway A, jprod-sb) and
  `recoveragwb` (gateway B, rj-or-sb), tried in order. The package adds gateway
  B to configurations that 0.6.39 pointed at gateway A only.
- The gateways also serve the `jammy-noble-transition` and `noble-stable`
  channels. A channel with nothing published is served as an empty pointer, so
  the Operating System Upgrade card reports "No operating-system upgrade has
  been published" instead of a gateway error, and one unavailable channel no
  longer stops the gateway from refreshing the others.
- Empty `jammy-noble-transition` and `noble-stable` channel pointers are
  committed, ready for the first releases.

## v0.6.39 - 2026-11-13

Updates through the Recovera update gateway by default, and an operating-system
upgrade that appliances pull from it and run unattended once an administrator
approves it.

- `UPDATE_ORIGINS` defaults to `https://recoveragw.rjproductionsut.com`, and the
  package adds it, `GATEWAY_TOKEN_FILE` and `TRANSITION_CHANNEL` to existing
  configurations that lack them (explicit values are kept). Without a gateway
  access token an appliance keeps updating from GitHub instead of failing.
- The update page shows the update source (gateway and token subject/expiry,
  or GitHub) and accepts a gateway access token, which
  `recovera-upgrade set-gateway-token` verifies against the gateway before
  keeping it (and rolls back otherwise).
- New **Operating System Upgrade** card: the published upgrade on the
  `jammy-noble-transition` channel, a readiness checklist, and **Install in the
  next update window** / **Install now** / **Cancel**.
- `recovera-upgrade check-transition`, `approve-transition`,
  `cancel-transition` and `install-transition`. The update window runs an
  approved upgrade when no package update is due: layout conversion, a
  replication drain (deferred to the next window if transfers do not finish),
  then the verified image install and reboot. Validation failure or a crash
  returns to the previous system and clears the approval; success clears it too.

## v0.6.38 - 2026-11-12

One code base for both application releases: 5.6.x on Ubuntu 22.04 (the
current appliances) and 5.12.x on Ubuntu 24.04 (the transition target). This
brings in the 5.12.2 / Noble compatibility work, made conditional so 22.04
appliances keep their behaviour.

- WebUI branding detects the web layout: `commonlookandfeel/` and `vintage/`
  on 5.6.x, flat on 5.12.x. Recovera pages, the Synchronize panel, the
  connectivity check and the Protect integration install into whichever is
  present. Checked against the original 5.6.3 and 5.12.2 web trees.
- Fix: the Recovery Points page loaded `RecoveraRecoveryPoints.js` through a
  tag written with backslash-escaped quotes, so browsers never ran it. The
  branding step now writes a correct tag and repairs the broken one.
- `setup.sh` and `install.sh` install a 22.04 (5.6.x) or 24.04 (5.12.x)
  bundle and refuse a bundle built for the other release. PHP-FPM is detected.
  The 24.04-only runtime fixes (no Xen libvirt driver, dnsmasq beside
  systemd-resolved, `target.service` loading `target_core_mod`, Symfony route
  cache rebuild) run only on 24.04.
- The control package installs the dnsmasq and `target.service` drop-ins only
  on 24.04 and never restarts `target.service` or dnsmasq during an update,
  because stopping `target.service` clears the iSCSI targets of a running
  restore. Apache is restarted rather than reloaded after an update.
- Bundle tooling from the Noble work: `tools/export-installed-packages.sh`,
  `tools/build-php-xattr-deb.sh`, sanitizer fixes (offline npyscreen venv,
  salt-minion and rly-client presets, the Xen libvirt plug-in), a stale
  `recovera-appliance` package is dropped from exports, and the source package
  is found by its Debian `Package` field. The PHP-FPM pool is found for either
  PHP version.
- Cloud isolation also masks `datto-hva-iscsi-tls-configure.service`.

## v0.6.37 - 2026-11-12

Moving an existing appliance to a new Ubuntu release without a hypervisor
snapshot. The new release boots from a verified loop image; the 22.04 root is
never modified and stays the fallback.

- `recovera-upgrade prepare-image-layout [--dry-run]` lets an OVA-installed
  appliance boot loop images: it bind-mounts the root filesystem at `/host`,
  moves the updater state to match, installs the GRUB image menu, records the
  conventional entry as the fallback and keeps it the default.
  `revert-image-layout` undoes it.
- `check`/`install --channel NAME` read another channel once, for transition
  releases; the update window never does. `--channel` cannot be cached.
- Image manifests may declare their OS (`os`) and, for a transition, the
  starting releases and minimum Recovera version (`from`). Installing one
  requires that start, a healthy pool, replication paused and idle, no active
  restores and enough disk space (`--allow-busy` skips the idle checks). An
  image for another OS release without `from` is refused.
- `build-upgrade-image.sh` takes `--os-version`, `--from-os`,
  `--minimum-version` and `--channels-dir`, keeps transitions on `*-transition`
  channels and shares the package releases' sequence counter. Images no longer
  carry the builder's host ID or pool cache.
- The configuration migration now also carries `/var/lib/datto`,
  `/var/lib/recovera`, firewall zones, Samba share accounts and the ZFS pool
  cache, removes a host ID the source does not have, and rewrites the image's
  fstab root line to the image label (it pointed at the 22.04 disk).
- A failed first image now falls back to the conventional root. It used to try
  a GRUB entry named after the previous package release, which does not exist.

## v0.6.36 - 2026-11-12

Groundwork that must reach every 22.04 appliance before any Ubuntu 24.04
appliance or OS-transition release exists. Nothing changes for 22.04 appliances
today: they keep reading the `stable` channel.

- The updater maps the administrator's channel to one per OS release:
  `stable` on Ubuntu 22.04 (unchanged), `noble-stable` on 24.04.
- Package manifests declare their OS (`"os": {"id": "ubuntu", "version_id":
  "22.04"}`) and the updater refuses one built for a different OS release.
  Older manifests without it are accepted only on 22.04.
- `build-package-release.sh` takes `--os-version`, keeps `noble-*` channels for
  24.04 releases only, and requires the sequence to exceed every channel's, so
  moving to a new channel never looks like a downgrade.
- `REQUIRED_SERVICES` accepts `php-fpm.service`, resolved to the installed
  `phpX.Y-fpm` unit; a listed `phpX.Y-fpm` that is no longer installed resolves
  the same way. The control package depends on `php8.1-fpm | php8.3-fpm` and
  restarts whichever is installed.
- `recovera-peer maintenance on|off|status` pauses replication and drains
  running transfers without interrupting them; sources keep their resume
  token. The update window skips appliances in maintenance, and the
  Synchronize panel shows the hold.
- `asset-info` reports the target's OS version and ZFS userland/module
  versions, for mixed-version replication.
- New pools are pinned to the OpenZFS 2.2 feature set
  (`compatibility=openzfs-2.2-linux`) when the installed ZFS knows it, so an
  accidental `zpool upgrade` cannot strand a pool.

## v0.6.35 - 2026-11-07

- Replication streams are compressed in transit with zstd when both appliances
  support it: the target advertises `stream_codecs` in its `asset-info` reply
  and the source adds the codec to the receive command, so older appliances keep
  receiving plain streams. `zstd --adapt` raises the level on slow WAN links and
  lowers it on fast LANs. Compression also applies to resumed streams, so a
  running seed speeds up after a restart without losing progress. On the
  Bitches-DC → Backup-Bitches link (~40–45 Mbit/s shared) the jprod-sb stream
  compresses about 1.5–1.8×.
- Progress, speed and time remaining stay in ZFS-stream bytes (the receiver
  decompresses before `zfs receive`), so they show effective backup throughput.
  The Synchronize panel marks compressed transfers.
- An upload speed limit applies after compression, so it caps bytes on the wire.

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
