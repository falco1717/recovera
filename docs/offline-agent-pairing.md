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
