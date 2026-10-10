#!/bin/bash
# Run ON the VM (as ubuntu, sudo). Installs every exported package at spf-datto's exact
# version from the offline folder /opt/localdebs (no internet, no other repos involved).
#
# Prereqs (from the workstation):
#   scp -r <export>/debs <export>/lists ubuntu@VM:pkgexport/
#   ssh ubuntu@VM 'cd ~/pkgexport/debs && sha256sum -c --quiet SHA256SUMS && sudo mv ~/pkgexport/debs /opt/localdebs'
#
# This is the corrected version of what was run. The first run locked us out of SSH
# after reboot and re-ran itself via needrestart; both are handled here (see GOTCHAS.md).
#   usage: ./02-install-packages.sh            # dry run only
#          ./02-install-packages.sh --install  # real install, detached
set -uo pipefail
LISTS=/home/ubuntu/pkgexport/lists
LA="-o Dir::Etc::sourcelist=/etc/apt/localonly.list -o Dir::Etc::sourceparts=/dev/null"

echo "deb [trusted=yes] file:/opt/localdebs ./" | sudo tee /etc/apt/localonly.list >/dev/null
sudo apt-get -qq $LA update

if [ "${1:-}" != "--install" ]; then
  sudo apt-get -s $LA install --allow-downgrades --allow-change-held-packages $(cat $LISTS/all-packages-versions.txt) > /tmp/sim.txt 2>&1
  echo "Inst: $(grep -c ^Inst /tmp/sim.txt)  Remv: $(grep -c ^Remv /tmp/sim.txt)  downgrades: $(grep -c '^Inst.*\[.*\] (' /tmp/sim.txt)"
  grep -E '^(E:|Remv)' /tmp/sim.txt
  exit 0
fi

cat > /home/ubuntu/pkgexport/install.sh <<'EOF'
#!/bin/bash
LA="-o Dir::Etc::sourcelist=/etc/apt/localonly.list -o Dir::Etc::sourceparts=/dev/null"
cd /home/ubuntu/pkgexport
apt-get -y $LA -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
  install --allow-downgrades --allow-change-held-packages $(cat lists/all-packages-versions.txt)
echo "APT-EXIT=$?"
echo "AUDIT=[$(dpkg --audit)]"

# Datto's sshd_config_device (symlinked in at every boot) has AllowGroups remote-users.
# The group only exists once Datto creates it, so create it now and add the login user.
groupadd -f remote-users
usermod -aG remote-users ubuntu

# Boot like spf-datto: 6.8 HWE generic kernel, FIPS off
cat > /etc/default/grub.d/99z-match-spf-datto.cfg <<'G'
GRUB_FLAVOUR_ORDER="generic"
GRUB_CMDLINE_LINUX_DEFAULT="$(echo "$GRUB_CMDLINE_LINUX_DEFAULT" | sed "s/ *fips=1//g")"
G
update-grub
echo "INSTALL-FINISHED"
EOF
chmod +x /home/ubuntu/pkgexport/install.sh

# NEEDRESTART_SUSPEND: otherwise needrestart restarts this unit and the script runs twice
sudo systemd-run --unit=pkg-install \
  --setenv=DEBIAN_FRONTEND=noninteractive --setenv=NEEDRESTART_SUSPEND=1 \
  --property=StandardOutput=append:/home/ubuntu/pkgexport/install.log \
  --property=StandardError=append:/home/ubuntu/pkgexport/install.log \
  /home/ubuntu/pkgexport/install.sh
echo "running as pkg-install.service; follow with: tail -f ~/pkgexport/install.log"
echo "takes ~15 min (metalibvirt compiles libvirt 10.9 from source)"
echo
echo "BEFORE REBOOTING, prove SSH survives Datto's sshd config, from a second window:"
echo "  sudo systemctl start datto-sshd-configure && sudo systemctl restart ssh"
echo "  then open a NEW ssh session; keep this one open as the fallback"
