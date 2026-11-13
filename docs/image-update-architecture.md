# Recovera image updates: architecture, gaps and migration path

This document describes how Recovera updates appliances today, how that maps
onto the image-update and delta-release requirements, and the order in which
the remaining work is done. It is the reference for the release factory, the
updater (`recovera-upgradectl`, also reachable as `recovera-upgrade`) and the
update gateways.

Status: 2026-11-13, Recovera 0.6.45.

## 1. What exists today

### 1.1 Two kinds of release, one client

| | Package release | Image release |
|---|---|---|
| What changes | `recovera-appliance` (and named packages) on the running root | the whole root filesystem |
| Manifest | `recovera-package-manifest.json`, schema 2, `type: package` | `recovera-image-manifest.json`, schema 1 |
| Assets | `.deb` files with size and SHA-256 | xz-compressed ext4 image split into parts, each with size and SHA-256, plus compressed and raw image size and SHA-256 |
| Install | dpkg transaction with rollback copies of the replaced packages | staged as a loop image, booted once, committed after validation |
| Rollback | reinstall the saved packages | boot the previous image, or the conventional root |
| Channels | `stable` (22.04), `noble-stable` (24.04) | `jammy-noble-transition` (opt-in), `jammy-noble-candidate-transition` (test), later `noble-stable` |

One updater handles both. A channel pointer (`upgrade/channels/<channel>.json`)
names a GitHub release tag, its manifest and signature asset, the version and a
**sequence**. One monotonic sequence counter spans every channel, so a release
is never older than what an appliance has installed, whichever channel it came
from; downgrades are rejected by sequence.

### 1.2 Signing and verification

- Manifests are signed with an offline Ed25519 key (`ssh-keygen -Y sign`,
  namespace `recovera-upgrade`) on the release workstation. The key never
  reaches a gateway, an appliance or a release asset.
- Appliances trust `/usr/local/share/recovera-upgrade/release-signers`. It
  lists two keys under the principal `recovera-release`, which is how a key is
  rotated: ship a release trusting old + new, then sign with the new key.
- Every asset is checked against the signed manifest: size and SHA-256 per
  part, then the combined compressed stream, then the raw image. The image's
  embedded `/etc/recovera-image-release` must match the manifest version and
  sequence.
- The manifest is checked against the appliance: channel equals the
  appliance's channel, architecture, minimum updater version, operating
  system (`os`), and for a transition the starting release (`from.os_version_ids`)
  and minimum Recovera version (`from.minimum_version`).

### 1.3 Boot layout (A/B with loop images)

```
/dev/sda1  (conventional root, the original 22.04 install)
 ├── /recovera/state.json            shared updater state  (= /host/recovera/state.json)
 ├── /recovera/pending               marker: a staged release awaits validation
 ├── /recovera/images/<ver>.img      ext4 root images (loop-mounted at boot)
 ├── /recovera/images/<ver>.manifest.json + .sig
 └── /recovera/downloads/image-<seq>-<digest>/   parts kept until staged
```

- `recovera-upgrade prepare-image-layout` converts an OVA appliance once: `/` is
  bind-mounted at `/host`, the GRUB image menu is installed, and the
  conventional GRUB entry is recorded as the permanent fallback. Nothing about
  the next boot changes.
- Staging an image uses `grub-reboot` (one-time entry). The image boots with
  `root=LABEL=recovera-root`; the initramfs attaches the loop device and moves
  the host filesystem to `/host`.
- `recovera-upgrade-validate.service` runs `mark-success` after Apache, PHP-FPM
  and `recovera-peer` start. Success commits the image with `grub-set-default`.
  Failure runs `validation-failed --reboot`, which selects the previous image
  or the conventional root.
- A crash, reset or power loss before validation needs no action: the one-time
  entry is spent, so the next boot is the previous system, whose validation
  unit records the attempt as interrupted (0.6.45).
- The backup pool (`homePool`) is never touched by any of this. Both releases
  run OpenZFS 2.2, so the pool imports on either.

The updater state lives on the host filesystem, not in an image, because it
must be readable by whichever root boots next. That is why it is not under
`/var/lib/recovera-upgrade` as the delta context suggests; per-root data
(package transactions, caches) does live under `/var/lib/recovera-upgrade` and
`/var/cache/recovera-upgrade`.

### 1.4 Configuration migration

`recovera-migrate-config` copies an allowlist from the running root into the
staged image before it is booted: `/datto/config` (keeping the image's own
software-version markers), Recovera and peer configuration, Apache TLS,
NetworkManager connections and `secret_key` (stable MAC), time zone, machine
ID, hostname and hosts, host ID, `zpool.cache`, fstab (root line rewritten),
firewall zones, `/var/lib/datto`, `/var/lib/recovera`, Samba secrets, SSH host
keys, netplan NetworkManager files, administrator-made `sudoers.d` rules that
pass `visudo`, and local (UID ≥ 1000) accounts with their groups.

