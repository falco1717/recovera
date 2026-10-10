#!/bin/bash
# Run ON the VM (as ubuntu, sudo). Switches from netplan/systemd-networkd to
# NetworkManager with bridge br0 (port ens192), the way spf-datto is set up, so
# datto-network-repair and NetworkManager-wait-online work.
#
# Safety: arms an automatic revert 4 minutes out. After it applies, open a NEW ssh
# session to the same IP and run:   sudo systemctl stop net-revert.timer
# If you can't get back in, wait 4 minutes and the old netplan config is restored.
#
# Copy config/br0.nmconnection and config/ens192.nmconnection to ~ first
# (edit the IP and cloned-mac-address in br0.nmconnection for a different VM).
set -euo pipefail

sudo mkdir -p /root/net-backup
sudo cp -a /etc/netplan/50-cloud-init.yaml /root/net-backup/
sudo install -m 600 ~/br0.nmconnection ~/ens192.nmconnection /etc/NetworkManager/system-connections/

sudo tee /root/net-revert.sh >/dev/null <<'EOF'
#!/bin/sh
rm -f /etc/NetworkManager/system-connections/br0.nmconnection /etc/NetworkManager/system-connections/ens192.nmconnection
nmcli connection reload
nmcli connection down br0 2>/dev/null; ip link delete br0 2>/dev/null
cp -a /root/net-backup/50-cloud-init.yaml /etc/netplan/
netplan apply
EOF
sudo tee /root/net-apply.sh >/dev/null <<'EOF'
#!/bin/sh
rm -f /etc/netplan/50-cloud-init.yaml
netplan apply
ip addr flush dev ens192
nmcli connection reload
nmcli connection up ens192
nmcli connection up br0
EOF
sudo chmod 700 /root/net-revert.sh /root/net-apply.sh

sudo systemd-run --on-active=240 --unit=net-revert /root/net-revert.sh
sudo systemd-run --on-active=2 --unit=net-apply /root/net-apply.sh
echo "applied; revert armed for 240s. Reconnect and run: sudo systemctl stop net-revert.timer"
echo "then, to match spf-datto (no networkd at all):"
echo "  sudo systemctl disable --now systemd-networkd-wait-online.service systemd-networkd.socket systemd-networkd.service"
