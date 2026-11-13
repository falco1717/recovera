import argparse
import os
import base64
import contextlib
import subprocess
import sys
import argparse
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "upgrade" / "recovera-upgrade"


def load_updater():
    loader = importlib.machinery.SourceFileLoader("recovera_upgrade", str(UPDATER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveraUpgradeTests(unittest.TestCase):
    JAMMY = {"id": "ubuntu", "version_id": "22.04", "codename": "jammy"}
    NOBLE = {"id": "ubuntu", "version_id": "24.04", "codename": "noble"}

    @classmethod
    def setUpClass(cls):
        cls.module = load_updater()

    def setUp(self):
        # Manifest validation checks the running OS; tests run on any host.
        patcher = mock.patch.object(self.module, "local_os", return_value=dict(self.JAMMY))
        patcher.start()
        self.addCleanup(patcher.stop)

    def manifest(self):
        return {
            "schema": 1,
            "version": "0.7.0",
            "sequence": 7,
            "channel": "stable",
            "architecture": "amd64",
            "minimum_updater": 1,
            "image": {
                "compression": "xz",
                "size": 10,
                "sha256": "a" * 64,
                "uncompressed_size": 20,
                "uncompressed_sha256": "b" * 64,
                "parts": [{"name": "recovera.img.xz.part-000", "size": 10, "sha256": "c" * 64}],
            },
        }

    def package_manifest(self):
        return {
            "schema": 2,
            "type": "package",
            "version": "0.7.1",
            "sequence": 8,
            "channel": "stable",
            "architecture": "amd64",
            "minimum_updater": 2,
            "download_size": 1234,
            "reboot_required": False,
            "packages": [{
                "name": "recovera-peer",
                "version": "0.7.1-1",
                "architecture": "all",
                "asset": "recovera-peer_0.7.1-1_all.deb",
                "size": 1234,
                "sha256": "d" * 64,
            }],
        }

    def test_manifest_requires_channel_pointer_agreement(self):
        pointer = {"version": "0.7.0", "sequence": 7}
        config = {"CHANNEL": "stable"}
        with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
            self.assertEqual(self.module.validate_manifest(self.manifest(), pointer, config)["sequence"], 7)
        pointer["sequence"] = 8
        with self.assertRaises(self.module.UpgradeError):
            self.module.validate_manifest(self.manifest(), pointer, config)

    def test_appliance_package_carries_agent_transfer_installer(self):
        builder = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text()
        self.assertIn('install -m 0755 "$ROOT/agents/linux/$file"', builder)
        self.assertIn("$stage/usr/share/recovera/agents/linux/", builder)

    def test_status_hides_cached_release_after_that_sequence_is_installed(self):
        state = {
            "installed_sequence": 24,
            "available": {
                "available": True,
                "version": "0.6.24",
                "sequence": 24,
                "current_version": "0.6.23",
            },
        }
        with mock.patch.object(self.module, "read_json", return_value=state):
            result = self.module.status_state({"version": "0.6.24", "sequence": 24})
        self.assertFalse(result["available"]["available"])
        self.assertEqual(result["available"]["current_version"], "0.6.24")
        self.assertTrue(state["available"]["available"])

    def test_manifest_rejects_path_traversal_asset(self):
        manifest = self.manifest()
        manifest["image"]["parts"][0]["name"] = "../image.part"
        with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
            with self.assertRaises(self.module.UpgradeError):
                self.module.validate_manifest(
                    manifest, {"version": "0.7.0", "sequence": 7}, {"CHANNEL": "stable"}
                )

    def test_package_manifest_accepts_small_application_release(self):
        manifest = self.package_manifest()
        pointer = {"version": "0.7.1", "sequence": 8}
        with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
            result = self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})
        self.assertEqual(result["download_size"], 1234)
        self.assertEqual(result["type"], "package")

    def test_package_manifest_rejects_boot_and_platform_packages(self):
        pointer = {"version": "0.7.1", "sequence": 8}
        for name in ("linux-image-6.8.0-94-generic", "grub-pc", "systemd", "zfsutils-linux"):
            with self.subTest(name=name):
                manifest = self.package_manifest()
                manifest["packages"][0]["name"] = name
                with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
                    with self.assertRaises(self.module.UpgradeError):
                        self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})

    def test_package_manifest_rejects_bad_size_and_traversal(self):
        pointer = {"version": "0.7.1", "sequence": 8}
        for mutation in ("size", "path"):
            manifest = self.package_manifest()
            if mutation == "size":
                manifest["download_size"] += 1
            else:
                manifest["packages"][0]["asset"] = "../recovera.deb"
            with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
                with self.assertRaises(self.module.UpgradeError):
                    self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})

    def test_updater_suspends_needrestart_for_package_transactions(self):
        source = (ROOT / "upgrade" / "recovera-upgrade").read_text(encoding="utf-8")
        main = source[source.index("def main():"):]
        self.assertLess(main.index('os.environ["NEEDRESTART_SUSPEND"] = "1"'), main.index("try:"))
        with mock.patch.dict("os.environ", {}, clear=False),              mock.patch.object(self.module, "parser") as parser,              mock.patch.object(self.module, "read_config", return_value={}),              mock.patch.object(self.module, "command_status", return_value=0) as status:
            parser.return_value.parse_args.return_value = mock.Mock(
                command="status", config=Path("/etc/recovera/upgrade.conf"))
            self.module.main()
            self.assertEqual(self.module.os.environ.get("NEEDRESTART_SUSPEND"), "1")
        status.assert_called_once()

    def test_package_install_is_offline_and_allows_no_removals(self):
        command = self.module.package_apt_command("install", [Path("/tmp/recovera.deb")])
        self.assertNotIn("--no-download", command)
        self.assertIn("Dir::Etc::sourcelist=/dev/null", command)
        self.assertIn("Dir::Etc::sourceparts=/dev/null", command)
        self.assertIn("Dir::Etc::sourcelist=/dev/null", command)
        self.assertIn("Dir::Etc::sourceparts=/dev/null", command)
        with mock.patch.object(self.module, "run") as runner:
            runner.return_value = mock.Mock(returncode=0, stdout=b"Remv openssh-server [1]\n", stderr=b"")
            with self.assertRaises(self.module.UpgradeError):
                self.module.verify_package_plan([Path("/tmp/recovera.deb")])
        with mock.patch.object(self.module, "run") as runner, \
             mock.patch.object(self.module, "dpkg_field", return_value="recovera-appliance"):
            runner.return_value = mock.Mock(returncode=0, stdout=b"Inst unsigned-helper (1 local)\n", stderr=b"")
            with self.assertRaises(self.module.UpgradeError):
                self.module.verify_package_plan([Path("/tmp/recovera.deb")])

    def test_operator_can_request_package_rollback(self):
        arguments = self.module.parser().parse_args(["rollback", "--reboot"])
        self.assertEqual(arguments.command, "rollback")
        self.assertTrue(arguments.reboot)

    def test_private_channel_error_explains_token_requirement(self):
        response = self.module.urllib.error.HTTPError(
            "https://api.github.com/repos/falco1717/recovera", 404,
            "Not Found", {}, io.BytesIO(b'{"message":"Not Found"}'),
        )
        opener = mock.Mock()
        opener.open.side_effect = response
        with mock.patch.object(self.module, "token", return_value=None), \
             mock.patch.object(self.module.urllib.request, "build_opener", return_value=opener), \
             self.assertRaisesRegex(self.module.UpgradeError, "read-only token"):
            self.module.request("https://api.github.com/repos/falco1717/recovera", {
                "TOKEN_FILE": "/etc/recovera/github-token",
            })

    def test_public_channel_and_assets_do_not_use_github_api(self):
        pointer = {
            "schema": 1, "channel": "stable", "release_tag": "package-v0.7.0",
            "manifest_asset": "manifest.json", "signature_asset": "manifest.json.sig",
            "sequence": 7, "version": "0.7.0",
        }
        response = io.BytesIO(json.dumps(pointer).encode())
        config = {
            "REPOSITORY": "falco1717/recovera", "CHANNEL": "stable",
            "CHANNEL_BRANCH": "main", "HOST_ROOT": "/host",
        }
        with mock.patch.object(self.module, "token", return_value=None), \
             mock.patch.object(self.module, "request", return_value=response) as requester, \
             mock.patch.object(self.module, "github_json") as github_api:
            self.assertEqual(self.module.fetch_channel(config), pointer)
            url = requester.call_args.args[0]
            self.assertTrue(url.startswith("https://raw.githubusercontent.com/"))
            assets = self.module.release_assets(pointer, config)
            github_api.assert_not_called()
        self.assertEqual(
            assets["__release_base_url__"],
            "https://github.com/falco1717/recovera/releases/download/package-v0.7.0",
        )

    def test_authenticated_private_channel_retains_api_support(self):
        config = {
            "REPOSITORY": "falco1717/recovera", "CHANNEL": "stable",
            "CHANNEL_BRANCH": "main", "HOST_ROOT": "/host",
        }
        release = {"assets": [{"name": "manifest.json", "url": "https://api.github.test/1"}]}
        with mock.patch.object(self.module, "token", return_value="read-only-token"), \
             mock.patch.object(self.module, "github_json", return_value=release) as github_api:
            assets = self.module.release_assets({"release_tag": "package-v0.7.0"}, config)
        self.assertEqual(assets["manifest.json"], "https://api.github.test/1")
        github_api.assert_called_once()

    def test_gateway_channel_and_assets_fail_over_in_order(self):
        pointer = {
            "schema": 1, "channel": "stable", "release_tag": "package-v0.7.0",
            "manifest_asset": "manifest.json", "signature_asset": "manifest.json.sig",
            "sequence": 7, "version": "0.7.0",
        }
        config = {
            "REPOSITORY": "falco1717/recovera", "CHANNEL": "stable",
            "CHANNEL_BRANCH": "main", "HOST_ROOT": "/host",
            "UPDATE_ORIGINS": "https://west.example https://east.example",
        }
        with mock.patch.dict("os.environ", {"RECOVERA_GATEWAY_TOKEN": "rgt1.e30.c2ln"}), \
             mock.patch.object(
            self.module, "request",
            side_effect=[self.module.UpgradeError("west unavailable"),
                         io.BytesIO(json.dumps(pointer).encode())],
        ) as requester:
            self.assertEqual(self.module.fetch_channel(config), pointer)
            assets = self.module.release_assets(pointer, config)
        self.assertEqual(requester.call_count, 2)
        self.assertEqual(config["_ACTIVE_GATEWAY_ORIGIN"], "https://east.example")
        self.assertEqual(assets["__release_base_urls__"], [
            "https://east.example/v1/releases/package-v0.7.0",
            "https://west.example/v1/releases/package-v0.7.0",
        ])

    def test_gateway_asset_download_fails_over(self):
        assets = {"__release_base_urls__": [
            "https://west.example/v1/releases/package-v0.7.0",
            "https://east.example/v1/releases/package-v0.7.0",
        ]}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "package.deb"
            def download_side_effect(url, output, _config, **_kwargs):
                if "west.example" in url:
                    raise self.module.UpgradeError("offline")
                Path(output).write_bytes(b"package")
            with mock.patch.object(self.module, "download", side_effect=download_side_effect) as downloader:
                self.module.obtain_asset("package.deb", assets, target, {})
            self.assertEqual(target.read_bytes(), b"package")
            self.assertEqual(downloader.call_count, 2)

    def test_gateway_origin_requires_https_and_exact_credential_host(self):
        with self.assertRaises(self.module.UpgradeError):
            self.module.gateway_origins({"UPDATE_ORIGINS": "http://updates.example"})
        config = {
            "UPDATE_ORIGINS": "https://updates.example",
            "GATEWAY_TOKEN_FILE": "/missing",
        }
        with mock.patch.object(self.module, "gateway_token", return_value="gateway-secret"), \
             mock.patch.object(self.module, "token", return_value="github-secret"):
            self.assertEqual(
                self.module.credential_for_url("https://updates.example/v1/channels/stable.json", config),
                "gateway-secret",
            )
            self.assertIsNone(
                self.module.credential_for_url("https://updates.example.evil/v1/channel", config)
            )
            self.assertEqual(
                self.module.credential_for_url("https://api.github.com/repos/o/r", config),
                "github-secret",
            )

    def test_pointer_rejects_path_traversal_before_asset_download(self):
        arguments = mock.Mock(
            channel_file=ROOT / "upgrade" / "channels" / "stable.json",
            source_dir=ROOT / "upgrade",
            signers=ROOT / "upgrade" / "keys" / "recovera-release-signers",
        )
        pointer = {
            "release_tag": "image-v1", "manifest_asset": "../../root-owned",
            "signature_asset": "manifest.sig", "version": "1", "sequence": 1,
        }
        with mock.patch.object(self.module, "fetch_channel", return_value=pointer), \
             mock.patch.object(self.module, "release_assets", return_value={}):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(self.module.UpgradeError):
                    self.module.get_release({"CHANNEL": "stable"}, arguments, Path(directory))

    def test_monotonic_sequence_prevents_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"installed_sequence": 9}))
            environment = {
                "RECOVERA_UPGRADE_STATE": str(state),
                "RECOVERA_RELEASE_FILE": str(Path(directory) / "none"),
            }
            with mock.patch.dict("os.environ", environment):
                with self.assertRaises(self.module.UpgradeError):
                    self.module.ensure_newer(self.manifest())

    def test_channel_points_to_current_package_release(self):
        channel = json.loads((ROOT / "upgrade" / "channels" / "stable.json").read_text())
        self.assertEqual(channel["type"], "package")
        self.assertEqual(channel["release_tag"], "package-v0.6.43")
        self.assertEqual(channel["version"], "0.6.43")
        self.assertEqual(channel["sequence"], 42)

    def test_empty_channel_is_a_successful_no_update_check(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "upgrade.conf"
            channel = Path(directory) / "stable.json"
            config.write_text(
                "REPOSITORY=falco1717/recovera\nCHANNEL=stable\n"
                "CHANNEL_BRANCH=main\nHOST_ROOT=/host\n"
            )
            channel.write_text(json.dumps({
                "schema": 1, "channel": "stable", "release_tag": None,
                "manifest_asset": None, "signature_asset": None,
                "sequence": 0, "version": None,
            }))
            arguments = self.module.parser().parse_args([
                "--config", str(config), "check", "--channel-file",
                str(channel),
            ])
            self.assertEqual(self.module.command_check(self.module.read_config(config), arguments), 0)

    def test_private_signing_key_is_not_in_repository(self):
        names = [path.name for path in ROOT.rglob("*") if path.is_file()]
        self.assertNotIn("recovera-upgrade-signing-key", names)

    def test_setup_installs_but_does_not_enable_image_layout(self):
        setup = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn('phase p79 "signed package and image upgrade client"', setup)
        self.assertIn("p79_image_updater()", setup)
        self.assertNotIn("image-layout.json <<", setup)

    def test_release_uses_signature_namespace_and_split_assets(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        self.assertIn("-n recovera-upgrade", builder)
        self.assertIn('split -b "$PART_SIZE"', builder)
        self.assertIn("uncompressed_sha256", builder)
        self.assertIn('if [ -n "$SIGNING_KEY" ]', builder)
        self.assertNotIn('mount --rbind "/$filesystem"', builder)
        self.assertIn('mount -t sysfs sysfs "$mountpoint/sys"', builder)
        self.assertIn('--compression-level)', builder)
        self.assertIn('xz -T0 "-$COMPRESSION_LEVEL"', builder)
        self.assertIn("minimum_bytes + 2 * 1024 * 1024 * 1024", builder)
        self.assertIn("RECOVERA_IMAGE_WORK_ROOT", builder)

    def test_package_release_is_signed_small_and_blocks_platform_changes(self):
        builder = (ROOT / "tools" / "build-package-release.sh").read_text()
        publisher = (ROOT / "tools" / "publish-package-release.sh").read_text()
        self.assertIn("recovera-package-manifest.json", builder)
        self.assertIn("minimum_updater': 2", builder)
        self.assertIn("platform package", builder)
        self.assertIn("-n recovera-upgrade", builder)
        self.assertIn("package-v$VERSION", publisher)
        self.assertIn(".packages[].asset", publisher)

    def test_fresh_bundle_builds_control_plane_rollback_baseline(self):
        bundle = (ROOT / "tools" / "make-bundle.sh").read_text()
        control = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text()
        self.assertIn("build-recovera-appliance-deb.sh", bundle)
        self.assertIn("Package: recovera-appliance", control)
        self.assertIn("recovera-upgrade-check.timer", control)
        self.assertIn("recovera-upgrade-schedule", control)
        self.assertIn("apply-branding.py", control)
        self.assertIn("REQUIRE_BASELINE_PACKAGES=recovera-appliance", (ROOT / "upgrade" / "recovera-upgrade.conf").read_text())
        self.assertIn("RECOVERA_DEFER_SERVICE_RESTART", control)
        self.assertIn('cat > "$stage/DEBIAN/preinst"', control)
        self.assertIn("/etc/systemd/system/datto-sshd-configure.service.d", control)
        self.assertIn("/etc/systemd/system/datto-firewall-share-sync.service.d", control)
        self.assertIn("/usr/share/recovera/defaults", control)
        self.assertIn("/usr/local/lib/recovera-upgrade", control)
        schedule = (ROOT / "upgrade" / "recovera-upgrade-schedule").read_text()
        self.assertIn('channel == "none"', schedule)
        self.assertIn('UPDATER, "check", "--cache"', schedule)
        self.assertIn('UPDATER, "install", "--reboot"', schedule)
        timer = (ROOT / "upgrade" / "recovera-upgrade-check.timer").read_text()
        self.assertIn("OnCalendar=hourly", timer)
        service = (ROOT / "upgrade" / "recovera-upgrade-check.service").read_text()
        self.assertIn("ProtectSystem=false", service)
        self.assertIn("TimeoutStartSec=infinity", service)

    def test_assembler_reclaims_verified_parts_before_decompression(self):
        self.assertIn("local.unlink()", UPDATER.read_text())

    def test_configuration_migration_is_allowlisted(self):
        migration = (ROOT / "upgrade" / "recovera-migrate-config").read_text()
        self.assertIn("/datto/config", migration)
        self.assertIn("/etc/recovera-peer", migration)
        self.assertIn("/etc/NetworkManager/system-connections", migration)
        self.assertIn("/etc/fstab", migration)
        self.assertIn("/etc/hosts", migration)
        self.assertNotIn("copy_path /etc\n", migration)
        self.assertNotIn("/home/agents", migration)

    def test_builder_removes_appliance_identity(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        for value in (
            "github-token", "backup-admin.json", "ssh_host_*", "deviceID",
            "/etc/machine-id", "/etc/recovera-peer", "/var/lib/recovera-peer",
            "recovera.localdomain recovera",
        ):
            self.assertIn(value, builder)

    def test_validation_service_has_no_multi_user_ordering_cycle(self):
        unit = (ROOT / "upgrade" / "recovera-upgrade-validate.service").read_text()
        self.assertIn("WantedBy=multi-user.target", unit)
        self.assertNotIn("After=multi-user.target", unit)

    def test_first_image_can_fall_back_to_conventional_root(self):
        boot = (ROOT / "upgrade" / "recovera-image-boot").read_text()
        updater = UPDATER.read_text()
        self.assertIn("fallback_entry", boot)
        self.assertIn('run([BOOT_HELPER, "fallback"])', updater)

    def test_image_boot_supplies_root_and_wait_timeout(self):
        grub = (ROOT / "upgrade" / "07_recovera_images").read_text()
        local_top = (ROOT / "upgrade" / "initramfs-local-top-recovera").read_text()
        self.assertIn("root=LABEL=recovera-root", grub)
        self.assertIn('remaining=30', local_top)
        self.assertIn('[ -e "$host_device" ] || panic', local_top)
        boot = (ROOT / "upgrade" / "recovera-image-boot").read_text()
        self.assertIn("unset next_entry initrdfail prev_entry prev_saved_entry", boot)
        self.assertIn("boot_root_uuid", boot)
        self.assertIn('chroot "$boot_root"', boot)

    def test_updater_can_be_installed_without_rerunning_setup(self):
        setup = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn("install-updater)", setup)
        self.assertIn("p79_image_updater || exit 1", setup)

    # --- 0.6.36: OS-aware channels, manifest OS, PHP-FPM resolution ---

    def test_local_os_reads_os_release(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "os-release"
            release.write_text('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n')
            module = load_updater()
            with mock.patch.dict("os.environ", {"RECOVERA_OS_RELEASE": str(release)}):
                self.assertEqual(module.local_os(), self.NOBLE)
            with mock.patch.dict("os.environ", {"RECOVERA_OS_RELEASE": str(Path(directory) / "none")}):
                with self.assertRaises(module.UpgradeError):
                    module.local_os()

    def test_effective_channel_keeps_legacy_names_on_jammy(self):
        self.assertEqual(self.module.effective_channel("stable", self.JAMMY), "stable")
        self.assertEqual(self.module.effective_channel("stable", self.NOBLE), "noble-stable")
        self.assertEqual(self.module.effective_channel("noble-stable", self.NOBLE), "noble-stable")
        with self.assertRaises(self.module.UpgradeError):
            self.module.effective_channel("stable", {"id": "ubuntu", "version_id": "26.04", "codename": ""})

    def test_main_uses_the_os_channel_for_check_and_install_only(self):
        seen = {}

        def capture(config, _args):
            seen.update(config)
            return 0

        base = {"REPOSITORY": "falco1717/recovera", "CHANNEL": "stable",
                "CHANNEL_BRANCH": "main", "HOST_ROOT": "/host"}
        with mock.patch.object(self.module, "local_os", return_value=dict(self.NOBLE)), \
             mock.patch.object(self.module, "read_config", side_effect=lambda _path: dict(base)), \
             mock.patch.object(self.module, "command_check", side_effect=capture), \
             mock.patch.object(self.module.sys, "argv", ["recovera-upgrade", "check"]):
            self.assertEqual(self.module.main(), 0)
        self.assertEqual(seen["CHANNEL"], "noble-stable")
        self.assertEqual(seen["CHANNEL_REQUESTED"], "stable")
        seen.clear()
        with mock.patch.object(self.module, "local_os", side_effect=AssertionError("not needed")), \
             mock.patch.object(self.module, "read_config", side_effect=lambda _path: dict(base)), \
             mock.patch.object(self.module, "command_status", side_effect=capture), \
             mock.patch.object(self.module.sys, "argv", ["recovera-upgrade", "status"]):
            self.assertEqual(self.module.main(), 0)
        self.assertEqual(seen["CHANNEL"], "stable")

    def test_package_manifest_must_match_the_running_os(self):
        manifest = self.package_manifest()
        pointer = {"version": "0.7.1", "sequence": 8}
        with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
            # Legacy manifests without "os" were all built for 22.04.
            self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})
            manifest["os"] = {"id": "ubuntu", "version_id": "22.04"}
            self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})
            manifest["os"] = {"id": "ubuntu", "version_id": "24.04"}
            with self.assertRaisesRegex(self.module.UpgradeError, "24.04"):
                self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})
            manifest["os"] = "ubuntu-22.04"
            with self.assertRaises(self.module.UpgradeError):
                self.module.validate_manifest(manifest, pointer, {"CHANNEL": "stable"})
        noble = self.package_manifest()
        with self.assertRaisesRegex(self.module.UpgradeError, "does not declare"):
            self.module.check_manifest_os(noble, self.NOBLE)
        noble["os"] = {"id": "ubuntu", "version_id": "24.04"}
        self.module.check_manifest_os(noble, self.NOBLE)

    def test_required_services_resolve_the_installed_php_fpm(self):
        def units(listing):
            return mock.Mock(returncode=0, stdout=listing.encode(), stderr=b"")

        both = "php8.1-fpm.service enabled enabled\nphp8.3-fpm.service enabled enabled\n"
        noble = "php8.3-fpm.service enabled enabled\n"
        cases = [
            ("apache2.service php-fpm.service recovera-peer.service", both,
             ["apache2.service", "php8.3-fpm.service", "recovera-peer.service"]),
            ("apache2.service php8.1-fpm.service", both, ["apache2.service", "php8.1-fpm.service"]),
            ("apache2.service php8.1-fpm.service", noble, ["apache2.service", "php8.3-fpm.service"]),
            ("php-fpm.service php8.1-fpm.service", noble, ["php8.3-fpm.service"]),
            ("apache2.service php-fpm.service", "", ["apache2.service", "php-fpm.service"]),
        ]
        for configured, listing, expected in cases:
            with self.subTest(configured=configured, listing=listing), \
                 mock.patch.object(self.module, "run", return_value=units(listing)):
                self.assertEqual(self.module.required_services({"REQUIRED_SERVICES": configured}), expected)
        with mock.patch.object(self.module, "run") as run:
            self.assertEqual(self.module.required_services({"REQUIRED_SERVICES": "apache2.service"}),
                             ["apache2.service"])
            run.assert_not_called()
        conf = (ROOT / "upgrade" / "recovera-upgrade.conf").read_text()
        self.assertIn("REQUIRED_SERVICES=apache2.service php-fpm.service recovera-peer.service", conf)

    def test_control_package_supports_both_php_releases(self):
        control = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text()
        self.assertIn("php8.1-fpm | php8.3-fpm", control)
        self.assertNotIn("systemctl restart php8.1-fpm ", control)
        self.assertIn("'php*-fpm.service'", control)

    def test_package_release_declares_os_and_uses_one_sequence_counter(self):
        builder = (ROOT / "tools" / "build-package-release.sh").read_text()
        self.assertIn("'os': {'id': 'ubuntu', 'version_id': os_version}", builder)
        self.assertIn("--os-version", builder)
        self.assertIn('OS_PREFIX=noble-', builder)
        self.assertIn("CHANNELS_DIR=$ROOT/upgrade/channels", builder)
        self.assertIn("the highest sequence on any channel", builder)

    def test_schedule_skips_while_in_maintenance(self):
        loader = importlib.machinery.SourceFileLoader(
            "recovera_upgrade_schedule", str(ROOT / "upgrade" / "recovera-upgrade-schedule"))
        with tempfile.TemporaryDirectory() as directory:
            hold = Path(directory) / "maintenance"
            hold.write_text("{}")
            policy = Path(directory) / "policy.json"
            policy.write_text(json.dumps({"channel": "stable", "window": {"start": 0, "end": 0}}))
            environment = {"RECOVERA_MAINTENANCE": str(hold), "RECOVERA_UPGRADE_POLICY": str(policy)}
            with mock.patch.dict("os.environ", environment):
                spec = importlib.util.spec_from_loader(loader.name, loader)
                schedule = importlib.util.module_from_spec(spec)
                loader.exec_module(schedule)
                with mock.patch.object(schedule.subprocess, "run") as run, \
                     mock.patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(schedule.main(), 0)
                run.assert_not_called()

    def test_new_pools_pin_the_openzfs_2_2_feature_set_when_available(self):
        for script in ("setup/setup.sh", "tools/prepare-ova.sh"):
            text = (ROOT / script).read_text()
            self.assertIn("compatibility.d/openzfs-2.2-linux ] && compat=(-o compatibility=openzfs-2.2-linux)", text)
            self.assertIn('zpool create -o ashift=12 "${compat[@]}"', text)

    # --- 0.6.37: image-layout conversion and OS transition images ---

    UUID = "a37c1887-f6dd-425b-890c-d2fd05249a97"

    def layout_fixture(self, directory):
        root = Path(directory)
        host = root / "host"
        (host / "recovera").mkdir(parents=True)
        (host / "recovera" / "state.json").write_text('{"installed_sequence": 36}')
        share = root / "share"
        share.mkdir()
        (share / "07_recovera_images").write_text("#!/bin/sh\n")
        (share / "99_recovera_images.cfg").write_text("GRUB_DEFAULT=saved\n")
        fstab = root / "fstab"
        fstab.write_text("LABEL=cloudimg-rootfs\t/\t ext4\tdiscard,errors=remount-ro\t0 1\n"
                         "LABEL=UEFI\t/boot/efi\tvfat\tumask=0077\t0 1\n")
        grub = root / "grub.cfg"
        grub.write_text(f"menuentry 'Ubuntu' $menuentry_id_option 'gnulinux-simple-{self.UUID}' {{\n}}\n")
        calls = []

        def fake_run(args, **_kwargs):
            args = [str(value) for value in args]
            calls.append(args)
            stdout = f"{self.UUID} /dev/sda1 ext4\n".encode() if args[0] == "findmnt" else b""
            return mock.Mock(returncode=0, stdout=stdout, stderr=b"")

        patches = [
            mock.patch.object(self.module, "SHARE_DIR", share),
            mock.patch.object(self.module, "FSTAB", fstab),
            mock.patch.object(self.module, "GRUB_CFG", grub),
            mock.patch.object(self.module, "GRUB_SCRIPT", root / "grub.d" / "07_recovera_images"),
            mock.patch.object(self.module, "GRUB_DEFAULTS", root / "default" / "99_recovera_images.cfg"),
            mock.patch.object(self.module, "SHARED_STATE", root / "recovera"),
            mock.patch.object(self.module, "HOST_MOUNTPOINT", str(host)),
            mock.patch.object(self.module, "PENDING_MARKER", host / "recovera" / "pending"),
            mock.patch.object(self.module, "UpgradeLock", lambda: contextlib.nullcontext()),
            mock.patch.object(self.module, "require_root", lambda: None),
            mock.patch.object(self.module, "run", side_effect=fake_run),
            mock.patch.dict("os.environ", {"RECOVERA_IMAGE_LAYOUT": str(root / "image-layout.json")}),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ]
        return root, host, fstab, calls, patches, {"HOST_ROOT": str(host)}

    def test_prepare_image_layout_keeps_the_conventional_boot_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root, host, fstab, calls, patches, config = self.layout_fixture(directory)
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                dry = argparse.Namespace(dry_run=True)
                self.assertEqual(self.module.command_prepare_image_layout(config, dry), 0)
                self.assertFalse((root / "image-layout.json").exists())
                self.assertNotIn("bind", fstab.read_text())

                self.assertEqual(self.module.command_prepare_image_layout(
                    config, argparse.Namespace(dry_run=False)), 0)
                layout = json.loads((root / "image-layout.json").read_text())
                entry = f"gnulinux-simple-{self.UUID}"
                self.assertEqual(layout["mode"], "loop-image-v1")
                self.assertEqual(layout["boot_root_uuid"], self.UUID)
                self.assertEqual(layout["fallback_entry"], entry)
                # Updater state follows the bind mount to /recovera.
                self.assertEqual(json.loads((root / "recovera" / "state.json").read_text()),
                                 {"installed_sequence": 36})
                self.assertIn(f"/ {host} none bind,", fstab.read_text())
                self.assertTrue((root / "grub.d" / "07_recovera_images").is_file())
                self.assertTrue((root / "default" / "99_recovera_images.cfg").is_file())
                order = [call[0] if call[0] != "mount" else "mount" for call in calls]
                self.assertIn(["mount", "--bind", "/", str(host)], calls)
                self.assertIn(["grub-set-default", entry], calls)
                self.assertLess(order.index("mount"), order.index("update-grub"))
                self.assertLess(order.index("update-grub"), order.index("grub-set-default"))

                calls.clear()
                self.module.command_prepare_image_layout(config, argparse.Namespace(dry_run=False))
                self.assertEqual(calls, [], "a second run must change nothing")

                (host / "recovera" / "images").mkdir(parents=True, exist_ok=True)
                (host / "recovera" / "images" / "0.7.0.img").write_text("x")
                with self.assertRaisesRegex(self.module.UpgradeError, "--force"):
                    self.module.command_revert_image_layout(config, argparse.Namespace(force=False))
                self.module.command_revert_image_layout(config, argparse.Namespace(force=True))
                self.assertFalse((root / "image-layout.json").exists())
                self.assertFalse((root / "grub.d" / "07_recovera_images").exists())
                self.assertNotIn("bind", fstab.read_text())
                self.assertIn("LABEL=UEFI", fstab.read_text())
                self.assertIn(["update-grub"], calls)

    def test_prepare_image_layout_refuses_unsafe_starting_points(self):
        with tempfile.TemporaryDirectory() as directory:
            root, host, fstab, calls, patches, config = self.layout_fixture(directory)
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                arguments = argparse.Namespace(dry_run=False)
                (host / "recovera" / "pending").write_text("")
                with self.assertRaisesRegex(self.module.UpgradeError, "reboot validation"):
                    self.module.command_prepare_image_layout(config, arguments)
                (host / "recovera" / "pending").unlink()
                (root / "grub.cfg").write_text("menuentry 'Other' {\n}\n")
                with self.assertRaisesRegex(self.module.UpgradeError, "no gnulinux-simple"):
                    self.module.command_prepare_image_layout(config, arguments)
                with mock.patch.object(self.module, "run", return_value=mock.Mock(
                        returncode=0, stdout=f"{self.UUID} /dev/loop0 ext4".encode())):
                    with self.assertRaisesRegex(self.module.UpgradeError, "already running"):
                        self.module.command_prepare_image_layout(config, arguments)
                self.assertFalse((root / "image-layout.json").exists())

    def test_failed_first_image_falls_back_to_the_conventional_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            images = root / "host" / "recovera" / "images"
            images.mkdir(parents=True)
            environment = {"RECOVERA_UPGRADE_STATE": str(state),
                           "RECOVERA_RELEASE_FILE": str(root / "none")}
            config = {"HOST_ROOT": str(root / "host")}
            arguments = argparse.Namespace(reason="validation failed", reboot=False)
            cases = [
                ({"type": "package", "version": "0.6.37", "sequence": 36}, "fallback"),
                ({"version": "0.7.0", "sequence": 40}, "fallback"),  # image file is gone
            ]
            (images / "0.7.1.img").write_text("x")
            cases.append(({"version": "0.7.1", "sequence": 41}, "rollback"))
            for previous, expected in cases:
                state.write_text(json.dumps({"pending": {"version": "0.8.0"}, "previous": previous}))
                with self.subTest(previous=previous), \
                     mock.patch.dict("os.environ", environment), \
                     mock.patch.object(self.module, "UpgradeLock", lambda: contextlib.nullcontext()), \
                     mock.patch.object(self.module, "require_root", lambda: None), \
                     mock.patch.object(self.module, "PENDING_MARKER", root / "pending"), \
                     mock.patch.object(self.module, "run") as run:
                    self.module.command_validation_failed(config, arguments)
                    self.assertEqual(run.call_args_list[0].args[0][1], expected)

    def image_manifest(self, **extra):
        manifest = self.manifest()
        manifest.update(extra)
        return manifest

    def test_image_manifest_transition_fields_are_validated(self):
        pointer = {"version": "0.7.0", "sequence": 7}
        good = {"os": {"id": "ubuntu", "version_id": "24.04"},
                "from": {"os_version_ids": ["22.04"], "minimum_version": "0.6.37"}}
        with mock.patch.object(self.module.platform, "machine", return_value="x86_64"):
            self.module.validate_manifest(self.image_manifest(**good), pointer, {"CHANNEL": "stable"})
            for bad in ({"from": {"os_version_ids": []}},
                        {"from": {"os_version_ids": ["22.04"], "extra": 1}},
                        {"from": {"os_version_ids": ["22.04;rm"]}},
                        {"os": {"id": "ubuntu"}}):
                with self.subTest(bad=bad), self.assertRaises(self.module.UpgradeError):
                    self.module.validate_manifest(self.image_manifest(**bad), pointer, {"CHANNEL": "stable"})

    def test_transition_preflight_requires_a_drained_healthy_appliance(self):
        manifest = self.image_manifest(
            os={"id": "ubuntu", "version_id": "24.04"},
            **{"from": {"os_version_ids": ["22.04"], "minimum_version": "0.6.37"}})
        manifest["image"]["size"] = 10
        manifest["image"]["uncompressed_size"] = 20
        ready = argparse.Namespace(allow_busy=False)

        def preflight(**overrides):
            values = {"installed": "0.6.37-1", "at_least": True, "health": "ONLINE",
                      "drained": (True, "idle"), "restores": [], "free": 10 * 2**30,
                      "os": dict(self.JAMMY), "args": ready}
            values.update(overrides)
            with mock.patch.object(self.module, "local_os", return_value=values["os"]), \
                 mock.patch.object(self.module, "installed_version", return_value=values["installed"]), \
                 mock.patch.object(self.module, "version_at_least", return_value=values["at_least"]), \
                 mock.patch.object(self.module, "pool_health", return_value=values["health"]), \
                 mock.patch.object(self.module, "replication_drained", return_value=values["drained"]), \
                 mock.patch.object(self.module, "active_restores", return_value=values["restores"]), \
                 mock.patch.object(self.module.shutil, "disk_usage",
                                   return_value=mock.Mock(free=values["free"])):
                self.module.transition_preflight(manifest, Path("."), values["args"])

        preflight()
        with self.assertRaisesRegex(self.module.UpgradeError, "starts from Ubuntu 22.04"):
            preflight(os=dict(self.NOBLE))
        with self.assertRaisesRegex(self.module.UpgradeError, "0.6.37 or newer"):
            preflight(at_least=False)
        with self.assertRaisesRegex(self.module.UpgradeError, "DEGRADED"):
            preflight(health="DEGRADED")
        with self.assertRaisesRegex(self.module.UpgradeError, "not paused"):
            preflight(drained=(False, "replication is not paused"))
        with self.assertRaisesRegex(self.module.UpgradeError, "restores are active"):
            preflight(restores=["virtual machine test"])
        with self.assertRaisesRegex(self.module.UpgradeError, "MiB free"):
            preflight(free=100)
        preflight(drained=(False, "busy"), restores=["vm"], args=argparse.Namespace(allow_busy=True))
        # An image for another OS release without "from" is not a transition.
        plain = self.image_manifest(os={"id": "ubuntu", "version_id": "24.04"})
        with mock.patch.object(self.module, "local_os", return_value=dict(self.JAMMY)):
            with self.assertRaisesRegex(self.module.UpgradeError, "needs a transition release"):
                self.module.transition_preflight(plain, Path("."), ready)

    def test_replication_drained_reads_the_peer_maintenance_status(self):
        def status(value):
            return mock.Mock(returncode=0, stdout=json.dumps(value).encode())

        with tempfile.TemporaryDirectory() as directory:
            peer = Path(directory) / "recovera-peer"
            with mock.patch.object(self.module, "PEER_COMMAND", peer):
                self.assertTrue(self.module.replication_drained()[0])
                peer.write_text("")
                cases = [({"maintenance": None, "busy": []}, False),
                         ({"maintenance": {"reason": "x"}, "busy": ["receiving a"]}, False),
                         ({"maintenance": {"reason": "x"}, "busy": []}, True)]
                for value, expected in cases:
                    with mock.patch.object(self.module, "run", return_value=status(value)):
                        self.assertEqual(self.module.replication_drained()[0], expected)

    def test_channel_override_is_explicit_and_never_cached(self):
        seen = {}
        base = {"REPOSITORY": "falco1717/recovera", "CHANNEL": "stable",
                "CHANNEL_BRANCH": "main", "HOST_ROOT": "/host"}

        def capture(config, _args):
            seen.update(config)
            return 0

        def invoke(*argv):
            with mock.patch.object(self.module, "read_config", side_effect=lambda _path: dict(base)), \
                 mock.patch.object(self.module, "command_check", side_effect=capture), \
                 mock.patch.object(self.module.sys, "argv", ["recovera-upgrade", *argv]), \
                 mock.patch("sys.stderr", new_callable=io.StringIO):
                return self.module.main()

        self.assertEqual(invoke("check", "--channel", "jammy-noble-transition"), 0)
        self.assertEqual(seen["CHANNEL"], "jammy-noble-transition")
        self.assertEqual(invoke("check", "--channel", "../stable"), 1)
        self.assertEqual(invoke("check", "--channel", "jammy-noble-transition", "--cache"), 1)
        schedule = (ROOT / "upgrade" / "recovera-upgrade-schedule").read_text()
        self.assertNotIn("--channel", schedule)

    def test_configuration_migration_carries_appliance_state_and_fixes_fstab(self):
        migration = (ROOT / "upgrade" / "recovera-migrate-config").read_text()
        for value in ("/etc/zfs/zpool.cache", "/var/lib/datto", "/var/lib/recovera",
                      "/etc/firewalld/zones", "/var/lib/samba/private",
                      # NM derives br0's stable cloned MAC from secret_key + machine-id.
                      "/var/lib/NetworkManager/secret_key", "/etc/localtime", "/etc/timezone",
                      "/etc/systemd/timesyncd.conf.d"):
            self.assertIn(value, migration)
        self.assertIn('[ -e /etc/hostid ] || rm -f "$target/etc/hostid"', migration)
        start = migration.index("<<'PY'\n", migration.index('"$target/etc/fstab"')) + len("<<'PY'\n")
        snippet = migration[start:migration.index("\nPY", start)]
        with tempfile.TemporaryDirectory() as directory:
            fstab = Path(directory) / "fstab"
            fstab.write_text(
                "# comment\n"
                "LABEL=cloudimg-rootfs\t/\t ext4\tdiscard,errors=remount-ro\t0 1\n"
                "LABEL=UEFI\t/boot/efi\tvfat\tumask=0077\t0 1\n"
                "# Recovera image host (recovera-upgrade prepare-image-layout)\n"
                "/ /host none bind,x-systemd.requires-mounts-for=/ 0 0\n")
            script = Path(directory) / "fix.py"
            script.write_text(snippet)
            subprocess.run([sys.executable, str(script), str(fstab)], check=True)
            lines = fstab.read_text().splitlines()
        self.assertIn("LABEL=recovera-root\t/\text4\tdefaults,errors=remount-ro\t0 0", lines)
        self.assertIn("LABEL=UEFI\t/boot/efi\tvfat\tumask=0077\t0 1", lines)
        self.assertFalse(any("cloudimg-rootfs" in line or "/host" in line for line in lines))
        self.assertIn("# comment", lines)

    def test_image_builder_marks_transitions_and_drops_host_identity(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        for value in ("--from-os", "--minimum-version", "--os-version", "*-transition",
                      "manifest['from']", '"$mountpoint/etc/hostid"',
                      '"$mountpoint/etc/zfs/zpool.cache"', "the highest sequence on any channel"):
            self.assertIn(value, builder)
        control = (ROOT / "tools" / "build-recovera-appliance-deb.sh").read_text()
        self.assertIn('"$stage/usr/local/share/recovera-upgrade/07_recovera_images"', control)
        self.assertIn('"$stage/usr/local/share/recovera-upgrade/99_recovera_images.cfg"', control)

    # --- 0.6.39: gateway by default, update source, approved OS upgrade ---

    def gateway_token(self, sub="Backup-Bitches", channels=("stable",), exp=None):
        payload = {"channels": sorted(channels), "exp": exp or 4102444800, "iat": 1700000000,
                   "jti": "x" * 32, "sub": sub, "v": 1}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"rgt1.{encoded}.c2lnbmF0dXJl"

    def test_gateways_are_used_only_with_an_access_token(self):
        config = {"UPDATE_ORIGINS": "https://recoveragw.example", "GATEWAY_TOKEN_FILE": "/nonexistent"}
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("RECOVERA_GATEWAY_TOKEN", None)
            self.assertEqual(self.module.active_gateway_origins(config), [])
            source = self.module.update_source(config)
            self.assertEqual(source["mode"], "github")
            self.assertIn("No gateway access token", source["detail"])
        with mock.patch.dict("os.environ", {"RECOVERA_GATEWAY_TOKEN": self.gateway_token()}):
            self.assertEqual(self.module.active_gateway_origins(config), ["https://recoveragw.example"])
            source = self.module.update_source(config)
            self.assertEqual(source["mode"], "gateway")
            self.assertEqual(source["token"]["subject"], "Backup-Bitches")
            self.assertFalse(source["token"]["expired"])
        conf = (ROOT / "upgrade" / "recovera-upgrade.conf").read_text()
        self.assertIn("UPDATE_ORIGINS=https://recoveragw.rjproductionsut.com,https://recoveragwb.rjproductionsut.com", conf)
        self.assertIn("TRANSITION_CHANNEL=jammy-noble-transition", conf)

    def test_gateway_token_is_validated_before_installing(self):
        for bad in ("", "not-a-token", "rgt1.@@@.sig", "rgt1." + base64.urlsafe_b64encode(b"[]").decode().rstrip("=") + ".s"):
            with self.subTest(bad=bad), self.assertRaises(self.module.UpgradeError):
                self.module.decode_gateway_token(bad)
        self.assertEqual(self.module.decode_gateway_token(self.gateway_token(sub="DC"))["sub"], "DC")

    def test_set_gateway_token_installs_and_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            conf = root / "upgrade.conf"
            conf.write_text("REPOSITORY=falco1717/recovera\nCHANNEL=stable\nCHANNEL_BRANCH=main\n"
                            "HOST_ROOT=/host\nUPDATE_ORIGINS=\n")
            token_path = root / "gateway-token"
            config = self.module.read_config(conf)
            config["GATEWAY_TOKEN_FILE"] = str(token_path)
            arguments = argparse.Namespace(config=conf)
            good = self.gateway_token(channels=("stable", "jammy-noble-transition"))

            def read_token(value):
                # Windows cannot express mode 0600; Linux CI covers the permission check.
                path = Path(value.get("GATEWAY_TOKEN_FILE", "/nonexistent"))
                return path.read_text().strip() if path.is_file() else None

            with mock.patch.object(self.module, "require_root", lambda: None), \
                 mock.patch.object(self.module, "gateway_token", side_effect=read_token), \
                 mock.patch.object(self.module, "UpgradeLock", lambda: contextlib.nullcontext()), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                with mock.patch("sys.stdin", io.StringIO(self.gateway_token(channels=("noble-stable",)))):
                    with self.assertRaisesRegex(self.module.UpgradeError, "does not include"):
                        self.module.command_set_gateway_token(config, arguments)
                with mock.patch("sys.stdin", io.StringIO(self.gateway_token(exp=1000))):
                    with self.assertRaisesRegex(self.module.UpgradeError, "expired"):
                        self.module.command_set_gateway_token(config, arguments)
                with mock.patch("sys.stdin", io.StringIO(good)), \
                     mock.patch.object(self.module, "fetch_channel",
                                       side_effect=self.module.UpgradeError("401 from gateway")):
                    with self.assertRaisesRegex(self.module.UpgradeError, "401"):
                        self.module.command_set_gateway_token(config, arguments)
                self.assertFalse(token_path.exists())
                self.assertIn("UPDATE_ORIGINS=\n", conf.read_text())
                with mock.patch("sys.stdin", io.StringIO(good)), \
                     mock.patch.object(self.module, "fetch_channel", return_value={}) as fetch:
                    self.assertEqual(self.module.command_set_gateway_token(config, arguments), 0)
                fetched = fetch.call_args.args[0]
                self.assertEqual(fetched["UPDATE_ORIGINS"], "https://recoveragw.rjproductionsut.com,https://recoveragwb.rjproductionsut.com")
            self.assertEqual(token_path.read_text().strip(), good)
            self.assertIn("GATEWAY_TOKEN_FILE=" + str(token_path), conf.read_text())

    def transition_manifest(self):
        manifest = self.image_manifest(os={"id": "ubuntu", "version_id": "24.04"},
                                       **{"from": {"os_version_ids": ["22.04"], "minimum_version": "0.6.37"}})
        manifest["channel"] = "jammy-noble-transition"
        return manifest

    def transition_fixture(self, directory, manifest=None, state=None):
        root = Path(directory)
        state_file = root / "state.json"
        state_file.write_text(json.dumps(state or {}))
        manifest = manifest or self.transition_manifest()
        release = ({"release_tag": "image-v0.7.0"}, {}, manifest, root / "m.json", root / "m.sig")
        patches = [
            mock.patch.dict("os.environ", {"RECOVERA_UPGRADE_STATE": str(state_file),
                                           "RECOVERA_RELEASE_FILE": str(root / "none"),
                                           "RECOVERA_IMAGE_LAYOUT": str(root / "layout.json")}),
            mock.patch.object(self.module, "get_release", return_value=release),
            mock.patch.object(self.module, "transition_readiness", return_value=[]),
            mock.patch.object(self.module, "require_root", lambda: None),
            mock.patch.object(self.module, "UpgradeLock", lambda: contextlib.nullcontext()),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ]
        config = {"HOST_ROOT": str(root), "TRANSACTION_ROOT": str(root / "tx"), "CHANNEL": "stable"}
        return root, state_file, config, release, patches

    def test_transition_is_offered_only_from_its_starting_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root, state_file, config, _, patches = self.transition_fixture(directory)
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                result, _ = self.module.transition_status(config, argparse.Namespace(signers=None), root)
                self.assertTrue(result["available"])
                self.assertEqual(result["version"], "0.7.0")
                with mock.patch.object(self.module, "local_os", return_value=dict(self.NOBLE)):
                    result, _ = self.module.transition_status(config, argparse.Namespace(signers=None), root)
                self.assertFalse(result["available"])
                self.assertIn("already runs Ubuntu 24.04", result["detail"])
                with mock.patch.object(self.module, "get_release",
                                       side_effect=self.module.NoReleaseError("none")):
                    result, _ = self.module.transition_status(config, argparse.Namespace(signers=None), root)
                self.assertFalse(result["available"])
                self.assertIn("No operating-system upgrade", result["detail"])

    def test_transition_needs_approval_and_runs_drain_layout_then_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root, state_file, config, release, patches = self.transition_fixture(directory)
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                install = stack.enter_context(mock.patch.object(self.module, "command_install_image"))
                prepare = stack.enter_context(mock.patch.object(self.module, "command_prepare_image_layout"))
                stack.enter_context(mock.patch.object(self.module, "transition_preflight"))
                maintenance = stack.enter_context(mock.patch.object(self.module, "peer_maintenance", return_value=0))
                arguments = argparse.Namespace(if_approved=True, drain_wait=60, reboot=True, signers=None)
                # Nothing approved: the update window does nothing.
                self.assertEqual(self.module.command_install_transition(config, arguments), 0)
                install.assert_not_called()
                with self.assertRaisesRegex(self.module.UpgradeError, "0.7.0, not 0.6.9"):
                    self.module.command_approve_transition(config, argparse.Namespace(version="0.6.9", start="window", signers=None))
                self.module.command_approve_transition(config, argparse.Namespace(version="0.7.0", start="window", signers=None))
                self.assertEqual(json.loads(state_file.read_text())["transition_approval"]["version"], "0.7.0")
                self.assertEqual(self.module.command_install_transition(config, arguments), 0)
                prepare.assert_called_once()
                maintenance.assert_any_call("on", "--reason", "Ubuntu operating-system upgrade", "--wait", "60")
                install.assert_called_once()
                self.assertEqual(install.call_args.args[0]["CHANNEL"], "jammy-noble-transition")
                self.assertTrue(install.call_args.args[1].reboot)

    def test_transition_defers_when_replication_does_not_drain(self):
        approval = {"transition_approval": {"version": "0.7.0", "sequence": 7}}
        with tempfile.TemporaryDirectory() as directory:
            root, state_file, config, release, patches = self.transition_fixture(directory, state=approval)
            (root / "layout.json").write_text(json.dumps({"mode": "loop-image-v1"}))
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                install = stack.enter_context(mock.patch.object(self.module, "command_install_image"))
                stack.enter_context(mock.patch.object(self.module, "transition_preflight"))
                maintenance = stack.enter_context(mock.patch.object(self.module, "peer_maintenance",
                                                                    side_effect=[4, 0]))
                arguments = argparse.Namespace(if_approved=True, drain_wait=60, reboot=True, signers=None)
                self.assertEqual(self.module.command_install_transition(config, arguments), 0)
                install.assert_not_called()
                self.assertEqual(maintenance.call_args_list[-1].args, ("off",))
                state = json.loads(state_file.read_text())
                self.assertIn("deferred", state["transition_last_attempt"]["result"])
                self.assertEqual(state["transition_approval"]["version"], "0.7.0", "stays approved for a retry")

    def test_transition_approval_is_dropped_when_the_published_upgrade_changes(self):
        approval = {"transition_approval": {"version": "0.6.99", "sequence": 6}}
        with tempfile.TemporaryDirectory() as directory:
            root, state_file, config, release, patches = self.transition_fixture(directory, state=approval)
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                install = stack.enter_context(mock.patch.object(self.module, "command_install_image"))
                arguments = argparse.Namespace(if_approved=True, drain_wait=60, reboot=True, signers=None)
                self.assertEqual(self.module.command_install_transition(config, arguments), 0)
                install.assert_not_called()
                state = json.loads(state_file.read_text())
                self.assertIsNone(state["transition_approval"])
                self.assertIn("approve it again", state["transition_last_attempt"]["result"])

    def test_failed_transition_clears_the_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            state.write_text(json.dumps({"pending": {"version": "0.7.0", "transition": True},
                                         "previous": {"type": "package", "version": "0.6.39"},
                                         "transition_approval": {"version": "0.7.0"}}))
            with mock.patch.dict("os.environ", {"RECOVERA_UPGRADE_STATE": str(state),
                                                "RECOVERA_RELEASE_FILE": str(root / "none")}), \
                 mock.patch.object(self.module, "UpgradeLock", lambda: contextlib.nullcontext()), \
                 mock.patch.object(self.module, "require_root", lambda: None), \
                 mock.patch.object(self.module, "PENDING_MARKER", root / "pending"), \
                 mock.patch.object(self.module, "run") as run:
                self.module.command_validation_failed({"HOST_ROOT": str(root)},
                                                      argparse.Namespace(reason="apache down", reboot=False))
            value = json.loads(state.read_text())
            self.assertIsNone(value["transition_approval"])
            self.assertIn("returned to its previous system", value["transition_last_attempt"]["result"])
            self.assertEqual(run.call_args_list[0].args[0][1], "fallback")

    def test_schedule_runs_an_approved_transition_when_no_package_update_is_due(self):
        schedule = (ROOT / "upgrade" / "recovera-upgrade-schedule").read_text()
        self.assertIn('UPDATER, "install-transition", "--if-approved"', schedule)
        self.assertNotIn('"approve-transition"', schedule)

    def test_image_builder_strips_builder_network_and_login_identity(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        for value in ('"$mountpoint/etc/netplan"/90-NM-*.yaml', '"$mountpoint/root/.ssh/authorized_keys"',
                      '"$mountpoint/var/lib/NetworkManager/secret_key"', '"$mountpoint/etc/recovera/gateway-token"',
                      'cloud-init.disabled', 'passwd -l ubuntu'):
            self.assertIn(value, builder)
        migration = (ROOT / "upgrade" / "recovera-migrate-config").read_text()
        self.assertIn("for path in /etc/netplan/90-NM-*.yaml; do copy_path", migration)
        arguments = self.module.parser().parse_args(
            ["install-transition", "--channel-file", "pointer.json", "--source-dir", "assets"])
        self.assertEqual(self.module.release_arguments(argparse.Namespace(
            signers=None, channel_file=arguments.channel_file, source_dir=arguments.source_dir)).source_dir, Path("assets"))

    # --- 0.6.44: findings from the first end-to-end transition test ---

    def test_rollback_from_the_first_image_boots_the_conventional_root(self):
        # After a transition the state still held the 22.04 package transaction;
        # rollback must boot 22.04, not reinstall packages that are not in the image.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            state.write_text(json.dumps({
                "installed": {"schema": 1, "sequence": 43, "version": "0.6.42-noble.test2"},
                "installed_sequence": 43,
                "previous": {"type": "package", "version": "0.6.43", "sequence": 42},
                "transition_last_attempt": {"version": "0.6.42-noble.test2", "result": "completed"},
            }))
            layout = root / "layout.json"
            layout.write_text(json.dumps({"mode": "loop-image-v1", "fallback_entry": "gnulinux-simple-x"}))
            release = root / "release.json"
            release.write_text(json.dumps({"schema": 1, "sequence": 43, "version": "0.6.42-noble.test2"}))
            boot_helper = root / "boot-helper"
            boot_helper.write_text("")
            environment = {"RECOVERA_UPGRADE_STATE": str(state), "RECOVERA_RELEASE_FILE": str(release),
                           "RECOVERA_IMAGE_LAYOUT": str(layout)}
            with mock.patch.dict("os.environ", environment), \
                 mock.patch.object(self.module, "UpgradeLock", lambda: contextlib.nullcontext()), \
                 mock.patch.object(self.module, "require_root", lambda: None), \
                 mock.patch.object(self.module, "BOOT_HELPER", boot_helper), \
                 mock.patch.object(self.module, "PENDING_MARKER", root / "pending"), \
                 mock.patch.object(self.module, "rollback_package_transaction") as package_rollback, \
                 mock.patch.object(self.module, "run") as run, \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                self.module.command_rollback({"HOST_ROOT": str(root)}, argparse.Namespace(reboot=False))
            package_rollback.assert_not_called()
            self.assertEqual(run.call_args_list[0].args[0], [boot_helper, "fallback"])
            value = json.loads(state.read_text())
            self.assertEqual(value["installed"]["version"], "0.6.43")
            self.assertEqual(value["installed_sequence"], 42)
            self.assertIn("rolled back", value["transition_last_attempt"]["result"])
        source = UPDATER.read_text()
        stage = source[source.index("def command_install_image"):source.index("def dpkg_field")]
        self.assertIn('"last_transaction": None', stage)

    def test_image_keeps_its_own_software_version_markers(self):
        migration = (ROOT / "upgrade" / "recovera-migrate-config").read_text()
        self.assertIn("for name in os2Version sirisUIVersion syncVersion; do", migration)
        self.assertLess(migration.index('cp -a "$target/datto/config/$name" "$versions/$name"'),
                        migration.index("  /datto/config \\"))
        self.assertLess(migration.index("  /datto/config \\"),
                        migration.index('cp -a "$versions/$name" "$target/datto/config/$name"'))

    def test_image_builder_copies_boot_and_drops_installer_payload(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        self.assertIn('if mountpoint -q "$ROOT/boot"; then', builder)
        self.assertIn("--exclude='/home/*'", builder)
        self.assertIn("--exclude='/var/log/journal/*'", builder)
        self.assertIn("! -name 'recovera-appliance_*.deb' -delete", builder)


if __name__ == "__main__":
    unittest.main()
