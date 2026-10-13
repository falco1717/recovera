import contextlib
import importlib.machinery
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "setup" / "peer" / "recovera-peer"
GATEWAY = SCRIPT.with_name("recovera-peer-gateway.conf")
SERVICE = SCRIPT.with_name("recovera-peer.service")
CONTROLLER = SCRIPT.parents[1] / "branding" / "RecoveraTargetController.php"


def load_module(root: Path):
    if not hasattr(socket, "AF_UNIX"):
        socket.AF_UNIX = 1
    if "fcntl" not in sys.modules:
        try:
            __import__("fcntl")
        except ModuleNotFoundError:
            sys.modules["fcntl"] = SimpleNamespace(
                LOCK_EX=2, LOCK_NB=4, flock=lambda *_args: None
            )
    if "grp" not in sys.modules:
        try:
            __import__("grp")
        except ModuleNotFoundError:
            sys.modules["grp"] = SimpleNamespace(
                getgrnam=lambda _name: SimpleNamespace(gr_gid=0)
            )
    os.environ["RECOVERA_PEER_ETC"] = str(root / "etc")
    os.environ["RECOVERA_PEER_STATE"] = str(root / "state")
    os.environ["RECOVERA_PEER_KEYS"] = str(root / "keys")
    os.environ["RECOVERA_PEER_LOCK"] = str(root / "lock")
    os.environ["RECOVERA_PEER_STATE_LOCK"] = str(root / "state.lock")
    os.environ["RECOVERA_PEER_OFFSITE"] = str(root / "offsite.json")
    os.environ["RECOVERA_PEER_WEB_TOKEN"] = str(root / "web.token")
    os.environ["RECOVERA_BACKUP_ADMIN_CREDENTIAL"] = str(root / "backup-admin.json")
    os.environ["RECOVERA_TX_SPEED"] = str(root / "txSpeed")
    os.environ["RECOVERA_PEER_AUTHORIZED_KEYS"] = str(root / "authorized_keys")
    os.environ["RECOVERA_PEER_SOCKET"] = str(root / "peer.sock")
    os.environ["RECOVERA_APACHE_TLS_CERT"] = str(root / "apache.crt")
    loader = importlib.machinery.SourceFileLoader("recovera_peer_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveraPeerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.peer = load_module(self.root)
        self.peer.require_root = lambda: None
        self.peer.save_config(self.peer.default_config())
        self.peer.save_state({"assets": {}, "events": []})
        self.peer.save_offsite(self.peer.default_offsite())

    def tearDown(self):
        self.temp.cleanup()

    def test_peer_service_has_no_standalone_admin_page(self):
        self.assertFalse(hasattr(self.peer, "HTML"))
        self.assertFalse(hasattr(self.peer, "LOGO_PATH"))
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/assets/recovera-logo.png", source)
        self.assertNotIn("ThreadingHTTPServer", source)
        self.assertNotIn("9443", source)
        self.assertIn("Use /configure/offsite-target on the Recovera WebUI", source)

    def test_peer_service_defaults_to_unix_socket_without_tcp_listener(self):
        config = self.peer.default_config()
        self.assertNotIn("listen", config)
        self.assertNotIn("port", config)
        self.assertEqual(self.peer.SOCKET_PATH, self.root / "peer.sock")

    def test_webui_and_apache_use_restricted_unix_socket(self):
        gateway = GATEWAY.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        service = SERVICE.read_text(encoding="utf-8")
        for text in (gateway, controller, service):
            self.assertNotIn("9443", text)
        self.assertIn("unix:/run/recovera-peer/http.sock|http://localhost", gateway)
        self.assertIn("CURLOPT_UNIX_SOCKET_PATH", controller)
        self.assertIn("RuntimeDirectory=recovera-peer", service)
        self.assertIn("Group=www-data", service)

    def test_backup_admin_credential_is_available_only_through_admin_api(self):
        self.peer.BACKUP_ADMIN_CREDENTIAL_PATH.write_text(json.dumps({
            "username": "backup-admin", "password": "stable-test-password"
        }))
        self.assertEqual(self.peer.backup_admin_credential(), {
            "username": "backup-admin", "password": "stable-test-password"
        })
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("'backup-admin-credential' => ['GET'", controller)
        gateway = GATEWAY.read_text(encoding="utf-8")
        self.assertNotIn("backup-admin-credential", gateway)

    @unittest.skipUnless(os.name == "posix", "Unix sockets are exercised on Linux CI")
    def test_unix_socket_serves_http_without_tcp(self):
        socket_path = self.root / "service.sock"
        server = self.peer.ThreadingUnixHTTPServer(str(socket_path), self.peer.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(5)
            client.connect(str(socket_path))
            client.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            response = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
            client.close()
            self.assertIn(b"HTTP/1.0 404 Not Found", response)
            self.assertIn(b"Use /configure/offsite-target", response)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            with contextlib.suppress(FileNotFoundError):
                socket_path.unlink()

    def test_offsite_schedule_add_apply_and_delete(self):
        item = self.peer.schedule_add(3600, 7200, -1)
        self.assertEqual(item["schedID"], 1)
        with mock.patch.object(self.peer.time, "localtime", return_value=SimpleNamespace(
                tm_wday=0, tm_hour=1, tm_min=30, tm_sec=0)):
            self.assertEqual(self.peer.schedule_speed(), -1)
        self.peer.schedule_delete(item["schedID"])
        self.assertEqual(self.peer.offsite()["schedules"], [])

    def test_offsite_speed_updates_peer_and_legacy_config(self):
        self.assertEqual(self.peer.set_speed(1250), 1250)
        self.assertEqual(self.peer.offsite()["speed_kbps"], 1250)
        self.assertEqual(self.peer.TX_SPEED_PATH.read_text().strip(), "1250")

    def test_default_offsite_reads_native_kilobytes_without_rescaling(self):
        self.peer.TX_SPEED_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.peer.TX_SPEED_PATH.write_text("1250000\n")
        self.assertEqual(self.peer.default_offsite()["speed_kbps"], 1250000)

    def test_offsite_schedule_rejects_invalid_ranges(self):
        for start, end, speed in ((1, 1, 100), (-1, 2, 100), (1, 604800, 100), (1, 2, -2)):
            with self.assertRaises(self.peer.PeerError):
                self.peer.schedule_add(start, end, speed)

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

    def test_wizard_assigns_policy_by_serialized_asset_identity(self):
        asset = "c" * 32
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"name": "target", "enabled": True}
        self.peer.save_config(cfg)
        self.peer.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        name = "Protected Test VM"
        serialized = f'a:2:{{s:4:"name";s:{len(name)}:"{name}";s:8:"hostname";s:7:"test-vm";}}'
        (self.peer.KEYS_DIR / f"{asset}.agentInfo").write_text(serialized)
        results = self.peer.configure_systems(
            [{"name": name}], target, interval=1440, retention_hours=2232
        )
        self.assertEqual(results[0]["asset"], asset)
        rule = self.peer.config()["assets"][asset]
        self.assertEqual(rule["peer_id"], target)
        self.assertEqual(rule["interval_minutes"], 1440)
        self.assertEqual(rule["retention_hours"], 2232)

    def test_wizard_prefers_uuid_when_names_are_duplicated(self):
        first, second = "d" * 32, "e" * 32
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"name": "target", "enabled": True}
        self.peer.save_config(cfg)
        self.peer.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        for asset, uuid in ((first, "uuid-one"), (second, "uuid-two")):
            raw = f'a:2:{{s:4:"name";s:9:"Duplicate";s:4:"uuid";s:{len(uuid)}:"{uuid}";}}'
            (self.peer.KEYS_DIR / f"{asset}.agentInfo").write_text(raw)
        results = self.peer.configure_systems(
            [{"name": "Duplicate", "uuid": "uuid-two"}], target, 60, 744
        )
        self.assertEqual([result["asset"] for result in results], [second])

    def test_newly_protected_asset_is_available_before_first_snapshot(self):
        asset = "f" * 32
        self.peer.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        name = "Freshly Protected VM"
        raw = f'a:1:{{s:4:"name";s:{len(name)}:"{name}";}}'
        (self.peer.KEYS_DIR / f"{asset}.agentInfo").write_text(raw)
        completed = mock.Mock(returncode=1, stdout=b"", stderr=b"missing")
        with mock.patch.object(self.peer, "run", return_value=completed):
            assets = self.peer.assets_local(self.peer.config())
        self.assertEqual(assets, [{
            "key": asset,
            "name": name,
            "dataset": f"homePool/home/agents/{asset}",
            "snapshots": [],
            "replicated": False,
            "origin": {},
        }])

    def test_replication_metadata_carries_target_retention(self):
        asset = "b" * 32
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"name": "target", "enabled": True}
        cfg["assets"][asset] = {
            "peer_id": target,
            "interval_minutes": 1440,
            "retention_hours": 2232,
            "enabled": True,
        }
        self.peer.save_config(cfg)
        with mock.patch.object(self.peer, "ssh_public_key", return_value="ssh-ed25519 test"):
            metadata = self.peer.collect_metadata(asset, cfg)
        self.assertEqual(metadata["retention_hours"], 2232)

    def test_target_retention_prunes_expired_points_but_keeps_newest(self):
        now = 2_000_000_000
        expired = str(now - 10 * 86400)
        recent = str(now - 3600)
        newest = str(now - 1800)
        completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(self.peer, "zfs_snapshots",
                               return_value=[expired, recent, newest]), \
             mock.patch.object(self.peer, "run", return_value=completed) as invoke:
            removed = self.peer.prune_received_snapshots(
                "homePool/home/agents/" + "d" * 32, 24, now=now
            )
        self.assertEqual(removed, [expired])
        invoke.assert_called_once_with([
            "snapctl", "asset:recoverypoints:local:destroy", "d" * 32, expired
        ])

    def test_target_retention_refuses_unsafe_values(self):
        for value in (0, 23, self.peer.MAX_RETENTION_HOURS + 1):
            with self.assertRaises(self.peer.PeerError):
                self.peer.prune_received_snapshots("homePool/test", value)

    def test_tiered_retention_keeps_recent_daily_weekly_and_monthly_points(self):
        now = 2_000_000_000
        points = [str(now - days * 86400 - hour * 3600)
                  for days, hour in ((1, 1), (1, 2), (8, 1), (8, 2),
                                     (20, 1), (21, 1), (60, 1), (61, 1))]
        points.append(str(now - 600))
        points.sort(key=int)
        completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(self.peer, "zfs_snapshots", return_value=points), \
             mock.patch.object(self.peer, "run", return_value=completed):
            removed = self.peer.prune_received_snapshots(
                "homePool/home/agents/" + "d" * 32, 2232, now=now
            )
        kept = set(points) - set(removed)
        self.assertIn(points[-1], kept)
        self.assertLess(len(kept), len(points))
        self.assertGreaterEqual(len(kept), 5)

    def test_policy_supports_siris_schedule_priority_and_pause(self):
        asset = "1" * 32
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"name": "target", "enabled": True}
        self.peer.save_config(cfg)
        rule = self.peer.configure_asset(
            asset, target, 60, enabled=False, retention_hours=2232,
            schedule_mode="daily", priority="high", daily_hour=20,
        )
        self.assertEqual(rule["schedule_mode"], "daily")
        self.assertEqual(rule["priority"], "high")
        self.assertFalse(rule["enabled"])
        self.assertEqual(rule["retention_tiers"]["weekly"], 1008)

    def test_forever_retention_still_thins_old_intraday_points(self):
        now = 2_000_000_000
        points = sorted([str(now - 90 * 86400 - 3600),
                         str(now - 90 * 86400 - 7200), str(now - 300)])
        completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(self.peer, "zfs_snapshots", return_value=points), \
             mock.patch.object(self.peer, "run", return_value=completed):
            removed = self.peer.prune_received_snapshots(
                "homePool/home/agents/" + "e" * 32,
                self.peer.MAX_RETENTION_HOURS, now=now,
            )
        self.assertEqual(len(removed), 1)

    def test_target_recovery_readiness_checks_provenance_metadata_and_zfs(self):
        asset = "a" * 32
        self.peer.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        (self.peer.KEYS_DIR / f"{asset}.agentInfo").write_text("metadata")
        completed = mock.Mock(returncode=0,
                              stdout=f"readonly\ton\nmountpoint\t/home/agents/{asset}\n".encode(),
                              stderr=b"")
        item = {"key": asset, "snapshots": ["100"],
                "origin": {"isReplicated": True}}
        with mock.patch.object(self.peer, "zfs_exists", return_value=True), \
             mock.patch.object(self.peer, "run", return_value=completed):
            result = self.peer.recovery_readiness(self.peer.config(), item)
        self.assertTrue(result["recovery_ready"])
        self.assertEqual(result["latest_snapshot"], "100")

    def test_replication_capacity_preflight_preserves_target_reserve(self):
        asset, snapshot = "f" * 32, "1791876008"
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"enabled": True, "host": "10.0.0.2", "ssh_port": 22}
        self.peer.save_config(cfg)
        remote = {"snapshots": [], "storage": {"size": 100 * 1024**3, "free": 1024**3}}
        with mock.patch.object(self.peer, "zfs_exists", return_value=True), \
             mock.patch.object(self.peer, "load_origin", return_value={}), \
             mock.patch.object(self.peer, "zfs_snapshots", return_value=[snapshot]), \
             mock.patch.object(self.peer, "remote_json", return_value=remote), \
             mock.patch.object(self.peer, "zfs_send_estimate", return_value=512 * 1024**2):
            with self.assertRaisesRegex(self.peer.PeerError, "capacity preflight failed"):
                self.peer.replicate(asset, target)

    def test_scheduler_applies_exponential_retry_backoff(self):
        asset = "0" * 32
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"enabled": True}
        cfg["assets"][asset] = {"peer_id": target, "enabled": True,
                                 "schedule_mode": "interval", "interval_minutes": 5}
        self.peer.save_config(cfg)
        with mock.patch.object(self.peer, "zfs_exists", return_value=True), \
             mock.patch.object(self.peer, "zfs_snapshots", return_value=["100"]), \
             mock.patch.object(self.peer, "replicate", side_effect=self.peer.PeerError("offline")) as invoke, \
             mock.patch.object(self.peer.time, "time", return_value=2_000_000_000):
            first = self.peer.configured_sync()
            second = self.peer.configured_sync()
        self.assertFalse(first[0]["ok"])
        self.assertEqual(second, [])
        self.assertEqual(invoke.call_count, 1)
        record = self.peer.state()["assets"][f"{target}:{asset}"]
        self.assertEqual(record["consecutive_failures"], 1)
        self.assertEqual(record["next_retry"], 2_000_000_300)

    def test_native_queue_prefers_asset_policy_then_single_target(self):
        asset = "6" * 32
        first = "12345678-1234-1234-1234-123456789abc"
        second = "87654321-4321-4321-4321-cba987654321"
        cfg = self.peer.config()
        cfg["peers"] = {
            first: {"name": "one", "enabled": True},
            second: {"name": "two", "enabled": True},
        }
        cfg["assets"][asset] = {"peer_id": second, "enabled": True}
        self.assertEqual(self.peer.target_for_asset(cfg, asset), second)
        cfg["assets"] = {}
        cfg["peers"][first]["enabled"] = False
        self.assertEqual(self.peer.target_for_asset(cfg, asset), second)

    def test_native_queue_rejects_ambiguous_targets(self):
        cfg = self.peer.config()
        cfg["peers"] = {
            "12345678-1234-1234-1234-123456789abc": {"enabled": True},
            "87654321-4321-4321-4321-cba987654321": {"enabled": True},
        }
        with self.assertRaisesRegex(self.peer.PeerError, "multiple off-site targets"):
            self.peer.target_for_asset(cfg, "7" * 32)

    def test_native_queue_persists_and_wakes_worker(self):
        asset, snapshot = "8" * 32, "1791756980"
        target = "12345678-1234-1234-1234-123456789abc"
        cfg = self.peer.config()
        cfg["peers"][target] = {"name": "target", "enabled": True}
        self.peer.save_config(cfg)
        completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(self.peer, "zfs_exists", return_value=True), \
             mock.patch.object(self.peer, "zfs_snapshots", return_value=[snapshot]), \
             mock.patch.object(self.peer, "load_origin", return_value={}), \
             mock.patch.object(self.peer, "run", return_value=completed) as invoke:
            item = self.peer.queue_snapshot(asset, snapshot)
        self.assertEqual(item["status"], "queued")
        self.assertEqual(self.peer.queue_document()["items"][0]["snapshot"], snapshot)
        invoke.assert_called_once_with(
            ["systemctl", "start", "--no-block", "recovera-peer-sync.service"],
            check=False, timeout=10,
        )

    def test_native_queue_worker_tracks_success_and_error_in_order(self):
        target = "12345678-1234-1234-1234-123456789abc"
        first, second = "9" * 32, "a" * 32
        value = self.peer.state()
        value["queue"] = {
            self.peer.queue_key(target, second, "200"): {
                "key": self.peer.queue_key(target, second, "200"), "asset": second,
                "snapshot": "200", "peer_id": target, "status": "queued", "queued_at": 2,
            },
            self.peer.queue_key(target, first, "100"): {
                "key": self.peer.queue_key(target, first, "100"), "asset": first,
                "snapshot": "100", "peer_id": target, "status": "queued", "queued_at": 1,
            },
        }
        self.peer.save_state(value)

        def replicate(asset, peer_id, snapshot, speed_kbps=0):
            if asset == second:
                raise self.peer.PeerError("network unavailable")
            return {"ok": True, "asset": asset, "snapshot": snapshot, "status": "full"}

        with mock.patch.object(self.peer, "replicate", side_effect=replicate) as invoke:
            results = self.peer.queued_sync(1250)
        self.assertEqual([call.args[0] for call in invoke.call_args_list], [first, second])
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        statuses = {item["snapshot"]: item["status"]
                    for item in self.peer.queue_document()["items"]}
        self.assertEqual(statuses, {"100": "completed", "200": "error"})

    def test_native_queue_worker_resumes_interrupted_sync(self):
        target, asset = "12345678-1234-1234-1234-123456789abc", "b" * 32
        key = self.peer.queue_key(target, asset, "300")
        value = self.peer.state()
        value["queue"] = {key: {
            "key": key, "asset": asset, "snapshot": "300", "peer_id": target,
            "status": "syncing", "queued_at": 1,
        }}
        self.peer.save_state(value)
        answer = {"ok": True, "asset": asset, "snapshot": "300", "status": "resumed"}
        with mock.patch.object(self.peer, "replicate", return_value=answer) as invoke:
            self.peer.queued_sync(0)
        invoke.assert_called_once_with(asset, target, "300", speed_kbps=0)
        self.assertEqual(self.peer.state()["queue"][key]["status"], "completed")

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
                self.peer.ssl_json("10.0.0.2", 443, "/recovera-peer/pair", {"code": "secret"},
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

    def test_registered_administrator_auth_uses_php_helper(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(self.peer, "run", return_value=completed) as invoke:
            self.assertTrue(self.peer.authenticate_local_admin("jfarmer", "correct horse"))
        invoke.assert_called_once_with(
            ["php", str(self.peer.AUTH_HELPER_PATH), "jfarmer"],
            check=False,
            input_data=b"correct horse",
            timeout=8,
        )

    def test_registered_administrator_auth_rejects_invalid_input(self):
        with mock.patch.object(self.peer, "run") as invoke:
            self.assertFalse(self.peer.authenticate_local_admin("../root", "password"))
            self.assertFalse(self.peer.authenticate_local_admin("admin", ""))
        invoke.assert_not_called()

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
