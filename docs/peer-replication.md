# Recovera peer replication

Recovera peer replication sends completed ZFS recovery-point snapshots directly
from one offline appliance to another. It does not impersonate or contact a
vendor cloud service.

## Requirements

- Both appliances must be installed from this branch with `PEER_REPLICATION=yes`.
- Each appliance needs a healthy `homePool` with enough free space.
- The appliances must reach one another on TCP 443 and TCP 22, directly or
  through a site-to-site VPN. The internal API uses a Unix-domain socket and
  does not require another network port.
- System clocks should be reasonably close. Internet time synchronization is
  not required.

## Pair from the web page

1. Sign in to the normal Recovera WebUI and open **Configure → Off-site Target**.
2. On the target, select **Generate one-time pairing code**. Record the code and
   TLS fingerprint. The code expires after 15 minutes and can be used once.
3. On the source, enter the target IP and select **Discover and verify
   fingerprint**. Compare it with the fingerprint displayed on the target.
4. Enter the one-time code and pair the target.
5. Start **Protect a System**. In **Replication & Retention**, choose **Target
   Recovera appliance**, select the authorized target, the replication
   frequency, and how long recovery points should remain on the target.
6. Finish protecting the system. Recovera saves the replication policy as part
   of the completed protection workflow.

For systems that are already protected, **Configure → Off-site Target** can
create or revise the same target, frequency, and retention policy. Select
**Synchronize now** there to start an immediate policy run.

You can also open an asset's recovery-points page and queue a specific point
from the **Exists in Cloud** column. Recovera maps the original SIRIS Private
control to the asset's configured target. If the asset has no saved policy, a
single enabled paired target is selected automatically; with multiple targets,
save a policy first so the destination is unambiguous. The page reports
**Queued**, **Streaming**, completion, or an actionable error while the transfer
runs in the background.

The scheduled service checks policies every five minutes. The policy interval
determines whether a particular asset is due.

Use **Configure → Off-site Synchronization** to set the default upload-speed
limit and weekly speed or pause windows. Those limits are applied to the actual
ZFS transfer stream and do not require Internet connectivity.

## CLI equivalent

On the target:

```bash
sudo recovera-peer pairing-code
```

On the source:

```bash
sudo recovera-peer discover 10.0.3.25
sudo recovera-peer peer-add 10.0.3.25 --code ABCD-EFGH-IJKL-MNOP
sudo recovera-peer status
sudo recovera-peer asset-configure <asset-key> --peer <peer-id> --interval 60
sudo recovera-peer sync --all
```

`peer-add` displays the target TLS fingerprint and requires confirmation. Use
`--fingerprint SHA256:...` for non-interactive setup.

Deauthorize an unused target or source with `recovera-peer peer-remove <peer-id>`
or `recovera-peer source-remove <source-id>`. A target cannot be removed while a
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
- Target retention is enforced after a successful receive. Points older than
  the selected horizon are removed through the appliance's supported local
  recovery-point deletion command, and the newest point is always retained.

## Security model

- The management page uses the normal registered administrator session and
  permissions; it does not store a second administrator password.
- A root-generated, loopback-only token authenticates the WebUI proxy to the
  local peer service. It is not sent to the browser or accepted remotely.
- Pairing codes are stored as scrypt hashes, expire, and are single-use.
- The source verifies the target TLS fingerprint during pairing and pins the
  target's SSH host key for every backup stream.
- Each source receives a restricted Ed25519 authorized key on the target.
- The `recovera-repl` account has no password and its key is forced through a
  validator. Shells, TTYs, forwarding, agent forwarding and arbitrary ZFS
  destinations are rejected.

Configuration is stored in `/etc/recovera-peer`; operational state and recent
events are stored in `/var/lib/recovera-peer`. View logs with:

```bash
sudo journalctl -u recovera-peer -u recovera-peer-sync
```

Existing appliances installed from an older version of this branch can install
or refresh only this feature, without rerunning package setup or rebooting:

```bash
sudo /opt/recovera/setup.sh install-peer
```
