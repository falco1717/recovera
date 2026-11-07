# Recovera offline agent installers

Enroll a Datto backup agent with an **offline** Recovera appliance (no Datto
cloud). The full design and the failure-by-failure derivation are in
[`../docs/offline-agent-pairing.md`](../docs/offline-agent-pairing.md).

| Platform | Status | Script |
|---|---|---|
| Linux (`dlad`) | **Working** (verified 2026-11-04, dlad 3.0.36) | [`linux/install-recovera-agent.sh`](linux/install-recovera-agent.sh) |
| Windows (DWA/ShadowSnap) | Untested wrapper | [`windows/install-recovera-agent.ps1`](windows/install-recovera-agent.ps1) |
| macOS | Not available (no Datto Mac agent exists) | [`macos/README.md`](macos/README.md) |

## Quick start (Linux)

```bash
# 1. On a workstation: mint one shared CA + both cert sets
tools/offline-agent-pairing/make-dla-ca.sh ./pki <recovera_device_id> <agent_install_uuid>

# 2. On the Linux host to protect (as root): point the agent at Recovera's CA
#    (also installs the datto-cow-reserve-fix watcher; SKIP_COW_FIX=1 to opt out)
sudo agents/linux/install-recovera-agent.sh ./pki/agent

# 3. On the Recovera appliance (as root): install the device cert set
sudo recovera/provision-agent-pki.sh ./pki/recovera

# 4. On Recovera: pair, discover the agent-derived deviceID from the agent log,
#    reissue the device cert CN to it + set /datto/config/deviceID, re-pair.
sudo snapctl agent:add <agent_ip> --offsiteTarget noOffsite
```

For existing protected Linux systems, install the ownership-transfer helper
once with `sudo agents/linux/install-recovera-agent-transfer.sh`. Future
removals then release the agent automatically so another Recovera appliance can
protect it without clearing its local database by hand.

The private CA key (`pki/ca/ca.key`) and all `*.key` files are secrets — keep
them off the appliances and out of git (see `.gitignore`). The CA impersonates
the *name* `dla.ca.datto.com` for one isolated lab only; it is not a production
trust model.
