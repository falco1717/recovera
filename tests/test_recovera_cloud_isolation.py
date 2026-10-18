import importlib.machinery
import importlib.util
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "setup/isolation/recovera-cloud-isolation"


def load_script():
    loader = importlib.machinery.SourceFileLoader("recovera_cloud_isolation", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CloudIsolationTests(unittest.TestCase):
    def test_scope_excludes_local_data_plane(self):
        units = set(line.strip() for line in (ROOT / "setup/isolation/cloud-units.txt").read_text().splitlines()
                    if line.strip() and not line.startswith("#"))
        self.assertIn("datto-emergency-checkin.timer", units)
        self.assertIn("datto-network-connectivity-test.timer", units)
        self.assertIn("datto-https-check.timer", units)
        self.assertIn("datto-apache-ca-update-refresh.timer", units)
        self.assertIn("salt-minion.service", units)
        self.assertIn("dtcserver.service", units)
        for forbidden in (
            "recovera-peer.service",
            "recovera-peer-sync.timer",
            "datto-asset-offsite-schedule-run.service",
            "datto-asset-replication-reconcile.service",
            "datto-retention-offsite.service",
            "datto-update-offsite-points.service",
        ):
            self.assertNotIn(forbidden, units)

    def test_hosts_are_exact_and_managed_block_is_idempotent(self):
        module = load_script()
        with tempfile.TemporaryDirectory() as directory:
            hosts = Path(directory) / "hosts"
            hosts.write_text("127.0.0.1 localhost\n")
            lines = ["0.0.0.0 device.dattobackup.com", "0.0.0.0 bmc.datto.com"]
            module.replace_managed_block(hosts, lines)
            first = hosts.read_text()
            module.replace_managed_block(hosts, lines)
            self.assertEqual(first, hosts.read_text())
            self.assertEqual(hosts.read_text().count(module.BEGIN), 1)

    def test_package_and_fresh_setup_install_isolation(self):
        builder = (ROOT / "tools/build-recovera-appliance-deb.sh").read_text()
        setup = (ROOT / "setup/setup.sh").read_text()
        self.assertIn("recovera-cloud-isolation apply", builder)
        self.assertIn("recovera-cloud-isolation.service", builder)
        self.assertIn('phase p79a "legacy cloud isolation"', setup)
        self.assertIn('cp -a "$ROOT/setup/isolation" "$payload/isolation"', (ROOT / "install.sh").read_text())


if __name__ == "__main__":
    unittest.main()