Consequence: the image file on an appliance is **not** byte-identical to the
release once staged, and it changes further while it runs read-write. Section
5.3 covers what that means for deltas.

### 1.5 Delivery: update gateways

```
GitHub (private repo, releases)  ──read-only token──▶  gateway A  recoveragw / recoveragwa  (jprod-sb)
                                                    ▶  gateway B  recoveragwb              (rj-or-sb)
appliance ──HTTPS + rgt1 token──▶ A, then B (UPDATE_ORIGINS order)
```

- Gateways sync channel pointers from GitHub every 15 minutes, download a
  release into a temporary directory, verify the signature and every asset,
  and only then rename it into the cache and write the pointer. They serve
  `/v1/channels/<c>.json` and `/v1/releases/<tag>/<asset>`.
- Appliances authenticate with an `rgt1.` token signed by the gateway access
  key: subject, allowed channels, expiry; revocable by `jti`. Tokens are never
  GitHub credentials, and gateways hold no release-signing key.
- 0.6.45 added: single byte-range requests (206/416), a free-space check before
  a release is cached, a verified-release stamp (no re-hash every sync),
  cleanup of releases no channel uses (one previous kept per channel), and
  `recovera-gateway status`. `/readyz` reports whether the last sync of every
  channel succeeded.
- Appliances resume interrupted parts with a Range request against either
  gateway; parts live in a per-release download directory until staged.

### 1.6 Operator and UI flow for the OS transition

Configure → Device → Operating System Upgrade shows availability, download
size and a readiness list. An administrator approves it for the next update
window or starts it now. `install-transition` then prepares the layout if
needed, pauses replication (`recovera-peer maintenance on --wait`) and waits
for running transfers, installs the image and reboots. A failed or interrupted
attempt clears the approval, so it never retries without a new one.

## 2. Requirements mapping

Legend: **done**, **partial**, **gap**.

| Requirement (delta context) | Status | Notes |
|---|---|---|
| Gateway hides GitHub, caches, survives GitHub outage | done | cached releases keep serving; `/healthz`, `/readyz` |
| Per-appliance revocable credentials | done | `rgt1` tokens, revocation list |
| Gateways verify signatures before caching | done | |
| Interchangeable gateways | partial | appliances try each origin in order; the rj-or-sb LAN cannot reach B (hairpin NAT) without split DNS |
| SHA-256, signed manifests, offline key, key rotation | done | two trusted signers; no `key_id` field yet (gap, §4) |
| Manifest: date, notes, required space, rollback target, key id, rollout rules | gap | add as optional fields (§4) |
| Full image, A/B staging, atomic next-boot switch, health confirmation, automatic rollback | done | tested end to end on the test appliance |
| Delta images with full-image fallback | gap | after full images are proven through the gateways (§5) |
| Durable state machine with explicit states | partial | state exists (`pending`, `transition_*`, `last_failure`) but no explicit phase; §3 |
| `/run` status mirror | gap | §3 |
| `query`, `check`, `status`, `download`, `stage`, `upgrade`, `rollback` | partial | `check`, `status`, `install`, `rollback` exist; §6 |
| `upgrade --dry-run` with no durable changes | partial | `check-transition` resolves, verifies and runs readiness, but there is no single dry run (§6) |
| Blockers: replication, restores/virtualization, pool, disk | done | |
| Blockers: backup running, package manager busy, outside window, network unsafe, gateway unavailable, previous failure | gap / partial | previous failure: approval cleared; others are new (§6) |
| Staged rollout / cohorts | gap | per-device approval covers the OS transition; cohorts later (§7) |
| UI: availability banner, delta/full and size, blockers, versions, Check / Download / Install / Schedule | partial | transition card has size, readiness, Install now / next window; §8 |
| Release factory | gap | after the state machine (§9) |

## 3. State machine

The updater records the phase of its latest **operation** in
`/host/recovera/phase.json` (beside `state.json`, so both roots see it) and
rebuilds `/run/recovera-upgrade/status.json` for the UI on every run. The
existing fields (`installed`, `pending`, `previous`, `transition_approval`,
`transition_last_attempt`, `last_failure`) stay the source of truth for what
is installed and staged.

Availability is **derived**, not recorded: the shown phase is the operation's
phase while one is in progress (or `BLOCKED`), otherwise `AVAILABLE` when the
cached package or transition check found an eligible release, otherwise the
last result (`COMPLETE`, `FAILED`, `ROLLED_BACK`) or `IDLE`. This keeps the
hourly checks from overwriting a staged update and keeps package and OS checks
from flipping the phase back and forth. `CHECKING` appears only in the `/run`
copy while a check runs. A downloaded but unstaged image is recorded as
`AVAILABLE` with `downloaded: true`.

