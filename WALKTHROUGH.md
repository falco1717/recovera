# Walkthrough: exporting spf-datto and rebuilding it as a VM

Done 2026-10-09. Everything is in order, including the dead ends, because most of the
useful knowledge came from those. Short version of the traps: [GOTCHAS.md](GOTCHAS.md).

**Starting point:** `spf-datto` (10.0.3.147) is a Datto SIRIS appliance:
- Datto SIRIS OS 2 5.6.3 on Ubuntu 22.04.5, FIPS build, amd64.
- 1,351 installed packages, 265 of them explicitly installed.

**Goal:**
1. Export every installed package as a `.deb` file.
2. Build a new VM on vCenter 10.0.3.12 with all of them at the exact same versions.
3. Give the VM ZFS storage like the appliance.

**End result:** the `spf-datto-pkgs` VM at 10.0.3.200, with 1,351/1,351 packages at exact
versions, a `homePool` ZFS pool on a 3 TB disk, and a NetworkManager bridge like the
appliance. The only services left failing are the ones that need real hardware or Datto
registration.

---

## Phase 1: What's on the box

```bash
apt list --installed          # 1,351 packages
apt-mark showmanual           # 265 installed explicitly
apt list --installed 2>/dev/null | grep ',local]'   # 43 installed from local .deb files, not a repo
```

**What the package list shows:**
- **Datto stack:** `datto-siris-os-2`, `speedsync`, `dtcserver`, `stitchfs`, `lakitu-*`,
  `roundtrip-ng`, `mercuryftp`, `rly-client`, `zsender`, `vddk-fuse`, `metalibvirt`, and others.
- **Security and monitoring agents:**
  - `falcon-sensor` (CrowdStrike) and `wiz-sensor`, both installed from local `.deb` files
  - `al-agent` (Alert Logic)
  - log shippers `filebeat`, `fluent-bit` and `td-agent-bit`
  - `telegraf`, `salt-minion`
- **Two kernels:** `linux-fips` 5.15.0-170 and `linux-generic-hwe` 6.8.0-94.
  - Phase 6 showed the box actually runs **6.8.0-94-generic with FIPS off**.

`snapctl` is Datto's appliance CLI, a PHP/Symfony app inside `datto-siris-os-2`:

```bash
dpkg -S "$(readlink -f "$(command -v snapctl)")"
# datto-siris-os-2: /usr/lib/datto/device/app/snapctl.php
# /usr/bin/snapctl -> /datto/bin/snapctl -> /usr/lib/datto/device/app/snapctl.php
```

## Phase 2: Access

- **On spf-datto:** user `roseadmin`, with key `F:\Users\jfarmer\Documents\keys\sshkey Private`.
  - The public key was installed once from a terminal. The password was typed there by hand and never stored.
  - roseadmin has passwordless sudo.
  - roseadmin is in the `remote-users` group. That matters later (Phase 7).

## Phase 3: Export attempt 1, from the box's own repos (failed)

[`scripts/export/run.sh`](scripts/export/run.sh) + [`pkgplan.py`](scripts/export/pkgplan.py)
run on spf-datto as roseadmin. The script:
1. Writes all the package lists.
2. Tars the apt sources, leaving out `auth.conf*`.
3. Asks python-apt which installed versions are downloadable.
4. Runs `apt-get download` in batches of 100.
5. Checks what arrived.
6. Builds a `Packages.gz` index.

**Result: 0 of 1,308 downloadable packages arrived.**
- Every apt source on the box is a Datto mirror, including Ubuntu itself, which comes from a frozen snapshot:
  ```
  https://update.datto.com/device/packages/datto/2602201619 jammy main
  https://update.datto.com/device/packages/ubuntu/211 jammy{,-updates,-security} ...
  http://misc-mirror.datto.com/beats-8x-generic stable main      # filebeat
  ```
- spf-datto had **no outbound internet**: `update.datto.com:443` refused the connection, and Cloudflare, GitHub and Launchpad timed out.

### Diagnosing the block

- spf-datto's own `iptables OUTPUT` policy was ACCEPT, with no rules matching by owner. Root failed the same way, so it wasn't a per-user rule.
- The route goes out through `10.0.3.1`.
- After general internet was opened at the gateway, Ubuntu, Google and Cloudflare all worked, but every Datto address still failed. A packet capture proved it was the gateway:

