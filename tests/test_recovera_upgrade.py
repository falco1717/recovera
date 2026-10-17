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
    @classmethod
    def setUpClass(cls):
        cls.module = load_updater()

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
        with mock.patch.object(
            self.module, "request",
            side_effect=[self.module.UpgradeError("west unavailable"),
                         io.BytesIO(json.dumps(pointer).encode())],
        ) as requester:
            self.assertEqual(self.module.fetch_channel(config), pointer)
        self.assertEqual(requester.call_count, 2)
        self.assertEqual(config["_ACTIVE_GATEWAY_ORIGIN"], "https://east.example")
        assets = self.module.release_assets(pointer, config)
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
        self.assertEqual(channel["release_tag"], "package-v0.6.13")
        self.assertEqual(channel["version"], "0.6.13")
        self.assertEqual(channel["sequence"], 13)

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
        timer = (ROOT / "upgrade" / "recovera-upgrade-check.timer").read_text()
        self.assertIn("OnCalendar=hourly", timer)

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


if __name__ == "__main__":
    unittest.main()
