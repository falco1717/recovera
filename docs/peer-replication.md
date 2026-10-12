# BackOps peer replication

BackOps peer replication sends completed ZFS recovery-point snapshots directly
from one offline appliance to another. It does not impersonate or contact the
Datto cloud service.

## Requirements

- Both appliances must be installed from this branch with `PEER_REPLICATION=yes`.
- Each appliance needs a healthy `homePool` with enough free space.
- The appliances must reach one another on TCP 9443 and TCP 22, directly or
  through a site-to-site VPN.
- System clocks should be reasonably close. Internet time synchronization is
  not required.

## Pair from the web page

1. On each appliance, run `sudo backops-peer admin-token` once. Open
   `https://<IP>:9443/`, use username `backops`, and use that appliance's token
   as the password.
2. On the target, select **Generate one-time pairing code**. Record the code and
   TLS fingerprint. The code expires after 15 minutes and can be used once.
3. On the source, enter the target IP and select **Discover and verify
   fingerprint**. Compare it with the fingerprint displayed on the target.
4. Enter the one-time code and pair the target.
5. Select a protected asset, the target appliance, and a replication interval.
   Save the policy and select **Sync configured assets now** for the first run.

The scheduled service checks policies every five minutes. The policy interval
determines whether a particular asset is due.

## CLI equivalent

On the target:

```bash
sudo backops-peer pairing-code
```

On the source:

```bash
sudo backops-peer discover 10.0.3.25
sudo backops-peer peer-add 10.0.3.25 --code ABCD-EFGH-IJKL-MNOP
sudo backops-peer status
sudo backops-peer asset-configure <asset-key> --peer <peer-id> --interval 60
sudo backops-peer sync --all
```

`peer-add` displays the target TLS fingerprint and requires confirmation. Use
`--fingerprint SHA256:...` for non-interactive setup.

Deauthorize an unused target or source with `backops-peer peer-remove <peer-id>`
or `backops-peer source-remove <source-id>`. A target cannot be removed while a
replication policy still references it.

## Transfer and recovery behavior

- Only completed numeric recovery-point snapshots are eligible.
- The first point is a full `zfs send`; later runs use `zfs send -I` from the
  newest common point.
- The target uses resumable `zfs receive -s`. If a transfer is interrupted, the
  next run uses its receive resume token.
- A target chain with no common recovery point is never overwritten
  automatically. It requires deliberate administrator review/reseeding.
- A target refuses a replicated asset key that already belongs to another
  source or to an unrelated local protected system.
- Source metadata is copied from an allowlist; hypervisor credentials, logs and
  source schedules are excluded. The target marks the asset as replicated and
  calls `snapctl asset:replication:received` after each completed point.
- This initial implementation does not automatically delete target recovery
  points. That avoids irreversible retention mistakes until a target-specific
  retention policy is explicitly implemented and tested.

## Security model

- The management page uses a per-appliance random token stored root-only.
- Pairing codes are stored as scrypt hashes, expire, and are single-use.
- The source verifies the target TLS fingerprint during pairing and pins the
  target's SSH host key for every backup stream.
- Each source receives a restricted Ed25519 authorized key on the target.
- The `backops-repl` account has no password and its key is forced through a
  validator. Shells, TTYs, forwarding, agent forwarding and arbitrary ZFS
  destinations are rejected.

Configuration is stored in `/etc/backops-peer`; operational state and recent
events are stored in `/var/lib/backops-peer`. View logs with:

```bash
sudo journalctl -u backops-peer -u backops-peer-sync
```

Existing appliances installed from an older version of this branch can install
or refresh only this feature, without rerunning package setup or rebooting:

```bash
sudo /opt/spf-datto/setup.sh install-peer
```