```
IDLE ──check──▶ CHECKING ──▶ AVAILABLE ──download──▶ DOWNLOADING ──▶ VERIFYING ──▶ STAGING ──▶ READY_TO_REBOOT
  ▲                │  │          │                                                               │
  │                │  └▶ IDLE    └─ preflight fails ─▶ BLOCKED (blockers listed)                   reboot
  │                └─ error ─▶ FAILED                                                             ▼
  │                                                                                          REBOOTING
  │                                                                                               ▼
  └──────────── COMPLETE ◀── validation passes ── VERIFYING_BOOT ── validation fails / interrupted ─▶ ROLLED_BACK
```

Rules:

- Every transition is written atomically (`atomic_json`) with a timestamp, the
  target version, the selected artifact (`full` or `delta`, size, parts),
  download progress, and for `BLOCKED` the list of blockers and for `FAILED`
  the error. Moving on from a result keeps it as `last_result`.
- `REBOOTING` and `VERIFYING_BOOT` are written before the reboot, so the
  next boot (either root) knows what it is confirming.
- `COMPLETE` and `ROLLED_BACK` are terminal for an attempt and survive
  reboots; the next `check` moves back to `CHECKING`.
- Package releases use the same phases without `REBOOTING`/`VERIFYING_BOOT`
  unless the manifest requires a reboot.
- The `/run` mirror is presentation only and is rebuilt from `state.json` at
  boot; nothing reads it as truth.

## 4. Manifest evolution

Schema 1 image manifests and schema 2 package manifests stay valid. New
optional fields (ignored by older updaters, validated by newer ones):

| Field | Meaning |
|---|---|
| `released` | ISO-8601 UTC release time |
| `notes` | short release notes (plain text) |
| `key_id` | SHA-256 fingerprint of the signing key, checked against the signer set |
| `required_space` | bytes needed on the host filesystem to download and stage |
| `rollback_target` | what a failed boot returns to (`previous-image` or `conventional-root`) |
| `reboot_required` | already used by packages; always true for images |
| `rollout` | optional cohort rule (§7) |
| `deltas` | list of `{from_sequence, from_sha256, asset parts, size, sha256}` (§5) |
| `valid_until` | optional expiry so a gateway cannot freeze an appliance on an old pointer unnoticed |

`upgrade/schema/image-manifest.schema.json` defines the image manifest
(JSON Schema 2020-12). The tests check it against what the builder writes; the
release factory will enforce it.

## 5. Deltas (after full images are proven through the gateways)

### 5.1 When a delta applies

Only from one image release to the next (for example a `noble-stable` image
47 → 52). The first 22.04 → 24.04 step always starts from the conventional
22.04 root, which is not a release image, so it always uses the full image.

### 5.2 Format

A delta is a binary patch of the raw ext4 image from an exact source release to
the target release (`zstd --patch-from` with long-range matching, or xdelta3;
chosen by measurement), compressed and split like a full image. Datto's public
directory (`3392-to-3460.zvol.xz` beside `3460.zvol.xz`) shows the same idea —
a source-specific artifact plus a full fallback — but Recovera does not use or
redistribute Datto artifacts, and the encoding is chosen for Recovera's ext4
loop images.

### 5.3 Source verification: the pristine copy

The running image is modified by configuration migration and by running
read-write, so it cannot serve as a verifiable delta source. After an image is
staged, the appliance keeps the verified **compressed release** (the parts,
about 2.3 GB) as `/host/recovera/base/<sequence>/`. To apply a delta:

1. Check the kept base's parts against the base release's signed manifest.
2. Decompress the base, apply the delta, and hash the result.
3. The result must equal the target manifest's `uncompressed_sha256`;
   otherwise discard it and download the full image.

Disk cost: one compressed base per appliance, replaced when the next image is
staged. Fallback to the full image on any mismatch, missing base, failed patch
or failed hash.

## 6. Command surface (`recovera-upgradectl`)

`recovera-upgradectl` becomes the installed name; `recovera-upgrade` remains a
symlink because timers, the peer service and the UI call it. Existing
subcommands keep working.

| Command | Behaviour |
|---|---|
| `query --channel C` / `query --alias V` | resolve a channel (or find which allowed channel offers version V); verify the manifest signature; print the release; no download |
| `check` | as today; records `CHECKING` → `AVAILABLE`/`IDLE`/`BLOCKED` |
| `status` | state, phase, blockers, current/target/rollback versions, source |
| `download V` | fetch and verify assets into the download directory; no staging |
| `stage V` | download if needed, verify, stage for the next boot; no reboot |
| `upgrade V [--reboot] [--dry-run]` | the full flow; `--dry-run` resolves, verifies the signature, selects full or delta, runs every preflight check and estimates space, downloading nothing beyond the manifest and changing nothing durable |
| `rollback [--reboot]` | as today |

