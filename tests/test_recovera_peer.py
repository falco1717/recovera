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
    os.environ["RECOVERA_STORAGE_EXPAND_LOCK"] = str(root / "storage-expand.lock")
    os.environ["RECOVERA_PEER_STATE_LOCK"] = str(root / "state.lock")
    os.environ["RECOVERA_PEER_OFFSITE"] = str(root / "offsite.json")
    os.environ["RECOVERA_PEER_WEB_TOKEN"] = str(root / "web.token")
    os.environ["RECOVERA_BACKUP_ADMIN_CREDENTIAL"] = str(root / "backup-admin.json")
    os.environ["RECOVERA_TX_SPEED"] = str(root / "txSpeed")
    os.environ["RECOVERA_PEER_AUTHORIZED_KEYS"] = str(root / "authorized_keys")
    os.environ["RECOVERA_PEER_SOCKET"] = str(root / "peer.sock")
    os.environ["RECOVERA_APACHE_TLS_CERT"] = str(root / "apache.crt")
    os.environ["RECOVERA_UPGRADE_COMMAND"] = str(root / "recovera-upgrade")
    os.environ["RECOVERA_UPGRADE_CONFIG"] = str(root / "upgrade.conf")
    os.environ["RECOVERA_UPGRADE_TOKEN"] = str(root / "github-token")
    os.environ["RECOVERA_UPGRADE_POLICY"] = str(root / "update-policy.json")
    os.environ["RECOVERA_AGENT_CERT_DIR"] = str(root / "certs")
    os.environ["RECOVERA_DEVICE_ID"] = str(root / "deviceID")
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
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("'agent-release' => ['POST', '/v1/admin/agent/release']", controller)
        self.assertIn("'storage-status' => ['GET', '/v1/admin/storage/status']", controller)
        self.assertIn("'storage-expand' => ['POST', '/v1/admin/storage/expand']", controller)

    def test_storage_status_accepts_only_dedicated_single_disk_zfs_layout(self):
        def command(argv, **_kwargs):
            if argv[:3] == ["zpool", "list", "-H"]:
                return "107374182400 1073741824 106300440576 ONLINE"
            if argv[:2] == ["lsblk", "-d"] and argv[-2:] == ["TYPE", "/dev/sdb1"]:
                return "part"
            if argv[:2] == ["findmnt", "-n"]:
                return "/dev/sda1"
            if argv[-2:] == ["--getsize64", "/dev/sdb"]:
                return str(200 * 1024**3)
            if argv[-2:] == ["--getsize64", "/dev/sdb1"]:
                return str(100 * 1024**3)
            raise AssertionError(argv)

        partitions = [
            {"path": "/dev/sdb1", "number": 1, "type": "zfs", "size": 100 * 1024**3},
            {"path": "/dev/sdb9", "number": 9,
             "type": self.peer.ZFS_RESERVED_PARTITION_TYPE, "size": 8 * 1024**2},
        ]
        with mock.patch.object(self.peer, "_command_text", side_effect=command), \
             mock.patch.object(self.peer, "_pool_leaf", return_value=Path("/dev/sdb1")), \
             mock.patch.object(self.peer, "_partition_number", return_value=1), \
             mock.patch.object(self.peer, "_backing_disk",
                               side_effect=[Path("/dev/sdb"), Path("/dev/sda")]), \
             mock.patch.object(self.peer, "_disk_partition_table", return_value=partitions):
            status = self.peer.storage_expand_status()
        self.assertTrue(status["supported"])
        self.assertTrue(status["expandable"])
        self.assertEqual(status["reserved_partition"], "/dev/sdb9")
        self.assertEqual(status["disk"], "/dev/sdb")

    def test_storage_status_reports_unsupported_topology_without_http_error(self):
        with mock.patch.object(self.peer, "_command_text",
                               return_value="107374182400 1 107374182399 ONLINE"), \
             mock.patch.object(self.peer, "_pool_leaf",
                               side_effect=self.peer.PeerError(
                                   "automatic expansion requires homePool to contain exactly one data device"
                               )):
            status = self.peer.storage_expand_status()
        self.assertFalse(status["supported"])
        self.assertFalse(status["expandable"])
        self.assertIn("exactly one data device", status["reason"])

    def test_expand_storage_rescans_grows_partition_and_expands_zfs(self):
        gib = 1024**3
        before = {
            "pool": "homePool", "pool_size": 100 * gib, "health": "ONLINE",
            "supported": True, "unsupported_partitions": [], "disk": "/dev/sdb",
        }
        detected = before | {
            "disk_size": 200 * gib, "partition_size": 100 * gib, "expandable": True,
            "partition_table_size": 100 * gib,
            "partition_number": 1, "reserved_partition": "/dev/sdb9",
            "device": "/dev/sdb1",
        }
        kernel_ready = detected | {"partition_size": 190 * gib,
                                   "partition_table_size": 190 * gib}
        after = kernel_ready | {"pool_size": 190 * gib, "free": 180 * gib,
                                "expandable": False}
        commands = []

        def fake_run(argv, **_kwargs):
            commands.append(argv)
            if argv[0] == "growpart":
                return mock.Mock(returncode=1, stdout=b"",
                                 stderr=b"failed [pt_update:1] error updating partition 1")
            return mock.Mock(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(self.peer, "storage_expand_status",
                               side_effect=[before, detected, kernel_ready, after]), \
             mock.patch.object(self.peer, "_rescan_storage_disk") as rescan, \
             mock.patch.object(self.peer, "run", side_effect=fake_run), \
             mock.patch.object(self.peer, "_disk_partition_table",
                               return_value=[{"number": 1, "size": 190 * gib}]), \
             mock.patch.object(self.peer, "event") as event, \
             mock.patch.object(self.peer.os, "chmod"), \
             mock.patch.object(self.peer, "storage_expand_lock",
                               return_value=contextlib.nullcontext()):
            result = self.peer.expand_storage()
        self.assertTrue(result["changed"])
        rescan.assert_called_once_with(Path("/dev/sdb"))
        self.assertIn(["sgdisk", "--delete=9", "/dev/sdb"], commands)
        self.assertIn(["growpart", "/dev/sdb", "1"], commands)
        self.assertIn(["partx", "--update", "--nr", "1", "/dev/sdb"], commands)
        self.assertIn(["zpool", "online", "-e", "homePool", "/dev/sdb1"], commands)
        event.assert_called_once()

    def test_expand_storage_recovers_when_gpt_is_already_larger_than_kernel(self):
        before = {
            "pool": "homePool", "pool_size": 100, "health": "ONLINE",
            "supported": True, "unsupported_partitions": [], "disk": "/dev/sdb",
        }
        detected = before | {
            "disk_size": 400, "partition_size": 100, "partition_table_size": 400,
            "expandable": True, "partition_number": 1, "reserved_partition": None,
            "device": "/dev/sdb1",
        }
        kernel_ready = detected | {"partition_size": 400}
        after = kernel_ready | {"pool_size": 399, "free": 390, "expandable": False}
        commands = []

        def fake_run(argv, **_kwargs):
            commands.append(argv)
            return mock.Mock(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(self.peer, "storage_expand_status",
                               side_effect=[before, detected, kernel_ready, after]), \
             mock.patch.object(self.peer, "_rescan_storage_disk"), \
             mock.patch.object(self.peer, "run", side_effect=fake_run), \
             mock.patch.object(self.peer, "event"), \
             mock.patch.object(self.peer, "storage_expand_lock",
                               return_value=contextlib.nullcontext()):
            result = self.peer.expand_storage()
        self.assertTrue(result["changed"])
        self.assertIn(["partx", "--update", "--nr", "1", "/dev/sdb"], commands)
        self.assertNotIn(["growpart", "/dev/sdb", "1"], commands)
        self.assertFalse(any(command[0] == "sgdisk" for command in commands))

    def test_storage_rescan_uses_narrow_transient_systemd_unit(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return mock.Mock(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(self.peer, "run", side_effect=fake_run):
            self.peer._rescan_storage_disk(Path("/dev/sdb"))
        command, options = calls[0]
        self.assertEqual(command[0], "systemd-run")
        self.assertIn("--property=ProtectKernelTunables=true", command)
        self.assertIn(
            "--property=ReadWritePaths=/sys/class/block/sdb/device/rescan", command
        )
        self.assertEqual(command[-2:], ["/usr/bin/tee", "/sys/class/block/sdb/device/rescan"])
        self.assertEqual(options["input_data"], b"1\n")
        self.assertEqual(calls[1][0], ["udevadm", "settle"])

    def test_expand_storage_does_not_modify_disk_without_new_capacity(self):
        before = {
            "pool": "homePool", "pool_size": 100, "health": "ONLINE",
            "supported": True, "unsupported_partitions": [], "disk": "/dev/sdb",
        }
        detected = before | {"expandable": False}
        with mock.patch.object(self.peer, "storage_expand_status", side_effect=[before, detected]), \
             mock.patch.object(self.peer, "_rescan_storage_disk"), \
             mock.patch.object(self.peer, "run") as runner, \
             mock.patch.object(self.peer, "storage_expand_lock",
                               return_value=contextlib.nullcontext()):
            result = self.peer.expand_storage()
        self.assertFalse(result["changed"])
        runner.assert_not_called()

    def test_agent_address_uses_exact_asset_row_not_duplicate_display_name(self):
        asset = "a" * 32
        output = (
            "+---+---+\n"
            f"| {asset} | 10.0.3.44 | uuid | rj-or-sb | DLA | no | no | no | path |\n"
        ).encode()
        completed = mock.Mock(returncode=0, stdout=output, stderr=b"")
        with mock.patch.object(self.peer, "run", return_value=completed):
            self.assertEqual(self.peer.agent_address(asset), "10.0.3.44")

    def test_peer_service_defaults_to_unix_socket_without_tcp_listener(self):
        config = self.peer.default_config()
        self.assertNotIn("listen", config)
        self.assertNotIn("port", config)
        self.assertEqual(self.peer.SOCKET_PATH, self.root / "peer.sock")

    def test_replication_account_permissions_are_repaired_after_uid_changes(self):
        ssh_dir = self.peer.AUTHORIZED_KEYS_PATH.parent
        ssh_dir.mkdir(parents=True, exist_ok=True)
        self.peer.AUTHORIZED_KEYS_PATH.write_text("restricted key\n")
        account = SimpleNamespace(pw_uid=995, pw_gid=995)
        fake_pwd = SimpleNamespace(getpwnam=lambda _name: account)
        with mock.patch.dict(sys.modules, {"pwd": fake_pwd}), \
                mock.patch.object(self.peer.os, "chown", create=True) as chown, \
                mock.patch.object(self.peer.os, "chmod") as chmod:
            self.peer.repair_replication_account_permissions()

        chown.assert_any_call(self.peer.STATE_DIR, 995, 995)
        chown.assert_any_call(ssh_dir, 995, 995)
        chown.assert_any_call(self.peer.AUTHORIZED_KEYS_PATH, 995, 995)
        chmod.assert_any_call(ssh_dir, 0o700)
        chmod.assert_any_call(self.peer.AUTHORIZED_KEYS_PATH, 0o600)

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

    def test_update_api_uses_only_fixed_root_updater_commands(self):
        self.peer.UPGRADE_COMMAND.parent.mkdir(parents=True, exist_ok=True)
        self.peer.UPGRADE_COMMAND.write_text("#!/bin/sh\n")
        status = {
            "current": {"version": "0.6.1", "sequence": 1},
            "updater_version": 2,
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps(status).encode(), stderr=b"")
        with mock.patch.object(self.peer, "run", return_value=completed) as execute:
            value = self.peer.upgrade_status()
        self.assertEqual(value["channel"], "stable")
        command = execute.call_args_list[0].args[0]
        self.assertEqual(command[-1], "status")
        self.assertNotIn("shell", execute.call_args_list[0].kwargs)

        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("'update-status' => ['GET'", controller)
        self.assertIn("'update-check' => ['GET'", controller)
        self.assertIn("'update-install' => ['POST'", controller)
        self.assertIn("'update-policy' =>", controller)

    def test_update_policy_controls_native_channel_and_window(self):
        self.assertEqual(self.peer.upgrade_policy(), {
            "channel": "stable", "window": {"start": 21, "end": 5}
        })
        value = self.peer.set_upgrade_policy({
            "channel": "none", "window": {"start": 22, "end": 6}
        })
        self.assertEqual(value["policy"]["channel"], "none")
        self.assertEqual(self.peer.upgrade_policy()["window"], {"start": 22, "end": 6})
        with self.assertRaises(self.peer.PeerError):
            self.peer.set_upgrade_policy({
                "channel": "stable", "window": {"start": 1, "end": 3}
            })

    def test_web_update_defers_service_restart_until_transaction_finishes(self):
        self.peer.UPGRADE_COMMAND.parent.mkdir(parents=True, exist_ok=True)
        self.peer.UPGRADE_COMMAND.write_text("#!/bin/sh\n")
        completed = mock.Mock(returncode=0, stdout=b"Recovera 0.6.2 installed\n", stderr=b"")
        with mock.patch.object(self.peer, "run", return_value=completed) as execute:
            result = self.peer.upgrade_install()
        self.assertTrue(result["restart_scheduled"])
        install_call = execute.call_args_list[0]
        self.assertEqual(install_call.args[0][-1], "install")
        self.assertEqual(install_call.kwargs["env"]["RECOVERA_DEFER_SERVICE_RESTART"], "1")
        self.assertEqual(execute.call_args_list[1].args[0][0], "systemd-run")

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

    def test_known_hosts_ignores_legacy_dss_when_modern_key_is_available(self):
        lines = self.peer.known_host_lines("10.0.0.2", 22, [
            "ssh-dss AAAALEGACY",
            "ssh-ed25519 AAAAMODERN",
        ])
        self.assertEqual(lines, ["10.0.0.2 ssh-ed25519 AAAAMODERN"])

    def test_known_hosts_requires_at_least_one_supported_key(self):
        with self.assertRaisesRegex(self.peer.PeerError, "supported SSH host key"):
            self.peer.known_host_lines("10.0.0.2", 22, ["ssh-dss AAAALEGACY"])

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


    # --- Live replication activity (Synchronize page) -------------------------

    def fake_proc(self, processes, *, boot_age=100000):
        """Build a fake /proc with {pid: (argv, io_counters, seconds_since_start)}."""
        proc = self.root / "proc"
        proc.mkdir(exist_ok=True)
        boot = int(self.peer.time.time()) - boot_age
        (proc / "stat").write_text(f"cpu 1 2 3\nbtime {boot}\n", encoding="ascii")
        hertz = 100
        with contextlib.suppress(AttributeError, ValueError, OSError):
            hertz = int(os.sysconf("SC_CLK_TCK"))
        for pid, (argv, counters, age) in processes.items():
            entry = proc / str(pid)
            entry.mkdir()
            (entry / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in argv) + b"\0")
            (entry / "io").write_text(
                "".join(f"{name}: {value}\n" for name, value in counters.items()), encoding="ascii")
            ticks = int((boot_age - age) * hertz)
            fields = ["S"] + ["0"] * 18 + [str(ticks)] + ["0"] * 5
            (entry / "stat").write_text(f"{pid} (zfs) " + " ".join(fields) + "\n", encoding="ascii")
        return proc

    def test_replication_activity_reports_tracked_outbound_progress(self):
        peer_id = "12345678-1234-1234-1234-123456789abc"
        asset = "4" * 32
        cfg = self.peer.config()
        cfg["peers"][peer_id] = {"name": "Backup-Bitches", "enabled": True}
        self.peer.save_config(cfg)
        self.peer.write_transfer_record("outbound", f"{peer_id}:{asset}", {
            "direction": "outbound", "asset": asset, "name": "jprod-sb", "peer_id": peer_id,
            "peer_name": "Backup-Bitches", "snapshot": "1794086526", "mode": "resumed",
            "bytes_total": 1000, "bytes_before": 100, "started": int(self.peer.time.time()) - 10,
            "pid": 4242,
        })
        proc = self.fake_proc({4242: (["zfs", "send", "-t", "1-abc-def"], {"wchar": 400}, 10)})
        with mock.patch.object(self.peer, "PROC_ROOT", proc):
            activity = self.peer.replication_activity()
        self.assertEqual(activity["active"]["inbound"], [])
        item = activity["active"]["outbound"][0]
        self.assertEqual(item["status"], "transferring")
        self.assertEqual(item["name"], "jprod-sb")
        self.assertEqual(item["peer_name"], "Backup-Bitches")
        self.assertEqual(item["mode"], "resumed")
        self.assertEqual(item["bytes_done"], 500)
        self.assertEqual(item["percent"], 50.0)
        self.assertGreater(item["rate_bps"], 0)
        self.assertGreater(item["eta_seconds"], 0)

    def test_replication_activity_discovers_receive_started_by_older_code(self):
        source_id = "ab15e185-157d-487b-abe4-6a064c26decc"
        asset = "47f5020e4d344b0cac8cdb1f193c0f9b"
        cfg = self.peer.config()
        cfg["sources"][source_id] = {"name": "recovera", "address": "10.10.20.10"}
        self.peer.save_config(cfg)
        with self.peer.locked_state() as value:
            value["received"] = {asset: {"source_id": source_id, "snapshot": "1794086526",
                                         "status": "receiving", "updated": 1}}
        dataset = f"homePool/home/agents/{asset}"
        proc = self.fake_proc({
            77: (["zfs", "receive", "-u", "-s", dataset], {"rchar": 8_000_000}, 100),
            78: (["zfs", "send", "-nP", f"{dataset}@1794086526"], {"wchar": 5}, 1),
            79: (["python3", "/usr/local/sbin/recovera-peer", "serve"], {"rchar": 1}, 1),
        })
        with mock.patch.object(self.peer, "PROC_ROOT", proc):
            activity = self.peer.replication_activity()
        self.assertEqual(activity["active"]["outbound"], [])
        self.assertEqual(len(activity["active"]["inbound"]), 1)
        item = activity["active"]["inbound"][0]
        self.assertEqual(item["status"], "transferring")
        self.assertEqual(item["asset"], asset)
        self.assertEqual(item["bytes_done"], 8_000_000)
        self.assertIsNone(item["bytes_total"])
        self.assertEqual(item["source_name"], "recovera")
        self.assertEqual(item["source_address"], "10.10.20.10")
        self.assertIsNone(item["mode"])
        self.assertEqual(item["snapshot"], "1794086526")
        self.assertEqual(activity["paired"], {"targets": 0, "sources": 1})

    def test_zfs_transfer_process_ignores_dry_runs_and_classifies_streams(self):
        classify = self.peer._zfs_transfer_process
        self.assertIsNone(classify(["zfs", "send", "-nP", "pool/a@1"]))
        self.assertIsNone(classify(["zfs", "send", "-nvP", "-t", "token"]))
        self.assertIsNone(classify(["zfs", "list", "-H"]))
        self.assertEqual(classify(["zfs", "send", "pool/a@1"]), ("outbound", "pool/a", "full"))
        self.assertEqual(classify(["zfs", "send", "-I", "pool/a@1", "pool/a@2"]),
                         ("outbound", "pool/a", "incremental"))
        self.assertEqual(classify(["zfs", "send", "-t", "token"]), ("outbound", "", "resumed"))
        self.assertEqual(classify(["/usr/sbin/zfs", "receive", "-u", "-s", "pool/a"]),
                         ("inbound", "pool/a", ""))

    def test_replication_activity_marks_dead_transfers_interrupted_and_expires_old_records(self):
        peer_id = "12345678-1234-1234-1234-123456789abc"
        source_id = "87654321-4321-4321-4321-cba987654321"
        fresh, old, paused = "5" * 32, "6" * 32, "7" * 32
        self.peer.write_transfer_record("outbound", f"{peer_id}:{fresh}", {
            "direction": "outbound", "asset": fresh, "name": "fresh", "pid": 999,
            "mode": "full", "bytes_total": 10, "bytes_before": 0, "started": 1})
        self.peer.write_transfer_record("outbound", f"{peer_id}:{old}", {
            "direction": "outbound", "asset": old, "name": "old", "pid": 998})
        old_path = self.peer._transfer_record_path("outbound", f"{peer_id}:{old}")
        record = json.loads(old_path.read_text(encoding="utf-8"))
        record["updated"] = int(self.peer.time.time()) - 3 * 24 * 3600
        old_path.write_text(json.dumps(record), encoding="utf-8")
        with self.peer.locked_state() as value:
            value["received"] = {paused: {"source_id": source_id, "snapshot": "1",
                                          "status": "receiving", "updated": 1}}
        proc = self.fake_proc({})
        with mock.patch.object(self.peer, "PROC_ROOT", proc):
            activity = self.peer.replication_activity()
        outbound = activity["active"]["outbound"]
        self.assertEqual([item["asset"] for item in outbound], [fresh])
        self.assertEqual(outbound[0]["status"], "interrupted")
        self.assertNotIn("pid", outbound[0])
        self.assertFalse(old_path.exists())
        inbound = activity["active"]["inbound"]
        self.assertEqual([(item["asset"], item["status"]) for item in inbound],
                         [(paused, "interrupted")])

    def test_receive_dataset_records_live_transfer_and_clears_it(self):
        source = "12345678-1234-1234-1234-123456789abc"
        asset = "8" * 32
        cfg = self.peer.config()
        cfg["sources"][source] = {"name": "Bitches-DC"}
        self.peer.save_config(cfg)
        agent_info = json.dumps({"hostname": "jprod-sb"}).encode()
        metadata = {
            "asset": asset, "source_id": source, "source_numeric_id": 1234567890,
            "source_name": "Bitches-DC",
            "files": {"agentInfo": self.peer.base64.b64encode(agent_info).decode()},
        }
        seen = {}

        def communicate():
            path = self.peer._transfer_record_path("inbound", asset)
            seen.update(json.loads(path.read_text(encoding="utf-8")))
            return b"", b""

        process = mock.Mock(pid=555, returncode=0, communicate=communicate)
        with mock.patch.object(self.peer, "zfs_exists", return_value=False), \
             mock.patch.object(self.peer, "load_origin", return_value={}), \
             mock.patch.object(self.peer, "zfs_snapshots", return_value=[]), \
             mock.patch.object(self.peer, "install_metadata"), \
             mock.patch.object(self.peer, "prune_received_snapshots", return_value=[]), \
             mock.patch.object(self.peer, "run", return_value=mock.Mock(returncode=0, stdout=b"", stderr=b"")), \
             mock.patch.object(self.peer.subprocess, "Popen", return_value=process):
            answer = self.peer.receive_dataset(source, asset, "1794086526", "-",
                                               self.peer.encode_metadata(metadata), False, mock.Mock())
        self.assertTrue(answer["ok"])
        self.assertEqual(seen["pid"], 555)
        self.assertEqual(seen["name"], "jprod-sb")
        self.assertEqual(seen["source_name"], "Bitches-DC")
        self.assertEqual(seen["mode"], "full")
        self.assertFalse(self.peer._transfer_record_path("inbound", asset).exists())

    def replicate_fixture(self, remote):
        peer_id = "12345678-1234-1234-1234-123456789abc"
        asset = "9" * 32
        cfg = self.peer.config()
        cfg["peers"][peer_id] = {"name": "Backup-Bitches", "host": "10.0.3.187", "enabled": True}
        self.peer.save_config(cfg)
        patches = [
            mock.patch.object(self.peer, "zfs_exists", return_value=True),
            mock.patch.object(self.peer, "load_origin", return_value={}),
            mock.patch.object(self.peer, "zfs_snapshots", return_value=["1794086526"]),
            mock.patch.object(self.peer, "remote_json", return_value=remote),
            mock.patch.object(self.peer, "zfs_send_estimate", return_value=1000),
            mock.patch.object(self.peer, "collect_metadata", return_value={}),
            mock.patch.object(self.peer, "encode_metadata", return_value="meta"),
            mock.patch.object(self.peer, "asset_display_name", return_value="jprod-sb"),
        ]
        return peer_id, asset, patches

    def test_replicate_records_outbound_transfer_and_clears_it_on_failure(self):
        peer_id, asset, patches = self.replicate_fixture({"snapshots": [], "storage": {}})
        seen = {}

        def transfer(send, peer, remote, speed, on_start=None):
            on_start(321)
            path = self.peer._transfer_record_path("outbound", f"{peer_id}:{asset}")
            seen.update(json.loads(path.read_text(encoding="utf-8")))
            raise self.peer.PeerError("link dropped")

        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(self.peer, "transfer_stream", side_effect=transfer))
            with self.assertRaises(self.peer.PeerError):
                self.peer.replicate(asset, peer_id)
        self.assertEqual(seen["pid"], 321)
        self.assertEqual(seen["mode"], "full")
        self.assertEqual(seen["bytes_total"], 1000)
        self.assertEqual(seen["peer_name"], "Backup-Bitches")
        self.assertFalse(list((self.peer.TRANSFER_DIR).glob("*.json")))

    def test_replicate_resume_counts_bytes_already_on_target(self):
        peer_id, asset, patches = self.replicate_fixture(
            {"snapshots": [], "storage": {}, "resume_token": "1-abc"})
        seen = {}

        def transfer(send, peer, remote, speed, on_start=None):
            on_start(654)
            path = self.peer._transfer_record_path("outbound", f"{peer_id}:{asset}")
            seen.update(json.loads(path.read_text(encoding="utf-8")))
            seen["send"] = send

        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(self.peer, "transfer_stream", side_effect=transfer))
            stack.enter_context(mock.patch.object(self.peer, "zfs_send_resume_estimate", return_value=300))
            result = self.peer.replicate(asset, peer_id)
        self.assertEqual(result["status"], "resumed")
        self.assertEqual(seen["send"], ["zfs", "send", "-t", "1-abc"])
        self.assertEqual(seen["bytes_before"], 700)
        self.assertFalse(list((self.peer.TRANSFER_DIR).glob("*.json")))

    def test_replication_activity_route_is_proxied_for_the_webui(self):
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("'replication-activity' => ['GET', '/v1/admin/replication-activity']", controller)
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"/v1/admin/replication-activity"', source)

if __name__ == "__main__":
    unittest.main()
