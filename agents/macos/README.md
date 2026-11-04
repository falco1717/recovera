# macOS agent — not available

There is intentionally no macOS agent installer here.

Datto's backup agent line (the protocol Recovera speaks on `:25567`) has only
**Windows** (Datto Windows Agent / ShadowSnap) and **Linux** (`dlad`) agents.
Datto never shipped a macOS agent, so there is nothing to fork or wrap for
offline Recovera pairing, and no binary this project could produce that a stock
Recovera/SIRIS pairing stack would accept.

Options for protecting a Mac through Recovera, none of which use a Datto Mac
agent:

- **Agentless:** back up the Mac as a VM image if it runs under a hypervisor
  Recovera can reach (Recovera's supported agentless path).
- **File-level:** replicate Mac data to a Linux host that *is* protected by the
  Linux agent, or to a Recovera peer over the appliance-to-appliance channel.

If Datto/Kaseya ever ships a macOS agent that speaks this pairing protocol, the
offline approach in `docs/offline-agent-pairing.md` (shared CA, `type:` cert
metadata, deviceID match, `certCheck` off) would be the starting point.
