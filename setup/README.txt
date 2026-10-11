spf-datto replica: single-script setup
=======================================

Turns a fresh Ubuntu 22.04 (jammy, amd64) VM into a replica of the Datto SIRIS spf-datto:
all 1,351 packages at spf-datto's exact versions, installed offline from debs/, plus every
fix from the original build (see WALKTHROUGH.md in the spf-datto-replica repo).

NEEDS
  - Ubuntu 22.04 amd64 (cloud image or server install), SSH key login for your user
  - about 8 GB free on /   (bundle copy + install)
  - for ZFS: a second, BLANK disk of at least ZFS_MIN_GB (default 20 GB); the largest blank disk is used
  - no Internet connection on the target; build/copy the complete bundle from another machine

AIR-GAPPED MODE
  OFFLINE_MODE=yes is the default. Every apt update, simulation, install, and purge runs in
  a private network namespace and is restricted to the bundled file: repository. Package
  maintainer scripts are prevented from starting services during installation. The exact
  npyscreen wheel required by datto-siris-os-2 is bundled too, and pip is forced to use that
  local wheel directory without querying an online index. At the end, public apt sources and
  automatic update timers are disabled.

  A default route and DNS are not required. For a static isolated LAN, set these in setup.conf:
    NET_GATEWAY="none"
    NET_DNS="none"

  This makes provisioning and the local web UI work without Internet access. It does not make
  Datto account registration, licensing, updates, or cloud services work offline; those remain
  subject to Datto's own connectivity requirements.

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
  p40  installs all packages at exact versions inside a private network namespace; package
       service starts are suppressed until installation is complete
  p45  applies spf-datto's copy of every package config file that differs (Datto's mirror ships
       rebuilt Ubuntu packages with the same version but different configs). This is what
       makes Apache work: stock ports.conf "Listen 80/443" duplicates Datto's device.conf and
       Apache fails to bind. Withheld: /root/* (Datto support root keys), filebeat (log-shipping
       identity), watchdog.conf (hardware). sudoers/sshd/apache are validated, else rolled back.
       Optional Datto cloud-client certificate authorization and its boot-time CA download are
       removed because this replica has no registration flow and must start without Internet.
       The first-run wizard's online-update pane and perpetual connectivity polling are also
       removed, so offline setup begins directly at "Name the Device."
  p50  GRUB: 6.8 generic kernel without fips=1, like spf-datto (FIPS packages stay installed)
  p60  purges snapd + cloud-init (they make boot ordering cycles with Datto's units) and
       restores the /usr/bin/snapctl link
  p70  ZFS homePool on the blank disk with spf-datto's layout; /home copied onto it (the
       original stays underneath, overlay=on)
  p80  NetworkManager bridge br0 (port = your NIC, zone datto). With a gateway configured it
       checks that the gateway answers; without one it checks the bridge address. It reverts to
       netplan automatically if the check fails. Then networkd is disabled.
  p85  APT_FREEZE=yes: Ubuntu sources disabled and backed up, unattended-upgrades off
  p90  verification timer: 3 min after the reboot, writes /var/log/spf-datto-verify.log

AFTERWARDS
  sudo cat /var/log/spf-datto-verify.log       (RESULT: PASS expected)
  sudo /opt/spf-datto/setup.sh verify          (run the check any time)
  Logs: /var/log/spf-datto-setup.log   Backups: /root/spf-datto-backup/
  The bundle in your home directory can be deleted; /opt/spf-datto keeps a copy.

WEB UI
  https://<VM IP>/  ->  "Control Panel - Register a Device" (the Datto UI of an unregistered
  appliance). Apache listens once on 0.0.0.0:80 and 0.0.0.0:443; verify checks both.
  It uses spf-datto's TLS certificate/key (they are config files of datto-siris-os-2).
  The page is locally accessible offline and starts at "Name the Device" without running the
  online update check. Completing Datto registration may still require Internet.

EXPECTED FAILED SERVICES (no IPMI hardware / no Datto registration)
  openipmi, datto-speedsync-cache-update, datto-system-speedsync-check,
  datto-telegraf-configure, datto-update-assets

SENSITIVE
  95 of the .debs were rebuilt from spf-datto's installed files (dpkg-repack) and contain its
  current config files. Treat this bundle as sensitive.
