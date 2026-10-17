import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecoveraOvaTests(unittest.TestCase):
    def test_preparation_removes_clone_sensitive_state(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        for required in (
            "userdel -f -r backup-admin",
            "/etc/recovera-peer",
            "/var/lib/recovera-peer",
            "/datto/config/deviceID",
            "/datto/config/local/reg",
            "/datto/config/local/webaccess",
            "/var/lib/php/sessions/sess_*",
            "/etc/apache2/ssl/www.key",
            "/etc/ssh/ssh_host_*",
            "/etc/machine-id",
            "authorized_keys",
            'LOGIN_USER="backup-admin"',
            'userdel -f -r "$builder_user"',
        ):
            self.assertIn(required, script)

    def test_first_boot_regenerates_every_appliance_identity(self):
        script = (ROOT / "tools" / "recovera-ova-firstboot").read_text()
        for required in (
            "ssh-keygen -A",
            "recovera-backup-admin install",
            "recovera-peer init",
            "www.key",
            "zgenhostid -f",
            "zpool reguid homePool",
            "first-boot-complete",
        ):
            self.assertIn(required, script)
        self.assertNotIn("hostnamectl set-hostname", script)
        self.assertIn("printf 'recovera\\n' > /etc/hostname", script)
        self.assertIn("hostname recovera", script)

    def test_first_boot_creates_tls_certificate_before_peer_identity(self):
        script = (ROOT / "tools" / "recovera-ova-firstboot").read_text()
        self.assertLess(
            script.index("openssl req -x509"),
            script.index("/usr/local/sbin/recovera-peer init"),
        )

    def test_first_boot_imports_data_pool_before_assigning_clone_guid(self):
        script = (ROOT / "tools" / "recovera-ova-firstboot").read_text()
        self.assertLess(
            script.index("zpool import -N -f homePool"),
            script.index("zpool reguid homePool"),
        )
        self.assertLess(
            script.index("zfs mount -a"),
            script.index("recovera-backup-admin install"),
        )

    def test_preparation_always_rearms_first_boot(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        self.assertIn("rm -f /var/lib/recovera-ova/first-boot-complete", script)

    def test_preparation_rebuilds_empty_pool_and_compacts_root(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        for required in (
            "compact_data_pool",
            "zpool destroy -f homePool",
            "blkdiscard -f",
            "zpool create -o ashift=12",
            "compact_root_disk",
            "compact_installer_payload",
            "recovera-appliance_${version}_all.deb",
            "/var/tmp/.guestfs-*",
            "/etc/metalibvirt/build",
            "dd if=/dev/zero",
            "fstrim -av",
        ):
            self.assertIn(required, script)

    def test_preparation_restores_updater_defaults(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        self.assertLess(
            script.index("rm -rf /etc/recovera /etc/recovera-peer"),
            script.index(
                "install -m 0600 /usr/share/recovera/defaults/upgrade.conf /etc/recovera/upgrade.conf"
            ),
        )

    def test_preparation_drops_unused_kernel_and_firmware(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        for required in (
            "compact_boot_payload",
            r"linux-(image|modules|modules-extra|headers)-5\.15\.",
            "purging the 5.15 kernel would also remove",
            "dpkg -L linux-firmware",
            'update-initramfs -u -k "$running"',
        ):
            self.assertIn(required, script)
        self.assertLess(
            script.index("\ncompact_boot_payload\n"),
            script.index("\ncompact_root_disk\n"),
        )

    def test_exported_ova_fits_a_github_release_asset(self):
        script = (ROOT / "tools" / "check-ova.sh").read_text()
        self.assertIn("2000000000", script)
        self.assertIn("streamOptimized", script)
        self.assertIn('"${#vmdk_members[@]}" -eq 2', script)

    def test_first_boot_precedes_network_facing_services(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        self.assertIn(
            "Before=network-pre.target NetworkManager.service ssh.service apache2.service recovera-peer.service",
            script,
        )

    def test_installer_purges_only_reviewed_pruned_packages(self):
        script = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn("purge_pruned_packages()", script)
        self.assertIn("grep -Fxq \"$package\" \"$list\"", script)
        self.assertIn(
            'phase p42 "remove stale source-appliance-only packages"      purge_pruned_packages',
            script,
        )

    def test_password_ssh_is_scoped_to_backup_admin(self):
        script = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn("recovera-sshd-policy", script)
        policy = (ROOT / "setup" / "peer" / "recovera-sshd-policy").read_text()
        self.assertIn("49-recovera-password-policy.conf", policy)
        self.assertIn("rm -f /etc/ssh/sshd_config.d/59-recovera-password-policy.conf", policy)
        self.assertIn("/etc/ssh/sshd_config.d/92-recovera-backup-admin.conf", policy)
        self.assertIn("Include /etc/ssh/sshd_config.d/*.conf", policy)
        self.assertIn("Match User backup-admin", policy)
        self.assertIn("Match all", policy)
        dropin = (ROOT / "setup" / "peer" / "recovera-sshd-service.conf").read_text()
        self.assertIn("ExecStartPost=/usr/local/sbin/recovera-sshd-policy", dropin)
        self.assertIn("password SSH is enabled only for backup-admin", script)

    def test_first_boot_service_races_are_recoverable(self):
        setup = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn("/var/lib/recovera/libguestfs-self-test-passed", setup)
        dropin = (
            ROOT / "setup" / "peer" / "recovera-firewall-service.conf"
        ).read_text()
        self.assertIn("After=firewalld.service dbus.service", dropin)
        self.assertIn("Restart=on-failure", dropin)


if __name__ == "__main__":
    unittest.main()