```
10.0.3.1 > 10.0.3.147: ICMP 162.244.85.60 tcp port 443 unreachable    (update.datto.com)
10.0.3.1 > 10.0.3.147: ICMP 172.64.148.147 tcp port 443 unreachable   (device.dattobackup.com)
10.0.3.1 > 10.0.3.147: ICMP 162.244.87.45 tcp port 80 unreachable     (relay tracker)
```

**That means a Reject rule on 10.0.3.1, which looks like a UniFi gateway (MAC OUI `0c:ea:14`).**
This also breaks **offsite sync**: target `server6637` = `198.49.95.99:22`, also refused. **Still open.**

Datto addresses this device is configured to use (from `/etc` and `/datto/config`):

| Purpose | Host | IP |
|---|---|---|
| Offsite sync target (server6637) | n/a | 198.49.95.99 TCP 22 |
| Older offsite server (sync logs) | n/a | 161.129.222.102 |
| Packages / updates | update.datto.com, misc-mirror.datto.com | 162.244.85.60 |
| Device check-in / portal | device.dattobackup.com | 104.18.39.109, 172.64.148.147 (Cloudflare) |
| Cloud restores / admin | admin.dattobackup.com | 162.244.87.51 |
| Remote web | remote.datto.com, remote.dattobackup.com | 162.244.87.39, 209.118.59.253 |
| Relay trackers 1 to 6 | SRV `_rly-trackers._tcp.datto.com` | 162.244.87.41 to .46 |
| Pulse | n/a | 162.244.87.57 |
| Salt | dlt-salt.dattobackup.com | 198.49.95.19 |
| Log shipping (Kafka) | dlt-logging-kafka-11 to 13.dtc.datto.com | 206.201.138.5 to .7 |
| NTP | ntp.dattobackup.com | 206.201.138.10, .11, .15, .20 (UDP 123) |
| Connectivity tests | test22/test80/test443/speedtest.dattobackup.com | 198.49.95.46 |

Datto's published North America ranges and ports are in Datto KB200555135
(*Unified Backup Networking and Bandwidth Requirements*). A minimal allow rule for
10.0.3.147 needs:
- **Destinations:** `162.244.0.0/16`, `198.49.95.0/24`, `206.201.136.0/22`, plus the two Cloudflare portal IPs
- **Ports:** at least TCP 22, 80, 443 and UDP 123

## Phase 4: Export attempt 2, from public mirrors (no Datto needed)

With general internet working, [`scripts/export/run2.sh`](scripts/export/run2.sh) +
[`pkgplan2.py`](scripts/export/pkgplan2.py) built a **private apt root** in roseadmin's home
directory, so the appliance's own apt setup was never touched and no root was needed:

```
aptroot/etc/apt/sources.list   -> archive.ubuntu.com + security.ubuntu.com (jammy, -updates, -security)
aptroot/etc/apt/trusted.gpg.d  <- ubuntu-keyring-2018-archive.gpg
aptroot/var/lib/dpkg/status    <- copy of the real status file
apt-get -o Dir=$R -o Dir::State::status=$R/var/lib/dpkg/status update
```

It then fetched from three sources in turn:

