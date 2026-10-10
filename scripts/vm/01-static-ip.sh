#!/bin/bash
# Run ON the VM (as ubuntu, sudo). Moves the VM off its DHCP address onto a static one
# and stops cloud-init from rewriting the network config on later boots.
# The SSH session drops when the address changes; reconnect on the new IP.
#   usage: ./01-static-ip.sh 10.0.3.200 00:50:56:9a:b6:f7
set -euo pipefail
IP="${1:?static IP}"; MAC="${2:?NIC MAC (lowercase, colons)}"

sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg >/dev/null <<EOF
network: {config: disabled}
EOF

sudo tee /etc/netplan/50-cloud-init.yaml >/dev/null <<EOF
network:
  version: 2
  ethernets:
    ens192:
      match:
        macaddress: "$MAC"
      set-name: "ens192"
      dhcp4: false
      dhcp6: false
      addresses: [$IP/24]
      routes:
        - to: default
          via: 10.0.3.1
      nameservers:
        addresses: [10.0.3.1]
EOF
sudo chmod 600 /etc/netplan/50-cloud-init.yaml
sudo netplan generate
# Detached so it completes even though this SSH session dies with the old address
sudo systemd-run --on-active=3 --unit=netplan-static /usr/sbin/netplan apply
echo "scheduled; reconnect to $IP"
