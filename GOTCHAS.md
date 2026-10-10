# Gotchas

Each item cost time in the session. The scripts in this repo already account for all of them.

## Exporting packages

1. **All of a SIRIS's apt sources are Datto's**, including Ubuntu (a frozen snapshot at
   `update.datto.com/device/packages/ubuntu/211`). If the device can't reach Datto, `apt-get download` gets nothing.
2. **You don't need any repo to export an installed package.** Get the clean originals from the public
   Ubuntu mirror first, then older versions from Launchpad `+files/`, then `dpkg-repack` for the rest.
3. **Launchpad can hand you the wrong release.** The same version string can exist for jammy and noble
   (`libzbar0t64 0.23.93-4build3`). Always compare the `.deb`'s `md5sums` with `/var/lib/dpkg/info/<pkg>.md5sums`.
4. **dpkg-repack exits 0 when it fails.** Search `repack.log` for *"problems found processing"*.
   - Stale config-file entries, such as td-agent-bit's `parsers.conf` now owned by fluent-bit, need
     `--generate`, removing the dead lines from `DEBIAN/conffiles`, then `dpkg-deb -b`.
5. **Repacked `.deb` files carry the box's current config files**, which may include keys or tokens. Treat the export as sensitive.
6. **On Windows `scp`, list each remote path separately.** `host:"a b c"` in one argument fails with SFTP-mode scp.

## Deploying on vCenter

7. **10.0.3.21 is taken by a static device** (`00:e0:ed:97:68:33`) inside the VLAN3 DHCP range. Use static .200.
8. **cloud-init's OVF datasource ignored an added `network-config` vApp property.** Set the static IP from inside the VM instead.
9. **Reverting a snapshot doesn't revert vApp properties**, such as the cloud-init `instance-id`.

## Installing Datto packages on plain Ubuntu

10. **SSH lockout at the first reboot.** `datto-sshd-configure.service` symlinks `sshd_config` to Datto's
    copy, which has `AllowGroups remote-users`. Add the login user to `remote-users` **before** rebooting.
    - Prove it works with a fallback session: `systemctl start datto-sshd-configure && systemctl restart ssh`, then make a new login.
    - A cloud-init re-run did **not** rescue a locked-out VM; reverting the snapshot did.
11. **needrestart restarts your `systemd-run` install unit and the script runs again.** Set `NEEDRESTART_SUSPEND=1`.
12. **ubuntu-fips makes GRUB boot the FIPS kernel with `fips=1`.** spf-datto actually runs 6.8.0-94-generic
    with FIPS off; its in-OS GRUB settings don't matter, because a host GRUB loop-boots `/images/<ver>.img`.
    Override with `99z-match-spf-datto.cfg`.
13. **The `metalibvirt` install compiles libvirt from source.** Expect about 10 minutes on 2 vCPUs and a harmless nested-apt *"could not get lock"* error.

## Booting cleanly

14. **snapd and cloud-init form systemd ordering cycles with Datto's ZFS and network units.** systemd then
    drops `sockets.target` and `systemd-tmpfiles-setup`, so `/run/php` is missing and php-fpm fails, plus
    rpcbind and others. Check with `journalctl -b | grep -c "Found ordering cycle"`. spf-datto has neither, so purge both.
15. **Purging snapd deletes `/usr/bin/snapctl`**, which Datto had repointed to `/datto/bin/snapctl`.
    Re-link it, or every Datto boot service fails.
16. **Mounting ZFS over a non-empty `/home` fails** unless `overlay=on` is set.
17. **`datto-network-repair` needs NetworkManager to manage the network card.** Use a NetworkManager bridge,
    as spf-datto does, then disable `systemd-networkd` or its wait-online adds about 2 minutes to every boot.
18. **apache2 failing with "no listening sockets" is normal.** It fails the same way on spf-datto.

## Credentials

19. The vCenter password and SSH passwords were typed into terminal prompts by the user. Only
    the vCenter **session secret** was saved, to `vc-session.txt` (gitignored), and it was deleted after each use.
