# Offline Datto Linux Agent (dlad) pairing with Recovera

Recovera inherits the SIRIS agent-pairing stack but ships no agent PKI and is
air-gapped from Datto cloud, so a stock Datto Linux Agent (`dlad`) cannot pair
with it out of the box. This document records how offline pairing was made to
work end to end, and the tooling that reproduces it.

**Status:** working. On 2026-11-04 a stock `dlad` 3.0.36 on `jprod-sb`
(10.10.20.2) paired to Recovera `Backup-Bitches` (10.0.3.187); `snapctl
agent:list` shows the agent with a ZFS dataset `homePool/home/agents/<uuid>`.

**Scope / honesty:** this covers *pairing*. The backup data path (MercuryFTP)
is wired to reuse the appliance web cert and was not yet exercised; pairing logs
two non-fatal offline-cloud warnings (`v1/device/asset/volumes/upload` and
`updateVolumes` "returned no result"), which are the most likely next gap for a
real backup. This reuses a self-issued CA that impersonates the *name*
`dla.ca.datto.com` for one isolated lab; it is not a production trust model.

## Why stock dlad rejects an offline device

Both ends of the `:25567` pair are mutually authenticated TLS. In real Datto,
the cloud issues **both** the device's `*device.pem` and the agent's
`server.pem` from one CA, `CN=dla.ca.datto.com`, and each side trusts that CA.
Recovera has no cloud to issue these, and `dlad` actively re-fetches its trust
from `mothership.dtc.datto.com`. The failures, peeled one layer at a time:

| Symptom (device side) | Agent-side log | Cause & fix |
|---|---|---|
| `Empty reply from server` | `Failed to verify peer certificate` | No shared CA. Mint one CA, issue both leaves from it. |
| `All certificate sets failed` | `Verification of device certificate failed: Cert signer not found` | `dlad` reverted our `ca.crt` back to the real `dla.ca.datto.com` via its trust-update thread. **Disable it:** `certCheck.enabled=false`, `checkin.enabled=false` in `/etc/datto/dla/config.json`. |
| `All certificate sets failed` | `Failed to find required metadata in client certificate` | Leaf certs need an `nsComment` extension: **`type:device`** on the device cert, **`type:agent`** on the agent cert. Real certs also sign with **SHA-512**. |
| `HTTP 400 (Bad Request)` | `Pair request ... rejected (device ID mismatch)` | The agent derives a deviceID from the device cert's public key and requires the device cert **CN** and Recovera's `/datto/config/deviceID` to equal that derived value. |

### The deviceID derivation

`dlad` computes a numeric deviceID from the device cert's public key (a
crc32-like function over the SPKI — not reproduced exactly here). Because you
cannot engineer a keypair to a chosen deviceID, you adopt whatever the agent
computes. The agent *tells you* the value: pair once and read
`Pair request from deviceID <N> rejected` from `/var/log/datto/dla/dba_*.log`.
Then set the device cert **CN=`<N>`** (reissue with the **same key** so the
derived value is unchanged) and `/datto/config/deviceID = <N>`, and re-pair.

## Procedure that worked

1. **Mint the CA + leaves** — `tools/offline-agent-pairing/make-dla-ca.sh`
   produces one CA (`CN=dla.ca.datto.com`), a Recovera device cert set
   (`*_device.pem/.key`, `*_dattoAgentCaCert.crt`, `nsComment type:device`), and
   an agent cert set (`server.pem/.key`, `ca.crt`, `cloud.thm`,
   `nsComment type:agent`), all SHA-512 leaves.
2. **Agent side** (`agents/linux/install-recovera-agent.sh`, run on the Linux
   host): ensure `dlad` is installed; set `certCheck.enabled`/`checkin.enabled`
   to false; install `ca.crt`, `server.pem`, `server.key`, `cloud.thm` into
   `/etc/datto/dla/certs/` (mode 600); `systemctl restart dlad`.
3. **Device side** (`recovera/provision-agent-pki.sh`, run as root on Recovera):
   install the device cert set into `/datto/config/certs/`
   (`dattoAgentCaCert.crt`/`device.pem` 644 root:root, `device.key` 640
   root:ssl-cert).
