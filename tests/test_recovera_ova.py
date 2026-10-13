import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecoveraOvaTests(unittest.TestCase):
    def test_preparation_removes_clone_sensitive_state(self):
        script = (ROOT / "tools" / "prepare-ova.sh").read_text()
        for required in (
            "userdel -r backup-admin",
            "/etc/recovera-peer",
            "/var/lib/recovera-peer",
            "/datto/config/deviceID",
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
        self.assertIn("59-recovera-password-policy.conf", script)
        self.assertIn("92-recovera-backup-admin.conf", script)
        self.assertIn("Match User backup-admin", script)
        self.assertIn("password SSH is enabled only for backup-admin", script)


if __name__ == "__main__":
    unittest.main()
