import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "gateway"


def load_auth():
    sys.path.insert(0, str(GATEWAY))
    loader = importlib.machinery.SourceFileLoader(
        "recovera_gateway_auth", str(GATEWAY / "recovera_gateway_auth.py")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    sys.modules[loader.name] = module
    return module


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen is required")
class RecoveraGatewayAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_auth()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.key = self.directory / "access-key"
        subprocess.run([
            "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)
        ], check=True)
        public = self.key.with_suffix(".pub").read_text(encoding="ascii").split()
        self.signers = self.directory / "allowed-signers"
        self.signers.write_text(
            f"recovera-gateway-access {public[0]} {public[1]}\n", encoding="ascii"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_signed_token_round_trip(self):
        token = self.module.issue(self.key, "appliance-27", ["stable"], 3600, now=1000)
        claims = self.module.verify(token, self.signers, "stable", now=1100)
        self.assertEqual(claims["sub"], "appliance-27")
        self.assertEqual(claims["channels"], ["stable"])

    def test_token_rejects_wrong_channel_tampering_expiry_and_revocation(self):
        token = self.module.issue(self.key, "appliance-210", ["stable"], 600, now=1000)
        claims = self.module.verify(token, self.signers, "stable", now=1100)
        with self.assertRaises(self.module.AccessError):
            self.module.verify(token, self.signers, "candidate", now=1100)
        prefix, payload, signature = token.split(".")
        tampered_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
        with self.assertRaises(self.module.AccessError):
            self.module.verify(f"{prefix}.{tampered_payload}.{signature}", self.signers,
                               "stable", now=1100)
        with self.assertRaises(self.module.AccessError):
            self.module.verify(token, self.signers, "stable", now=2000)
        with self.assertRaises(self.module.AccessError):
            self.module.verify(token, self.signers, "stable", now=1100,
                               revoked={claims["jti"]})

    def test_committed_access_signer_matches_expected_identity(self):
        signer = (GATEWAY / "keys" / "recovera-gateway-access-signers").read_text()
        self.assertTrue(signer.startswith("recovera-gateway-access ssh-ed25519 "))


class RecoveraGatewayReleaseTrustTests(unittest.TestCase):
    def test_active_and_offline_recovery_keys_are_pretrusted(self):
        lines = [line for line in (
            ROOT / "upgrade" / "keys" / "recovera-release-signers"
        ).read_text().splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("recovera-release ssh-ed25519 ") for line in lines))
        self.assertEqual(len(set(lines)), 2)


if __name__ == "__main__":
    unittest.main()
