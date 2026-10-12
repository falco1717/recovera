import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "setup" / "peer" / "backops-peer"


def load_module(root: Path):
    os.environ["BACKOPS_PEER_ETC"] = str(root / "etc")
    os.environ["BACKOPS_PEER_STATE"] = str(root / "state")
    os.environ["BACKOPS_PEER_KEYS"] = str(root / "keys")
    os.environ["BACKOPS_PEER_LOCK"] = str(root / "lock")
    os.environ["BACKOPS_PEER_AUTHORIZED_KEYS"] = str(root / "authorized_keys")
    loader = importlib.machinery.SourceFileLoader("backops_peer_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class BackOpsPeerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.peer = load_module(self.root)
        self.peer.require_root = lambda: None
        self.peer.save_config(self.peer.default_config())
        self.peer.save_state({"assets": {}, "events": []})

    def tearDown(self):
        self.temp.cleanup()

    def test_asset_and_snapshot_validation_reject_path_injection(self):
        good = "a" * 32
        self.assertEqual(self.peer.validate_asset(good.upper()), good)
        self.assertEqual(self.peer.validate_snapshot("1791756980"), "1791756980")
        for value in ("../homePool", "a" * 31, "a" * 32 + "/child", "$(id)"):
            with self.assertRaises(self.peer.PeerError):
                self.peer.validate_asset(value)
        for value in ("latest", "1/../../x", "1;id", ""):
            with self.assertRaises(self.peer.PeerError):
                self.peer.validate_snapshot(value)

    def test_pairing_code_is_single_use(self):
        code = self.peer.pairing_code(15)
        self.peer.consume_pairing_code(code.lower())
        with self.assertRaises(self.peer.PeerError):
            self.peer.consume_pairing_code(code)

    def test_pairing_code_rejects_wrong_value_without_consuming(self):
        code = self.peer.pairing_code(15)
        with self.assertRaises(self.peer.PeerError):
            self.peer.consume_pairing_code("AAAA-BBBB-CCCC-DDDD")
        self.peer.consume_pairing_code(code)

    def test_pairing_refuses_self_without_consuming_code(self):
        code = self.peer.pairing_code(15)
        cfg = self.peer.config()
        with self.assertRaises(self.peer.PeerError):
            self.peer.pair_accept({
                "code": code,
                "source_id": cfg["appliance_id"],
                "source_name": "self",
                "source_public_key": "ssh-ed25519 AAAATEST",
            }, "127.0.0.1")
        self.peer.consume_pairing_code(code)

    def test_metadata_allowlist_and_replicated_origin(self):
        asset = "1" * 32
        metadata = {
            "asset": asset,
            "source_id": "12345678-1234-1234-1234-123456789abc",
            "source_numeric_id": 1234567890,
            "source_name": "source-one",
            "files": {"osType": "bGludXg="},
        }
        self.peer.install_metadata(asset, metadata)
        self.assertEqual((self.peer.KEYS_DIR / f"{asset}.osType").read_bytes(), b"linux")
        origin = json.loads((self.peer.KEYS_DIR / f"{asset}.originDevice").read_text())
        self.assertTrue(origin["isReplicated"])
        self.assertEqual(origin["deviceId"], 1234567890)
        metadata["files"] = {"esxInfo": "eA=="}
        with self.assertRaises(self.peer.PeerError):
            self.peer.install_metadata(asset, metadata)

    def test_policy_requires_known_peer_and_bounded_interval(self):
        asset = "2" * 32
        with self.assertRaises(self.peer.PeerError):
            self.peer.configure_asset(asset, "missing", 60)
        cfg = self.peer.config()
        cfg["peers"]["12345678-1234-1234-1234-123456789abc"] = {
            "enabled": True, "host": "10.0.0.2"
        }
        self.peer.save_config(cfg)
        with self.assertRaises(self.peer.PeerError):
            self.peer.configure_asset(asset, "12345678-1234-1234-1234-123456789abc", 1)
        result = self.peer.configure_asset(asset, "12345678-1234-1234-1234-123456789abc", 60)
        self.assertEqual(result["interval_minutes"], 60)

    def test_known_hosts_uses_brackets_for_nonstandard_port(self):
        lines = self.peer.known_host_lines("10.0.0.2", 2222, ["ssh-ed25519 AAAATEST comment"])
        self.assertEqual(lines, ["[10.0.0.2]:2222 ssh-ed25519 AAAATEST"])

    def test_known_hosts_rejects_key_injection(self):
        with self.assertRaises(self.peer.PeerError):
            self.peer.known_host_lines("10.0.0.2", 22, [
                "ssh-ed25519 AAAATEST\nevil.example ssh-ed25519 AAAAFAKE"
            ])

    def test_tls_fingerprint_is_checked_before_pairing_request(self):
        connection = mock.Mock()
        connection.sock.getpeercert.return_value = b"target-certificate"
        with mock.patch.object(self.peer.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(self.peer.PeerError):
                self.peer.ssl_json("10.0.0.2", 9443, "/v1/pair", {"code": "secret"},
                                   expected_fingerprint="SHA256:00")
        connection.request.assert_not_called()

    def test_source_remove_revokes_its_forced_key(self):
        source = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["sources"][source] = {"name": "test source"}
        self.peer.save_config(cfg)
        path = self.peer.authorized_keys_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'restrict,command="entry {source}" ssh-ed25519 AAAATEST backops-source={source}\n'
            'restrict,command="entry other" ssh-ed25519 AAAAOTHER backops-source=87654321-4321-4321-4321-cba987654321\n'
        )
        self.peer.source_remove(source)
        self.assertNotIn(source, self.peer.config()["sources"])
        self.assertNotIn(source, path.read_text())
        self.assertIn("87654321", path.read_text())

    def test_peer_remove_refuses_an_assigned_target(self):
        target = "12345678-1234-1234-1234-123456789abc"
        asset = "4" * 32
        cfg = self.peer.config()
        cfg["peers"][target] = {"name": "target"}
        cfg["assets"][asset] = {"peer_id": target, "interval_minutes": 60}
        self.peer.save_config(cfg)
        with self.assertRaises(self.peer.PeerError):
            self.peer.peer_remove(target)

    def test_received_provenance_requires_dataset_removal_first(self):
        asset = "5" * 32
        value = self.peer.state()
        value["received"] = {asset: {"source_id": "source"}}
        self.peer.save_state(value)
        with mock.patch.object(self.peer, "zfs_exists", return_value=True):
            with self.assertRaises(self.peer.PeerError):
                self.peer.received_forget(asset)
        with mock.patch.object(self.peer, "zfs_exists", return_value=False):
            self.peer.received_forget(asset)
        self.assertNotIn(asset, self.peer.state()["received"])

    def test_receiver_rejects_resume_for_asset_owned_by_another_source(self):
        source = "12345678-1234-1234-1234-123456789abc"
        other = "87654321-4321-4321-4321-cba987654321"
        asset = "3" * 32
        cfg = self.peer.config()
        cfg["sources"][source] = {"name": "source"}
        self.peer.save_config(cfg)
        metadata = {
            "asset": asset, "source_id": source, "source_numeric_id": 1234567890,
            "source_name": "source", "files": {},
        }
        encoded = self.peer.encode_metadata(metadata)
        with mock.patch.object(self.peer, "zfs_exists", return_value=True), \
             mock.patch.object(self.peer, "load_origin", return_value={"sourceApplianceId": other}), \
             mock.patch.object(self.peer, "run", return_value=mock.Mock(
                 returncode=0, stdout=b"resume-token\n", stderr=b"")):
            with self.assertRaises(self.peer.PeerError):
                self.peer.receive_dataset(source, asset, "1791756980", "-", encoded, True, mock.Mock())


if __name__ == "__main__":
    unittest.main()