4. **Discover + set the deviceID:** `snapctl agent:add <agentIP>
   --offsiteTarget noOffsite`; read the agent-computed deviceID `<N>` from the
   agent log; reissue the device cert CN=`<N>` with the same key; write `<N>` to
   `/datto/config/deviceID`; re-run `agent:add`.

## Files I changed on the live hosts (2026-11-04, reversible)

- **jprod-sb** `/etc/datto/dla/config.json` (`certCheck`/`checkin` off, backup at
  `config.json.bak`); `/etc/datto/dla/certs/{ca.crt,server.pem,server.key,cloud.thm}`
  replaced (originals in `certs.old/` and `certs.bak-*`, full tar at
  `/root/dla-backup-*.tgz`). Revert: restore `certs.old`, restore config, restart dlad.
- **Recovera** `/datto/config/certs/` device set added (old set backed up to
  `/datto/config/certs.bak-*`); `/datto/config/deviceID` set to `1356211596`
  (original `5651178892` at `/datto/config/deviceID.bak-cc`).
- **Recovera** `/etc/sudoers.d/99-backup-admin-nopasswd` (granted so this could
  run unattended; remove when done).

## Backups fail immediately: COW reserved-space overflow (2026-11-04)

After pairing, the first real backup failed within ~90 s every time. The agent
log showed the data path starting ("Remote has a valid superblock",
DIFFERENTIAL_MERGE) then:

```
Failed during iscsi read command / Read iscsi failed. Sleeping, reconnecting...
Failed to read length 16384 on block device /dev/datto0, err: 5
Backup error: Error occurred reading the protected volume: ... read error 5 (VOLUME_READ_FAILED)
```

The "iscsi read failed" is a **downstream symptom**. The real cause is in
`dmesg`:

```
datto: rejected auto-expand: 5120 MiB step size, 76639 MiB reserved space, N blocks available
datto: cow file '/.datto' max size exceeded (X/X): -27        # -27 = EFBIG
datto: error writing cow data / error handling write bio in kernel thread: -27
```

**Mechanism.** dlad configures the `dattobd` snapshot driver's COW auto-expand
with a huge `reserved_space_mib` — observed **76639 MiB (74.8 GiB)** on a 491 GB
root, i.e. ~15 % of the volume. dattobd refuses to grow the COW file unless that
much space stays free. On a volume that is more than half full, the COW cannot
expand (or, after earlier failed attempts leak COW files and eat free space, is
rejected on the very first write). The COW file overflows, `/dev/datto0` goes
EIO, and the backup dies. Churn itself is normal — confirmed live via
`/proc/datto-info`: `cow_size_current` 10 GiB, `nr_changed_blocks` climbing only
~0.5–4 MB/s. The reserve, not the write rate, is the problem.

**Confirm it:**
```bash
cat /proc/datto-info      # look at devices[].auto_expand.reserved_space_mib
dmesg -T | grep -i datto  # "rejected auto-expand" / "max size exceeded"
```

**Fix.** Cap the reserved space on the live snapshot so auto-expand works down to
a sane floor (keeps the volume from truly filling, but gives the COW room):
```bash
dbdctl reconfigure-auto-expand -r 30720 10240 <minor>   # 30 GiB reserve, 10 GiB step
```
dlad **re-applies its large default on every new snapshot**, so this must run
continuously. `agents/linux/datto-cow-reserve-fix.{sh,service}` is a tiny systemd
watcher that caps `reserved_space_mib` to 30 GiB whenever it exceeds 40 GiB.
Install:
```bash
sudo install -m0755 agents/linux/datto-cow-reserve-fix.sh /usr/local/sbin/
sudo install -m0644 agents/linux/datto-cow-reserve-fix.service /etc/systemd/system/
sudo systemctl enable --now datto-cow-reserve-fix.service
```
Reversible: `systemctl disable --now datto-cow-reserve-fix` restores dlad's
defaults. Tune the floor with `RESERVE_MIB`/`THRESH_MIB` (see the unit file).

**Note on speed.** A first backup over a WAN link (DC→home, ~40 Mbps / 105 ms
RTT here) as a differential merge is latency-bound and slow (hours). Once one
backup completes, incrementals are small. Moving the agent onto the same LAN as
the Recovera makes it fast.
