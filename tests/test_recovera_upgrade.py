import importlib.machinery
import importlib.util
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

    def test_channel_is_dormant_until_first_image(self):
        channel = json.loads((ROOT / "upgrade" / "channels" / "stable.json").read_text())
        self.assertIsNone(channel["release_tag"])
        self.assertEqual(channel["sequence"], 0)

    def test_empty_channel_is_a_successful_no_update_check(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "upgrade.conf"
            config.write_text(
                "REPOSITORY=falco1717/recovera\nCHANNEL=stable\n"
                "CHANNEL_BRANCH=main\nHOST_ROOT=/host\n"
            )
            arguments = self.module.parser().parse_args([
                "--config", str(config), "check", "--channel-file",
                str(ROOT / "upgrade" / "channels" / "stable.json"),
            ])
            self.assertEqual(self.module.command_check(self.module.read_config(config), arguments), 0)

    def test_private_signing_key_is_not_in_repository(self):
        names = [path.name for path in ROOT.rglob("*") if path.is_file()]
        self.assertNotIn("recovera-upgrade-signing-key", names)

    def test_setup_installs_but_does_not_enable_image_layout(self):
        setup = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn('phase p79 "signed image upgrade client"', setup)
        self.assertIn("p79_image_updater()", setup)
        self.assertNotIn("image-layout.json <<", setup)

    def test_release_uses_signature_namespace_and_split_assets(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        self.assertIn("-n recovera-upgrade", builder)
        self.assertIn('split -b "$PART_SIZE"', builder)
        self.assertIn("uncompressed_sha256", builder)

    def test_configuration_migration_is_allowlisted(self):
        migration = (ROOT / "upgrade" / "recovera-migrate-config").read_text()
        self.assertIn("/datto/config", migration)
        self.assertIn("/etc/recovera-peer", migration)
        self.assertIn("/etc/NetworkManager/system-connections", migration)
        self.assertIn("/etc/fstab", migration)
        self.assertNotIn("copy_path /etc\n", migration)
        self.assertNotIn("/home/agents", migration)

    def test_builder_removes_appliance_identity(self):
        builder = (ROOT / "tools" / "build-upgrade-image.sh").read_text()
        for value in (
            "github-token", "backup-admin.json", "ssh_host_*", "deviceID",
            "/etc/machine-id", "/etc/recovera-peer", "/var/lib/recovera-peer",
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

    def test_updater_can_be_installed_without_rerunning_setup(self):
        setup = (ROOT / "setup" / "setup.sh").read_text()
        self.assertIn("install-updater)", setup)
        self.assertIn("p79_image_updater", setup)


if __name__ == "__main__":
    unittest.main()
