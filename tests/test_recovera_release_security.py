import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "recovera_verify_release", ROOT / "tools" / "verify-release.py"
)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class RecoveraReleaseSecurityTests(unittest.TestCase):
    def package_manifest(self, path):
        data = path.read_bytes()
        return {
            "schema": 2,
            "type": "package",
            "version": "1.0",
            "sequence": 1,
            "download_size": len(data),
            "packages": [{
                "name": "recovera-test",
                "version": "1.0-1",
                "architecture": "all",
                "asset": path.name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }],
        }

    def test_release_audit_accepts_exact_package_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "recovera-test_1.0-1_all.deb"
            package.write_bytes(b"signed release fixture")
            verified = VERIFY.verify_package_assets(root, self.package_manifest(package))
            self.assertEqual(verified[0]["name"], package.name)

    def test_release_audit_rejects_tampering_and_path_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "recovera-test_1.0-1_all.deb"
            package.write_bytes(b"original")
            manifest = self.package_manifest(package)
            package.write_bytes(b"tampered")
            with self.assertRaises(VERIFY.VerificationError):
                VERIFY.verify_package_assets(root, manifest)
            manifest["packages"][0]["asset"] = "../outside.deb"
            with self.assertRaises(VERIFY.VerificationError):
                VERIFY.verify_package_assets(root, manifest)

    def test_release_process_documents_rotation_and_private_delivery(self):
        security = (ROOT / "docs" / "release-security.md").read_text(encoding="utf-8")
        private = (ROOT / "docs" / "private-updates.md").read_text(encoding="utf-8")
        publisher = (ROOT / "tools" / "publish-package-release.sh").read_text(encoding="utf-8")
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for required in ("Bridge release", "Overlap release", "Retirement release", "recovery key"):
            self.assertIn(required, security)
        self.assertIn("recovera-upgrade install --channel-file", private)
        self.assertIn("/etc/recovera/github-token", private)
        self.assertIn("verify-release.py", publisher)
        self.assertIn("recovera-upgrade-signing-key*", ignore)

    def test_trusted_signer_file_contains_public_keys_only(self):
        signers = (ROOT / "upgrade" / "keys" / "recovera-release-signers").read_text()
        self.assertIn("recovera-release ssh-ed25519 ", signers)
        self.assertNotIn("PRIVATE KEY", signers)


if __name__ == "__main__":
    unittest.main()
