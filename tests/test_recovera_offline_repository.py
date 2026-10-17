import gzip
import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MERGER = ROOT / "tools/merge-offline-package.py"


def load_merger():
    loader = importlib.machinery.SourceFileLoader("recovera_offline_merge", str(MERGER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveraOfflineRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_merger()

    def test_package_merge_replaces_version_and_rebuilds_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, source = root / "target", root / "source"
            target.mkdir()
            source.mkdir()
            old = target / "recovera-appliance_1_all.deb"
            old.write_bytes(b"old")
            new = source / "recovera-appliance_2_all.deb"
            new.write_bytes(b"new")
            old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
            new_hash = hashlib.sha256(new.read_bytes()).hexdigest()
            (target / "Packages").write_text(self.stanza("1", old.name, old_hash, len(old.read_bytes())))
            (source / "Packages").write_text(self.stanza("2", new.name, new_hash, len(new.read_bytes())))
            package_list = root / "all-packages-versions.txt"
            package_list.write_text("recovera-appliance=1\nzfsutils-linux=2\n")

            copied = self.module.merge(target, source, package_list)

            self.assertEqual(copied, [new.name])
            self.assertFalse(old.exists())
            self.assertTrue((target / new.name).exists())
            self.assertIn("Version: 2", (target / "Packages").read_text())
            self.assertNotIn("Version: 1", (target / "Packages").read_text())
            with gzip.open(target / "Packages.gz", "rt") as handle:
                self.assertEqual(handle.read(), (target / "Packages").read_text())
            self.assertEqual(package_list.read_text(), "recovera-appliance=2\nzfsutils-linux=2\n")
            self.assertIn(new.name, (target / "SHA256SUMS").read_text())

    @staticmethod
    def stanza(version, filename, digest, size):
        return (
            "Package: recovera-appliance\n"
            f"Version: {version}\n"
            "Architecture: all\n"
            f"Filename: ./{filename}\n"
            f"Size: {size}\n"
            f"SHA256: {digest}\n"
            "Description: test package\n\n"
        )


if __name__ == "__main__":
    unittest.main()
