import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "gateway"
NEW_CHANNELS = "stable jammy-noble-transition noble-stable jammy-noble-candidate-transition"


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


def load_gateway():
    if str(GATEWAY) not in sys.path:
        sys.path.insert(0, str(GATEWAY))
    if "recovera_gateway_auth" not in sys.modules:
        load_auth()
    loader = importlib.machinery.SourceFileLoader(
        "recovera_gateway", str(GATEWAY / "recovera-gateway")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
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

    def test_container_uses_fixed_unprivileged_identity_for_secret_mounts(self):
        dockerfile = (GATEWAY / "Dockerfile").read_text()
        saltbox_installer = (GATEWAY / "install-saltbox.sh").read_text()
        self.assertIn("--uid 39871 --gid 39871", dockerfile)
        self.assertIn("-g 39871 -m 0640", saltbox_installer)
        self.assertIn("USER recovera-gateway", dockerfile)


class RecoveraGatewayGitHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_gateway()

    def test_public_repository_request_does_not_require_or_send_token(self):
        configuration = mock.Mock()
        configuration.github_token.return_value = None
        opener = mock.Mock()
        response = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(self.module.urllib.request, "build_opener", return_value=opener):
            result = self.module.GitHub(configuration).request("https://api.github.com/example")
        self.assertIs(result, response)
        request = opener.open.call_args.args[0]
        self.assertNotIn("Authorization", dict(request.header_items()))

    def test_private_repository_request_sends_configured_token(self):
        configuration = mock.Mock()
        configuration.github_token.return_value = "read-only-secret"
        opener = mock.Mock()
        opener.open.return_value = mock.Mock()
        with mock.patch.object(self.module.urllib.request, "build_opener", return_value=opener):
            self.module.GitHub(configuration).request("https://api.github.com/example")
        request = opener.open.call_args.args[0]
        self.assertEqual(dict(request.header_items())["Authorization"], "Bearer read-only-secret")

    def cache_for(self, directory, channels):
        configuration = mock.Mock()
        configuration.cache = Path(directory)
        configuration.channels = channels
        configuration.repository = "falco1717/recovera"
        configuration.branch = "main"
        return self.module.Cache(configuration)

    @staticmethod
    def contents(pointer):
        import base64
        return {"content": base64.b64encode(json.dumps(pointer).encode()).decode()}

    def test_unpublished_channel_serves_an_empty_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.cache_for(directory, ["jammy-noble-transition"])
            empty = {"schema": 1, "channel": "jammy-noble-transition", "release_tag": None,
                     "manifest_asset": None, "signature_asset": None, "sequence": 0, "version": None}
            with mock.patch.object(cache.github, "json", return_value=self.contents(empty)):
                result = cache.sync_channel("jammy-noble-transition")
            self.assertIsNone(result["release_tag"])
            served = cache.read_channel("jammy-noble-transition")
            self.assertIsNone(served["release_tag"])
            self.assertEqual(served["sequence"], 0)
            with self.assertRaises(self.module.GatewayError):
                cache.release_channel("image-v0.7.0")
            wrong = dict(empty, channel="stable")
            with mock.patch.object(cache.github, "json", return_value=self.contents(wrong)):
                with self.assertRaises(self.module.GatewayError):
                    cache.sync_channel("jammy-noble-transition")

    def test_one_failing_channel_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.cache_for(directory, ["stable", "jammy-noble-transition", "noble-stable"])
            calls = []

            def sync_channel(channel):
                calls.append(channel)
                if channel == "jammy-noble-transition":
                    raise self.module.GatewayError("GitHub is unavailable")
                return {"channel": channel, "release_tag": "package-v1", "version": "1"}

            with mock.patch.object(cache, "sync_channel", side_effect=sync_channel):
                results = cache.sync()
            self.assertEqual(calls, ["stable", "jammy-noble-transition", "noble-stable"])
            self.assertEqual(results[1], {"channel": "jammy-noble-transition", "error": "GitHub is unavailable"})
            self.assertEqual(results[2]["channel"], "noble-stable")

    def test_saltbox_gateways_serve_the_os_upgrade_channels(self):
        for name in ("compose.saltbox.yaml", "compose.yaml"):
            self.assertIn(NEW_CHANNELS, (GATEWAY / name).read_text())
        self.assertIn(NEW_CHANNELS, (GATEWAY / "install-saltbox.sh").read_text())
        for channel in ("jammy-noble-transition", "noble-stable", "jammy-noble-candidate-transition"):
            pointer = json.loads((ROOT / "upgrade" / "channels" / f"{channel}.json").read_text())
            self.assertEqual(pointer["channel"], channel)
            self.assertEqual(pointer["schema"], 1)

    def test_gateway_handles_another_process_winning_release_publish(self):
        source = (GATEWAY / "recovera-gateway").read_text()
        self.assertIn("errno.ENOTEMPTY", source)
        # The winner's release is verified like any cached release.
        sync = source[source.index("    def sync_channel"):source.index("    def sync(self)")]
        self.assertIn("self.verify_cached_release(tag, manifest_name)", sync)
        self.assertLess(sync.index("self.verify_cached_release(tag, manifest_name)"),
                        sync.rindex("atomic_bytes(self.channel_path(channel)"))

    def test_gateway_root_has_branded_operational_page(self):
        page = self.module.LANDING_PAGE.decode("utf-8")
        self.assertIn("<title>Recovera Update Gateway</title>", page)
        self.assertIn("Update Gateway", page)
        self.assertIn("Operational", page)
        self.assertNotIn("Datto", page)

    def test_gateway_html_response_uses_security_headers(self):
        source = (GATEWAY / "recovera-gateway").read_text()
        self.assertIn("Content-Security-Policy", source)
        self.assertIn("frame-ancestors 'none'", source)
        self.assertIn('if parsed.path == "/":', source)


class RecoveraGatewayRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_gateway()

    def test_byte_range_parsing(self):
        parse = self.module.parse_byte_range
        self.assertIsNone(parse(None, 100))
        self.assertEqual(parse("bytes=0-9", 100), (0, 9))
        self.assertEqual(parse("bytes=40-", 100), (40, 99))
        self.assertEqual(parse("bytes=90-500", 100), (90, 99))
        self.assertEqual(parse("bytes=-10", 100), (90, 99))
        self.assertEqual(parse("bytes=-500", 100), (0, 99))
        for bad in ("bytes=100-", "bytes=5-2", "bytes=0-1,5-6", "items=0-1", "bytes=-", "bytes=-0", "bytes=a-b"):
            self.assertEqual(parse(bad, 100), "unsatisfiable", bad)

    def _serve(self, path):
        import http.server
        import threading
        module = self.module

        class Handler(module.GatewayHandler):
            def credential(self, channel):
                if self.headers.get("Authorization") != "Bearer test":
                    raise module.AccessError("gateway credential is required")

        class Cache:
            def release_channel(self, tag):
                return "stable"

            def release_path(self, tag):
                return path.parent

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.cache = Cache()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def _get(self, port, headers):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("GET", "/v1/releases/image-v1/recovera-1.img.xz.part-000", headers=headers)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_release_asset_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovera-1.img.xz.part-000"
            data = bytes(range(256)) * 40
            path.write_bytes(data)
            port = self._serve(path)
            auth = {"Authorization": "Bearer test"}
            response, body = self._get(port, auth)
            self.assertEqual((response.status, body), (200, data))
            self.assertEqual(response.getheader("Accept-Ranges"), "bytes")
            response, body = self._get(port, auth | {"Range": "bytes=1000-"})
            self.assertEqual((response.status, body), (206, data[1000:]))
            self.assertEqual(response.getheader("Content-Range"), f"bytes 1000-{len(data) - 1}/{len(data)}")
            self.assertEqual(response.getheader("Content-Length"), str(len(data) - 1000))
            self.assertIn("immutable", response.getheader("Cache-Control"))
            response, body = self._get(port, auth | {"Range": "bytes=10-19"})
            self.assertEqual((response.status, body), (206, data[10:20]))
            for bad in (f"bytes={len(data)}-", "bytes=0-1,4-5"):
                response, body = self._get(port, auth | {"Range": bad})
                self.assertEqual(response.status, 416, bad)
                self.assertEqual(response.getheader("Content-Range"), f"bytes */{len(data)}")
            response, body = self._get(port, {"Range": "bytes=0-"})
            self.assertEqual(response.status, 401)


class RecoveraGatewayCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_gateway()

    def make_cache(self, root, channels=("stable", "noble-stable"), keep_previous=1):
        from types import SimpleNamespace
        configuration = SimpleNamespace(cache=Path(root), channels=list(channels), keep_previous=keep_previous,
                                        space_reserve=0)
        cache = self.module.Cache.__new__(self.module.Cache)
        cache.configuration = configuration
        import threading
        cache.lock = threading.Lock()
        return cache

    def publish(self, cache, channel, tag):
        release = cache.release_path(tag)
        release.mkdir(parents=True, exist_ok=True)
        (release / "recovera-image-manifest.json").write_text("{}")
        cache.channel_path(channel).parent.mkdir(parents=True, exist_ok=True)
        cache.channel_path(channel).write_text(json.dumps({"schema": 1, "channel": channel, "release_tag": tag}))
        cache.remember_release(channel, tag)

    def test_cached_release_is_rehashed_only_when_its_files_change(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.make_cache(directory)
            self.publish(cache, "stable", "image-v1")
            with mock.patch.object(cache, "verify_release") as verify:
                cache.verify_cached_release("image-v1", "recovera-image-manifest.json")
                cache.verify_cached_release("image-v1", "recovera-image-manifest.json")
                self.assertEqual(verify.call_count, 1)
                (cache.release_path("image-v1") / "recovera-image-manifest.json").write_text('{"x": 1}')
                cache.verify_cached_release("image-v1", "recovera-image-manifest.json")
                self.assertEqual(verify.call_count, 2)
            with mock.patch.object(cache, "verify_release", side_effect=self.module.GatewayError("bad")):
                (cache.release_path("image-v1") / "recovera-image-manifest.json").write_text('{"x": 22}')
                with self.assertRaises(self.module.GatewayError):
                    cache.verify_cached_release("image-v1", "recovera-image-manifest.json")
            self.assertFalse(cache.stamp_path("image-v1").exists())

    def test_cleanup_keeps_current_and_previous_release_per_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.make_cache(directory)
            for tag in ("package-v1", "package-v2", "package-v3"):
                self.publish(cache, "stable", tag)
            self.publish(cache, "noble-stable", "package-v1")
            orphan = cache.release_path("image-v0")
            orphan.mkdir(parents=True)
            fresh_partial = cache.release_path(".image-v9.abc")
            fresh_partial.mkdir()
            removed = cache.cleanup()
            self.assertEqual(sorted(removed), ["image-v0"])
            remaining = sorted(item.name for item in (Path(directory) / "releases").iterdir())
            self.assertEqual(remaining, [".image-v9.abc", "package-v1", "package-v2", "package-v3"])
            self.publish(cache, "noble-stable", "package-v3")
            self.publish(cache, "noble-stable", "package-v4")
            self.assertEqual(sorted(cache.cleanup()), ["package-v1"])

    def test_failed_sync_never_removes_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.make_cache(directory, channels=("stable",))
            self.publish(cache, "stable", "package-v1")
            cache.release_path("image-v0").mkdir(parents=True)
            with mock.patch.object(cache, "sync_channel", side_effect=self.module.GatewayError("GitHub is unreachable")):
                results = cache.sync()
            self.assertTrue(cache.release_path("image-v0").exists())
            self.assertEqual(results[0]["error"], "GitHub is unreachable")
            status = json.loads(cache.status_path().read_text())
            self.assertEqual(status["channels"]["stable"]["last_error"], "GitHub is unreachable")
            with mock.patch.object(cache, "sync_channel", return_value={
                    "channel": "stable", "release_tag": "package-v1", "version": "1", "sequence": 1}):
                results = cache.sync()
            self.assertFalse(cache.release_path("image-v0").exists())
            status = json.loads(cache.status_path().read_text())
            self.assertIsNone(status["channels"]["stable"]["last_error"])
            self.assertEqual(status["channels"]["stable"]["sequence"], 1)
            self.assertIn("free_bytes", status["cache"])
            self.assertNotIn("token", json.dumps(status).lower())

    def test_ready_only_when_every_channel_synced_recently(self):
        import time as clock
        with tempfile.TemporaryDirectory() as directory:
            cache = self.make_cache(directory, channels=("stable", "noble-stable"))
            cache.configuration.sync_interval = 900
            self.assertFalse(cache.ready())
            ok = {"last_success": 1, "last_error": None}
            status = {"time": int(clock.time()), "channels": {"stable": ok, "noble-stable": ok}}
            cache.status_path().write_text(json.dumps(status))
            self.assertTrue(cache.ready())
            status["channels"]["noble-stable"] = {"last_success": 1, "last_error": "GitHub is unreachable"}
            cache.status_path().write_text(json.dumps(status))
            self.assertFalse(cache.ready())
            status["channels"]["noble-stable"] = ok
            status["time"] = int(clock.time()) - 4 * 900
            cache.status_path().write_text(json.dumps(status))
            self.assertFalse(cache.ready())

    def test_release_larger_than_free_space_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.make_cache(directory)
            free = shutil.disk_usage(directory).free
            cache.require_space(1024)
            with self.assertRaisesRegex(self.module.GatewayError, "not enough cache space"):
                cache.require_space(free + 1)


if __name__ == "__main__":
    unittest.main()