New preflight checks (0.6.46): a backup that is not idle
(`snapctl asset:backup:list`), dpkg/apt holding its lock, a device migration
holding `/datto/config/migration.lock`, and no default route. Like restores,
the first three only advise while an OS upgrade waits for approval and block
the install itself; a blocked install is recorded as `BLOCKED` and retried in
the next window. The dry run also reports the update window and an earlier
failed attempt of the same release.

## 7. Rollout control (later)

Gateway-side assignment, keyed by the token subject: rings (`canary`, `pilot`,
`stable`) and explicit subject allowlists for a release. Assignment controls
visibility only; the appliance still enforces signature, eligibility, pool,
restore and boot-safety checks. No inbound control channel: "push" means
changing what the next poll returns.

## 8. UI (last)

An **Update available** banner as soon as a signed eligible release is found
(not after a failed attempt), showing full or delta and the download size,
blockers in plain language, current / target / rollback versions, and Check
now / Download / Install now / Schedule. The banner is driven by the state
machine and disappears at `COMPLETE`.

## 9. Release factory

A CLI that turns an authorised input into an unsigned, tested release
candidate with an immutable job directory (inputs and digests, compatibility
baselines and diff, transformation log, test evidence, manifests, unsigned
assets, signing-request digest, gateway verification, disposition). It calls
`tools/build-upgrade-image.sh`, never signs, and never moves a production
pointer. Signing stays on the release workstation.

## 10. Threat model

| Threat | Mitigation | Residual |
|---|---|---|
| Forged or modified release | offline Ed25519 signature over the manifest; per-part, combined and raw SHA-256; embedded release identity | none known for the artifact itself |
| Compromised gateway serves altered assets | appliances verify signatures and hashes themselves; gateways hold no signing key | a gateway can withhold updates (freeze); `valid_until` (§4) and gateway monitoring |
| Rollback / downgrade attack | single monotonic sequence across channels | none |
| Cross-OS or wrong-channel release | manifest `channel`, `os`, `from` checked against the appliance | none |
| Stolen appliance token | channel-scoped, expiring, revocable by `jti`; grants read access to releases only | releases are readable by the token holder until revoked |
| Stolen GitHub read token (gateway) | read-only, gateway-side only, never sent to appliances | read access to the private repository |
| Signing key compromise | offline custody, two-key signer set for rotation | a new trusted set must ship before revoking the old key |
| Builder identity leaking into images (keys, MAC, tokens, host ID, sudo rules) | builder strips an explicit list; tests pin it | a new identity source must be added to the list |
| Bad image bricks the appliance | one-time boot, health validation, untouched fallback root, power-cut safe | a fault that passes validation but breaks later needs an administrator rollback |
| Update interrupts backups or replication | maintenance hold drains transfers; restore and pool checks | backup-running blocker is new work (§6) |
| Tampering with a staged image on the appliance | root-only paths | no boot-time verification (no secure boot or dm-verity) |

## 11. Migration path

1. **Done (0.6.36–0.6.45):** OS channels, image layout, loop images,
   transition flow, gateways with ranges and cache management, resumable
   downloads, tested fallback and rollback.
2. **Now:** prove a full image through both gateways on the candidate channel
   with a test appliance (interrupted download, gateway fail-over).
3. **0.6.46:** `recovera-upgradectl` name and verbs, explicit state machine
   and `/run` mirror, `--dry-run`, new blockers, manifest JSON schema with the
   reserved fields.
4. Production transition: publish the image on `jammy-noble-transition`
   (approval), approve per appliance (Backup-Bitches, then Bitches-DC).
5. Release factory around the proven commands.
6. Deltas between `noble-stable` images, with the pristine compressed base.
7. Rollout rings; UI update lifecycle.

## 12. Recovery procedures

- **Failed validation:** automatic; the appliance is back on its previous
  system with the attempt recorded. Fix the cause and approve again.
- **Return to the previous system on request:** `sudo recovera-upgrade rollback --reboot`.
- **Appliance will not boot the image at all:** power-cycle it. The one-time
  entry is spent, so the previous system boots; its validation unit records
  the attempt as interrupted.
- **Previous system needed from the GRUB menu:** the conventional entry
  (`Ubuntu`, id `gnulinux-simple-<root-uuid>`) is always listed.
- **Gateway outage:** appliances try the other origin; the cached release is
  served while GitHub is unreachable. `recovera-gateway status` shows the last
  successful sync per channel.
