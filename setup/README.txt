Recovera: single-script appliance setup
========================================

Turns a fresh Ubuntu 22.04 (jammy, amd64) VM into a Recovera backup appliance using
the reviewed application package set: 1,329 retained packages at tested versions,
installed offline from debs/, plus the fixes required to run that application stack
on a normal Ubuntu VM.
The bundle excludes 22 source-appliance-only security, telemetry, debug, and legacy FIPS
kernel packages after validating the retained package dependency closure.

NEEDS
  - Ubuntu 22.04 amd64 (cloud image or server install), SSH key login for your user
  - at least 8 GB RAM (more when local recovery/verification VMs require it)
  - about 12 GB free on /   (archive extraction + bundle copy + install)
  - a second, BLANK disk of at least ZFS_MIN_GB (default 20 GB) for homePool
  - hardware virtualization; for a VM, enable nested virtualization before boot
  - no Internet connection on the target; build/copy the complete bundle from another machine

AIR-GAPPED MODE
  OFFLINE_MODE=yes is the default. Every apt update, simulation, install, and purge runs in
  a private network namespace and is restricted to the bundled file: repository. Package
  maintainer scripts are prevented from starting services during installation. The exact
  The required npyscreen wheel is bundled too, and pip is forced to use that
  local wheel directory without querying an online index. At the end, public apt sources and
  automatic update timers are disabled.

  A default route and DNS are not required. For a static isolated LAN, set these in setup.conf:
    NET_GATEWAY="none"
    NET_DNS="none"

  This makes provisioning, the local web UI, and the appliance's initial local registration and
  administrator setup work without Internet access. The final registration action uses the
  native local registration service but satisfies its four observed registration-only cloud RPCs
  inside the process, then enables local administrator login instead of Partner Portal login.
  Original-vendor account enrollment, licensing, updates, and cloud services are not emulated.

RUN
  From the cloned repository:
    nano setup/setup.conf                 # optional; defaults keep the current IP
    ./install.sh --check                  # optional dry run
    ./install.sh                          # about 20 min, then reboots

  With a manually transferred archive on an isolated VM:
    ./install.sh --bundle /path/to/recovera-setup.tar --check
    ./install.sh --bundle /path/to/recovera-setup.tar

  It runs as the systemd unit "recovera-setup", so losing the SSH session doesn't stop it.
  Reconnect and run:  sudo ./setup.sh status       (or: sudo /opt/recovera/setup.sh status)
  Re-running resumes; finished phases are skipped.

WHAT IT DOES (in order)
  p10  copies the bundle to /opt/recovera, checks SHA256SUMS, adds it as a local apt source
  p20  apt dry run; aborts on errors or if it would remove a protected package
  p30  creates group remote-users and adds your user. The bundled sshd config, applied at every
       boot, has "AllowGroups remote-users"; without this you are locked out after the reboot.
  p40  installs all packages at exact versions inside a private network namespace; package
       service starts are suppressed until installation is complete
  p45  applies the appliance copy of every package config file that differs (the source mirror ships
       rebuilt Ubuntu packages with the same version but different configs). This is what
       makes Apache work: stock ports.conf "Listen 80/443" duplicates the appliance device.conf and
       Apache fails to bind. Withheld: /root/* (vendor support root keys), telemetry/log-shipping
       configuration, copied TLS keys, and watchdog.conf (hardware). A fresh per-VM TLS key and
       certificate are generated. sudoers/sshd/apache are validated, else rolled back.
       Optional cloud-client certificate authorization and its boot-time CA download are
       removed so this replica can start without Internet. The first-run wizard's online-update
       pane and perpetual connectivity polling are removed, and a one-time same-origin finalizer
       completes the native local registration without contacting the cloud.
  p50  GRUB: 6.8 generic kernel without fips=1. The unused legacy FIPS kernel
       and its meta-packages are not included in the bundle.
  p60  purges snapd + cloud-init (they make boot ordering cycles with appliance units) and
       restores the /usr/bin/snapctl link
  p70  requires a suitable blank disk, creates the Recovera ZFS homePool layout, and
       copies /home onto it. Limited troubleshooting installs can explicitly select auto/no.
  p75  verifies /dev/kvm and runs the libguestfs disk-inspection self-test used by
       agentless VM protection; this catches missing nested virtualization before registration
  p78  installs the offline peer-replication service, restricted SSH receiver, management UI,
       and five-minute scheduler. Pairing and snapshot transport never use a cloud endpoint.
  p80  NetworkManager bridge br0 (port = your NIC). With a gateway configured it
       checks that the gateway answers; without one it checks the bridge address. It reverts to
       netplan automatically if the check fails. Then networkd is disabled.
  p85  APT_FREEZE=yes: Ubuntu sources disabled and backed up, unattended-upgrades off
  p90  verification timer: 3 min after the reboot, writes /var/log/recovera-verify.log

AFTERWARDS
  sudo cat /var/log/recovera-verify.log       (RESULT: PASS expected)
  sudo /opt/recovera/setup.sh verify          (run the check any time)
  Logs: /var/log/recovera-setup.log   Backups: /root/recovera-backup/
  The bundle in your home directory can be deleted; /opt/recovera keeps a copy.

WEB UI
  https://<VM IP>/  ->  "Set Up Recovera" on an unregistered appliance. Apache listens once
  on 0.0.0.0:80 and 0.0.0.0:443; verify checks both.
  It uses a fresh local TLS certificate/key generated for this VM; the source appliance's
  private key and certificate are removed while the payload is built.
  The page is locally accessible offline and starts at "Name the Device" without running the
  online update check. Name, administrator, configuration, confirmation, local login, and the
  registration marker can all complete without Internet. The resulting login page accepts the
  local administrator rather than requiring a Partner Portal account. Cloud enrollment and
  licensing remain outside this offline replica workflow.

PEER REPLICATION
  Sign in to the normal Recovera WebUI and open Configure -> Off-site Target. The page uses
  the registered administrator session; no separate replication password is stored.

  On the target, generate a one-time pairing code. On the source, discover the target by
  IP, compare the displayed TLS fingerprint, and enter the code. The paired appliance appears
  in Protect a System -> Replication & Retention, where the target, replication frequency, and
  target retention are selected. Existing protected systems can be configured from Off-site
  Target. Configure -> Off-site Synchronization sets weekly replication windows and upload-speed
  limits. The first transfer is a full ZFS stream; later transfers are incremental and interrupted
  receives are resumable. Data transport uses a pinned SSH host key and a forced-command account
  that cannot request a shell, forwarding, or arbitrary dataset paths.

  For separate sites, route the appliance IPs across a site-to-site VPN and allow TCP 22 and
  TCP 443 for one-time pairing and TCP 22 for replication between only those two
  addresses. No default route, DNS, or Internet is required. The internal peer API
  uses a restricted Unix-domain socket and does not listen on another TCP port.

EXPECTED FAILED SERVICES
  Hardware-management and original cloud-registration services are expected to remain
  inactive on a virtual, locally managed Recovera appliance.

SENSITIVE
  Some .debs were rebuilt from reference-appliance installed files. The builder removes
  known source-appliance TLS/log-shipping keys and locks exported factory password hashes, but
  the payload still contains proprietary packages and selected configs. Keep it private and
  treat it as sensitive.
