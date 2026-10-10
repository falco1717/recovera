# spf-datto replica

This repo exports every installed package from the Datto SIRIS appliance **spf-datto**
(10.0.3.147) and rebuilds it as a VM, **spf-datto-pkgs** (10.0.3.200), on vCenter 10.0.3.12.
The VM has the same 1,351 packages at the same versions, a ZFS `homePool` and a NetworkManager bridge.

- **[WALKTHROUGH.md](WALKTHROUGH.md)**: what was done, step by step, including the dead ends
- **[GOTCHAS.md](GOTCHAS.md)**: the traps, in short form

## Layout

```
scripts/export/    run on spf-datto (as roseadmin)
  run.sh, pkgplan.py      attempt 1: download from the box's Datto repos (failed: gateway blocks Datto)
  run2.sh, pkgplan2.py    public Ubuntu mirror (private apt root) + Launchpad + Elastic
  run3.sh                 dpkg-repack everything still missing (runs after run2.sh)
scripts/vcenter/   run on this PC (PowerShell 7 + PowerCLI 13)
  vc-login.ps1            interactive sign-in; saves only the session secret
  vc-connect.ps1          reuse that session (dot-sourced by the others)
  vc-inventory.ps1        hosts / datastores / port groups
  vc-deploy.ps1           attempt 1: OVA + cloud-init over DHCP (hit an IP conflict)
  vc-redeploy.ps1         delete + re-import (its network-config property was ignored)
  vc-fix-ssh.ps1          cloud-init lockout recovery; did NOT work, kept for the record
  vc-add-disk.ps1         3 TB thin disk on Farmer-NAS-VMFS
  vc-snapshot.ps1         create / replace / revert snapshots
scripts/vm/        run on the VM (as ubuntu)
  01-static-ip.sh         DHCP to static 10.0.3.200; turns off cloud-init's network handling
  02-install-packages.sh  dry run, then exact-version install from /opt/localdebs
  03-remove-snapd-cloud-init.sh   fixes the boot ordering cycles (and php-fpm)
  04-zfs-homepool.sh      homePool + spf-datto dataset layout, /home moved onto ZFS
  05-networkmanager-bridge.sh     br0 like spf-datto, with automatic revert
config/            NetworkManager keyfiles, GRUB override, interim netplan
lists/             package lists from the export (all, manual, portable, repacked, ...)
docs/              README from the export folder
  datto-siris-registration-flow.md  registration workflow notes; PDF built from Markdown
```

The scripts in `scripts/vm/` are the **corrected** versions. They include the fixes for each
problem hit during the session (SSH lockout, needrestart re-run, overlay, snapctl link).

## Registration workflow document

The editable source is `docs/datto-siris-registration-flow.md`. Build the checked-in PDF
with PowerShell 7 and Chrome or Edge:

```powershell
pwsh -File tools/build-registration-pdf.ps1
```

## Not in the repo

| What | Where |
|---|---|
| The 1,351 `.deb` files (1.6 GB) + `SHA256SUMS` + `Packages.gz` | `F:\Users\jfarmer\Desktop\pkgexport-spf-datto\debs\` |
| Ubuntu 22.04 cloud OVA (711 MB) | `cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.ova`; put it in `scripts/vcenter/ova/` |
| SSH key | `F:\Users\jfarmer\Documents\keys\sshkey Private` / `sshkey Public.pub` |
| Passwords | never stored; typed into terminal prompts |

## Rebuilding from scratch

1. **Export:** on spf-datto, run `run2.sh` and then `run3.sh`. Copy the result off and run `sha256sum -c SHA256SUMS`.
   Or reuse the export already on the Desktop.
2. **Deploy:** run `vc-login.ps1`, then `vc-redeploy.ps1`.
3. **On the VM:**
   1. Run `01-static-ip.sh`, then snapshot `pre-package-install`.
   2. Copy `debs` and `lists`, then run `02-install-packages.sh` (a dry run) and `02-install-packages.sh --install`.
   3. **Prove a new SSH login works under Datto's sshd config before rebooting** (see GOTCHAS #10).
   4. Run `03-remove-snapd-cloud-init.sh` and reboot.
4. **Storage:** run `vc-add-disk.ps1`, then `04-zfs-homepool.sh`.
5. **Network:** run `05-networkmanager-bridge.sh` and cancel the revert. Disable networkd, reboot, and snapshot `configured`.

## Open items

- Gateway 10.0.3.1 rejects Datto destinations, so **spf-datto's offsite sync is broken** (WALKTHROUGH, Phase 3).
- `00:e0:ed:97:68:33` statically holds 10.0.3.21 inside the DHCP range.
- Rotate the `administrator@vsphere.local` and `roseadmin` passwords.
- Delete the `pre-package-install` snapshot when you no longer need it.
