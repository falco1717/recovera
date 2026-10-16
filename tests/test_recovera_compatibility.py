import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "tools" / "compatibility" / "collect-baseline.py"
COMPARATOR = ROOT / "tools" / "compatibility" / "compare-baselines.py"


def load_script(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveraCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collector = load_script("recovera_compat_collect", COLLECTOR)
        cls.comparator = load_script("recovera_compat_compare", COMPARATOR)

    def test_sensitive_paths_are_never_collected(self):
        excluded = [
            "/etc/shadow",
            "/etc/ssh/ssh_host_ed25519_key",
            "/opt/app/client.pem",
            "/var/lib/app/credentials/token.json",
            "/var/lib/app/api-token.json",
            "/etc/app/client.crt",
            "/var/lib/app/state.sqlite",
        ]
        for path in excluded:
            with self.subTest(path=path):
                self.assertTrue(self.collector.is_sensitive_path(path))
        self.assertFalse(self.collector.is_sensitive_path("/etc/systemd/system/recovera-peer.service"))

    def test_collector_hashes_code_but_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "usr/local/lib/recovera/app.py"
            secret = root / "usr/local/lib/recovera/private.key"
            safe.parent.mkdir(parents=True)
            safe.write_text("print('ok')\n", encoding="utf-8")
            secret.write_text("do-not-collect\n", encoding="utf-8")
            policy = {
                "schema": 1,
                "max_file_size": 1024,
                "rules": [{"path": "/usr/local/lib/recovera", "recursive": True, "extensions": [], "hash": True}],
            }
            files = self.collector.collect_files(root, policy)
            self.assertEqual([item["path"] for item in files], ["/usr/local/lib/recovera/app.py"])
            self.assertEqual(files[0]["sha256"], hashlib.sha256(safe.read_bytes()).hexdigest())

    def test_comparison_classifies_removals_as_high_attention(self):
        before = self.baseline("old")
        after = self.baseline("new")
        before["packages"] = [{"name": "required", "version": "1", "architecture": "amd64"}]
        after["packages"] = []
        after["files"] = [{"path": "/safe/new", "type": "file", "mode": "0644", "size": 1, "sha256": "a" * 64}]
        result = self.comparator.build_comparison(before, after)
        self.assertEqual(result["summary"]["classification"], "high-attention")
        self.assertEqual(result["summary"]["packages_removed"], 1)
        self.assertEqual(result["summary"]["files_added"], 1)

    def test_overlay_manifest_is_well_formed(self):
        overlay = json.loads((ROOT / "compatibility/recovera-overlay.json").read_text(encoding="utf-8"))
        self.assertEqual(overlay["schema"], 1)
        self.assertTrue(overlay["entries"])
        self.assertTrue(overlay["acceptance_tests"])
        self.assertEqual({entry["strategy"] for entry in overlay["entries"]}, {"owned", "drop_in", "patched"})

    @staticmethod
    def baseline(label):
        return {
            "schema": 1,
            "collector_version": 1,
            "label": label,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "privacy": "metadata-and-digests-only",
            "fingerprint": label * 8,
            "platform": {"architecture": "amd64", "kernel": "1", "os": {"id": "ubuntu"}},
            "packages": [],
            "services": [],
            "files": [],
        }


if __name__ == "__main__":
    unittest.main()