| Source | Packages | Method |
|---|---|---|
| Ubuntu public mirror | **986** | `apt-get download pkg=exact-version`, signature-verified |
| Launchpad | **269** | `https://launchpad.net/ubuntu/+archive/primary/+files/<name>_<ver>_<arch>.deb`, for versions no longer on the mirror (Datto's Ubuntu mirror is a frozen snapshot) |
| Elastic | **1** | `filebeat-8.19.15-amd64.deb`, checked against Elastic's `.sha512` |

**Integrity check:** each `.deb`'s internal `md5sums` was compared with
`/var/lib/dpkg/info/<pkg>.md5sums`, which describes the files actually installed on the box.
- Config files aren't in that list, so local config changes don't cause false mismatches.

## Phase 5: Export pass 3, rebuilding the rest from disk with dpkg-repack

- **The idea:** you don't need any repo to export an installed package; the files are already on disk.
- **The tool:** [`scripts/export/run3.sh`](scripts/export/run3.sh) fetched `dpkg-repack` from Ubuntu.
  - It was unpacked with `dpkg-deb -x`, not installed.
  - It ran with sudo against every package that still had no `.deb`.
- **What it rebuilt:** **95** packages.
  - All the Datto packages, Falcon, Wiz and the FIPS / Ubuntu Pro packages.
  - Two fixes:
    - **zbar:** Launchpad had served `libzbar0t64` / `zbar-tools` 0.23.93-4build3, but that's the
      **Ubuntu 24.04** build with the same version string. It depends on `libv4l-0t64`, which
      doesn't exist on 22.04, and it failed the integrity check. Replaced with repacks.
    - **td-agent-bit:** `dpkg-repack` failed with *"conffile '/etc/fluent-bit/parsers.conf' does not
      appear in package"*, because `fluent-bit` took ownership of that file.
      - Fixed with `dpkg-repack --generate`, then dropping missing entries from `DEBIAN/conffiles`, then `dpkg-deb --root-owner-group -b`.
      - dpkg-repack exits 0 even when it fails, so check `repack.log` for *"problems found processing"*.

**Final export:** 1,351 `.deb` files, 1.6 GB, all 1,351 integrity MATCH.
- Every file is listed in `SHA256SUMS`, and the folder works as an offline apt source through `Packages.gz`.
- **Location:** `F:\Users\jfarmer\Desktop\pkgexport-spf-datto\`. See [`docs/export-README.txt`](docs/export-README.txt). The lists are copied in [`lists/`](lists/).
- The working files on spf-datto were deleted afterwards.

**Repacked `.deb` files contain spf-datto's current config files**, which may include local
settings or keys. They aren't byte-identical to the vendor originals and aren't signed.
Treat the export folder as sensitive.

## Phase 6: Deploy the VM

**vCenter:** 10.0.3.12 (`rj-or-vc8`, vCenter 8.0.3).
- Datacenter `Datacenter`, cluster `Cluster`, one host `10.0.3.11`.
- **Sign-in:** [`vc-login.ps1`](scripts/vcenter/vc-login.ps1) in a terminal. The user types the password; only the
  session secret is saved (`vc-session.txt`, gitignored, deleted after each use).
- **Reconnecting:** [`vc-connect.ps1`](scripts/vcenter/vc-connect.ps1) reuses that session with `Connect-VIServer -Session`.
- **Inventory:** [`vc-inventory.ps1`](scripts/vcenter/vc-inventory.ps1) picked Datastore2 (25 TB free) and the
  `Servers-VLAN3` port group (the 10.0.3.x network).

**Image:** `jammy-server-cloudimg-amd64.ova` from `cloud-images.ubuntu.com/jammy/current/`
(711 MB), SHA256 `ea42c32e…37df7`, verified. It has to be 22.04 to match the packages.
Put it in `scripts/vcenter/ova/` (gitignored).

### Attempt 1: DHCP address conflict

[`vc-deploy.ps1`](scripts/vcenter/vc-deploy.ps1) did the following:
1. Imported the OVA with cloud-init `user-data`, the `public-keys` setting and a hostname, through OVF properties.
2. Set 2 vCPU, 4 GB RAM and a 40 GB thin disk before the first boot, so cloud-init grows the root filesystem.
3. Powered on.

It got **10.0.3.21 from DHCP**, but SSH timed out. An `arp-scan` from spf-datto showed two MAC addresses for .21:
- the VM, `00:50:56:9a:22:86`
- `00:e0:ed:97:68:33`, which is **something else already using .21 inside the DHCP range**

IPv6 link-local through a jump host didn't work either.

### Attempt 2: static 10.0.3.200

[`vc-redeploy.ps1`](scripts/vcenter/vc-redeploy.ps1) did the following:
1. Deleted the first VM, after checking that its MAC matched the one created earlier.
2. Re-imported the OVA.
3. Added a base64 netplan `network-config` vApp property.

**cloud-init ignored that property**, and the VM took DHCP .23, which was free. From there,
[`scripts/vm/01-static-ip.sh`](scripts/vm/01-static-ip.sh) moved it to **10.0.3.200** and
turned off cloud-init's network handling. .200 to .253 were free according to `arp-scan`.

**Snapshot `pre-package-install`.** This is a clean 22.04 VM on .200.

## Phase 7: Install all 1,351 packages

1. Copy `debs/` and `lists/` to the VM, check `SHA256SUMS`, and move the files to `/opt/localdebs`.
2. **Dry run** with apt pointed only at the local folder ([`02-install-packages.sh`](scripts/vm/02-install-packages.sh) with no flag):
   - **989 installs:** the other 362 were already present at the same version.
   - **143 of those installs are downgrades:** the cloud image is newer than Datto's snapshot.
   - **4 removals, all harmless:** `netplan-generator`, `python3-netplan`, `ubuntu-standard`, `nftables`.
   - No errors.
3. **Real install:** `apt-get install --allow-downgrades pkg=ver …`, keeping the VM's config files wherever both exist (`--force-confold`).
   - It runs as a detached `systemd-run` unit, so a dropped SSH session can't kill it.
   - `metalibvirt`'s install script **compiles libvirt 10.9 from source** (about 757 steps, roughly 10 minutes).
   - That script also tries a nested `apt-get` and gets *"Could not get lock"*. That's harmless, because the dependencies are already there.

### The FIPS kernel

Installing `ubuntu-fips` adds `/etc/default/grub.d/99-fips.cfg` (`fips=1`) and
`99-ubuntu-fips.cfg` (`GRUB_FLAVOUR_ORDER=fips`), so the VM would boot the FIPS kernel in FIPS mode.
- **spf-datto doesn't actually do that.** A host-level GRUB loop-boots `/images/3202.0.img` on 6.8.0-94-generic, and `fips_enabled` is empty.
- [`config/99z-match-spf-datto.cfg`](config/99z-match-spf-datto.cfg) restores generic-first booting and strips `fips=1`. Its name sorts after the FIPS files, so it wins.

### Lockout after the first reboot

**Symptom:** SSH answered, but my key was rejected for every user.

**Cause:** `datto-sshd-configure.service` runs at every boot and symlinks
`/etc/ssh/sshd_config -> /etc/ssh/sshd_config_device` (or `_server`). That file contains
**`AllowGroups remote-users`**. On spf-datto, roseadmin is in that group. On the VM, `ubuntu` wasn't.

**Recovery attempts:**
1. Changing the cloud-init `instance-id` and adding a `bootcmd` that runs `usermod` **didn't recover it**.
2. So I reverted to `pre-package-install`.
3. Then re-copied the packages, because they had been copied after that snapshot.
4. Then reinstalled with the fixes now in `02-install-packages.sh`:
   - `groupadd -f remote-users && usermod -aG remote-users ubuntu`
   - `NEEDRESTART_SUSPEND=1`. In the first run, needrestart restarted `pkg-install.service` and the script ran a second time.
   - **SSH proof before rebooting:**
     1. Hold a fallback SSH session open (`tail -f queue | ssh … bash`).
     2. `systemctl start datto-sshd-configure`
     3. `systemctl restart ssh`
     4. Open a **brand-new** login. It worked.

**Snapshot `post-package-install`** (later replaced, see below), then the reboot went fine.

## Phase 8: Making it boot cleanly

### php8.1-fpm, and why so much else was failing

- **Symptom:** `/run/php` was missing, `systemd-tmpfiles-setup` was **inactive**, and `sockets.target` was also skipped.
- **Cause:** `journalctl -b | grep "ordering cycle"` showed systemd breaking loops:
  - `local-fs.target → snapd.mounts.target → snapd.mounts-pre.target → zfs-mount → zfs-import-cache → datto-zfs-unlock → datto-feature-flag-update → network.target → … → sysinit.target → local-fs.target`
  - a second loop through `cloud-init.service ↔ datto-persistent-net-rules / network-pre`
- **Neither snapd nor cloud-init is installed on spf-datto.** [`03-remove-snapd-cloud-init.sh`](scripts/vm/03-remove-snapd-cloud-init.sh):
  - purges snapd
  - **restores `/usr/bin/snapctl → /datto/bin/snapctl`**. snapd's package owns that path, so the purge deleted Datto's link and every Datto boot service failed with *"Failed to locate executable /usr/bin/snapctl"*.
  - purges cloud-init
- **Result:** 0 ordering cycles at boot, `/run/php` created, and php8.1-fpm active.

### ZFS: homePool on a 3 TB disk

spf-datto's layout:

```
homePool                 /homePool           ashift=12 compression=on
homePool/.recv           /homePool/.recv
homePool/home            /home
homePool/home/agents     /home/agents
homePool/home/configBackup /home/configBackup
homePool/os              /homePool/os         (spf-datto also has os/base, the Datto image)
homePool/transfer        /datto/transfer
```

1. [`vc-add-disk.ps1`](scripts/vcenter/vc-add-disk.ps1) hot-adds a **3 TB thin disk on `Farmer-NAS-VMFS`**.
2. [`04-zfs-homepool.sh`](scripts/vm/04-zfs-homepool.sh):
   1. Finds the blank 3 TB disk.
   2. Creates the pool by its `/dev/disk/by-path` ID.
   3. Creates the datasets.
   4. **rsyncs `/home` into the new dataset and diffs it before mounting it over `/home`**, so the SSH key survives.
   5. Sets `overlay=on`. The original `/home` stays underneath as a fallback, and without overlay
      `zfs-mount.service` fails with *"cannot mount '/home': directory is not empty"*.

This also made `datto-zfs-cache-update` pass. It had been failing on *"cannot open 'homePool/home'"*.

### NetworkManager bridge, like the appliance

spf-datto has no netplan at all. NetworkManager runs bridge `br0` (zone `datto`, STP off) with
`eth0` as its port. Datto's `datto-network-repair` parses `nmcli` output and fails when NetworkManager
manages nothing. [`05-networkmanager-bridge.sh`](scripts/vm/05-networkmanager-bridge.sh):

1. Installs [`config/br0.nmconnection`](config/br0.nmconnection) and [`ens192.nmconnection`](config/ens192.nmconnection).
   - The VM keeps a static 10.0.3.200, where spf-datto uses DHCP.
   - `cloned-mac-address` keeps the vNIC's MAC on the bridge, so vSphere doesn't see a different MAC.
2. **Arms an automatic revert 240 seconds out**, then applies the change as a detached job.
3. A new SSH login confirmed the change, then the revert was cancelled.
4. `systemd-networkd` (plus its socket and wait-online) was disabled, because spf-datto has it disabled.
   - Otherwise `systemd-networkd-wait-online` times out and the boot takes more than 2 minutes.

`datto` is the default firewalld zone (target DROP; allows http, https, ssh), so SSH was never at risk.

**Final reboot:** 49 s boot, 0 ordering cycles, br0 on .200, homePool ONLINE, `/home` from ZFS.
**Snapshot `configured`** replaced `post-package-install`.

## Final state

| | |
|---|---|
| VM | `spf-datto-pkgs`: 2 vCPU, 4 GB RAM, 40 GB thin (Datastore2) + 3 TB thin (Farmer-NAS-VMFS) |
| Network | `Servers-VLAN3`, NetworkManager `br0` 10.0.3.200/24, gateway and DNS 10.0.3.1 |
| Login | `ubuntu` with the same key; in `remote-users` |
| Kernel | 6.8.0-94-generic, FIPS off (FIPS packages installed) |
| Packages | 1,351/1,351 at spf-datto's exact versions (plus 87 cloud-image extras, 1,438 total) |
| Storage | `homePool` 2.98 TB, spf-datto dataset layout, `/home` on ZFS |
| Running | ssh, firewalld (`datto` zone), libvirtd 10.9, smbd, nfs-server, php8.1-fpm, zfs-mount, NetworkManager |
| Snapshots | `pre-package-install` (plain Ubuntu), `configured` (final) |

**Still failing, all expected:**

| Service | Why |
|---|---|
| `openipmi` | No IPMI hardware in a VM |
| `apache2` | *"no listening sockets available"*. It **fails the same way on spf-datto**. |
| `datto-speedsync-cache-update`, `datto-system-speedsync-check` | Need Datto registration |
| `datto-telegraf-configure` | Needs the Datto device certificate for mTLS |
| `datto-update-assets` (sometimes) | Datto cloud returns *"Invalid auth"* |

## Open items

- [ ] **Gateway 10.0.3.1 rejects Datto destinations.** spf-datto's offsite sync and updates are broken. See Phase 3 for the allow rule.
- [ ] **IP conflict:** `00:e0:ed:97:68:33` is statically on 10.0.3.21, inside the DHCP range. Reserve it or move it.
- [ ] Rotate the `administrator@vsphere.local` and `roseadmin` passwords. Both were sent in chat during the session.
- [ ] Delete the `pre-package-install` snapshot when done. Snapshots slow disks over time, and more so with the 3 TB disk.
- [ ] spf-datto had a load average of about 68 during the session. Probably backups, but worth a look.
