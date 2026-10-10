spf-datto replica: single-script setup
=======================================

Turns a fresh Ubuntu 22.04 (jammy, amd64) VM into a replica of the Datto SIRIS spf-datto:
all 1,351 packages at spf-datto's exact versions, installed offline from debs/, plus every
fix from the original build (see WALKTHROUGH.md in the spf-datto-replica repo).

NEEDS
  - Ubuntu 22.04 amd64 (cloud image or server install), SSH key login for your user
  - about 8 GB free on /   (bundle copy + install)
  - for ZFS: a second, BLANK disk of at least ZFS_MIN_GB (default 20 GB); the largest blank disk is used

RUN
  scp spf-datto-setup.tar ubuntu@VM:
  ssh ubuntu@VM
  tar xf spf-datto-setup.tar && cd spf-datto-setup
  nano setup.conf          # optional; the defaults keep the VM's current IP
  sudo ./setup.sh check    # optional dry run
  sudo ./setup.sh          # about 20 min, then reboots

  It runs as the systemd unit "spf-datto-setup", so losing the SSH session doesn't stop it.
  Reconnect and run:  sudo ./setup.sh status       (or: sudo /opt/spf-datto/setup.sh status)
  Re-running resumes; finished phases are skipped.

WHAT IT DOES (in order)
  p10  copies the bundle to /opt/spf-datto, checks SHA256SUMS, adds it as a local apt source
  p20  apt dry run; aborts on errors or if it would remove a protected package
  p30  creates group remote-users and adds your user. Datto's sshd config, applied at every
       boot, has "AllowGroups remote-users"; without this you are locked out after the reboot.
  p40  installs all packages at exact versions (downgrades allowed; your config files kept)
  p50  GRUB: 6.8 generic kernel without fips=1, like spf-datto (FIPS packages stay installed)
  p60  purges snapd + cloud-init (they make boot ordering cycles with Datto's units) and
       restores the /usr/bin/snapctl link
  p70  ZFS homePool on the blank disk with spf-datto's layout; /home copied onto it (the
       original stays underneath, overlay=on)
  p80  NetworkManager bridge br0 (port = your NIC, zone datto). It checks that the gateway
       answers and reverts to netplan automatically if not. Then networkd is disabled.
  p85  APT_FREEZE=yes: Ubuntu sources disabled and backed up, unattended-upgrades off
  p90  verification timer: 3 min after the reboot, writes /var/log/spf-datto-verify.log

AFTERWARDS
  sudo cat /var/log/spf-datto-verify.log       (RESULT: PASS expected)
  sudo /opt/spf-datto/setup.sh verify          (run the check any time)
  Logs: /var/log/spf-datto-setup.log   Backups: /root/spf-datto-backup/
  The bundle in your home directory can be deleted; /opt/spf-datto keeps a copy.

EXPECTED FAILED SERVICES (no IPMI hardware / no Datto registration)
  openipmi, apache2 (fails the same way on spf-datto), datto-speedsync-cache-update,
  datto-system-speedsync-check, datto-telegraf-configure, datto-update-assets

SENSITIVE
  95 of the .debs were rebuilt from spf-datto's installed files (dpkg-repack) and contain its
  current config files. Treat this bundle as sensitive.
