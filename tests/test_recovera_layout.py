import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATOR = ROOT / "setup" / "migrate-layout.sh"


class RecoveraLayoutTests(unittest.TestCase):
    def test_new_installation_identity_is_recovera(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        setup = (ROOT / "setup/setup.sh").read_text(encoding="utf-8")
        release = (ROOT / "setup/release.env").read_text(encoding="utf-8")
        bundle = (ROOT / "tools/make-bundle.sh").read_text(encoding="utf-8")
        self.assertIn("/opt/recovera", setup)
        self.assertIn("/var/lib/recovera-setup", setup)
        self.assertIn("/var/log/recovera-setup.log", setup)
        self.assertIn("UNIT=recovera-setup", setup)
        self.assertIn('BUNDLE_TAG="installer-payload-v2"', release)
        self.assertIn('BUNDLE_ASSET="recovera-setup.tar"', release)
        self.assertIn("recovera-setup.tar", installer)
        self.assertIn("recovera-setup.tar", bundle)
        for content in (installer, setup, release, bundle):
            self.assertNotIn("spf-datto", content)

    def test_update_package_runs_layout_migration(self):
        builder = (ROOT / "tools/build-recovera-appliance-deb.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/local/lib/recovera/migrate-layout", builder)
        self.assertIn("/usr/share/recovera/setup/setup.sh", builder)
        self.assertIn("/opt/recovera/setup.sh", builder)
        self.assertIn("recovera-sshd-service.conf", builder)
        self.assertIn("recovera-firewall-service.conf", builder)

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "requires a Linux shell")
    def test_layout_migration_preserves_state_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_install = root / "opt/spf-datto"
            old_state = root / "var/lib/spf-datto-setup"
            old_units = root / "etc/systemd/system"
            old_apt = root / "etc/apt/sources.list.d"
            old_install.mkdir(parents=True)
            old_state.mkdir(parents=True)
            old_units.mkdir(parents=True)
            old_apt.mkdir(parents=True)
            (old_install / "setup.conf").write_text("LOGIN_USER=test\n", encoding="utf-8")
            (old_state / "p10.done").write_text("done\n", encoding="utf-8")
            (old_apt / "spf-datto-local.list").write_text(
                "deb [trusted=yes] file:/opt/spf-datto/debs ./\n", encoding="utf-8"
            )
            (old_units / "spf-datto-verify.service").write_text(
                "[Service]\nExecStart=/opt/spf-datto/setup.sh verify --after-boot\n", encoding="utf-8"
            )
            (old_units / "spf-datto-verify.timer").write_text(
                "[Timer]\nOnBootSec=3min\n", encoding="utf-8"
            )
            environment = dict(os.environ, RECOVERA_MIGRATION_ROOT=str(root))
            subprocess.run(["bash", str(MIGRATOR)], env=environment, check=True, capture_output=True, text=True)
            subprocess.run(["bash", str(MIGRATOR)], env=environment, check=True, capture_output=True, text=True)
            self.assertFalse(old_install.exists())
            self.assertFalse(old_state.exists())
            self.assertEqual((root / "opt/recovera/setup.conf").read_text(), "LOGIN_USER=test\n")
            self.assertEqual((root / "var/lib/recovera-setup/p10.done").read_text(), "done\n")
            self.assertIn(
                "file:/opt/recovera/debs",
                (old_apt / "recovera-local.list").read_text(encoding="utf-8"),
            )
            self.assertFalse((old_units / "spf-datto-verify.service").exists())
            self.assertTrue((old_units / "recovera-verify.service").exists())

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "requires a Linux shell")
    def test_layout_migration_does_not_fail_when_legacy_backup_cannot_move(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_backup = root / "root/spf-datto-backup"
            legacy_backup.mkdir(parents=True)
            (legacy_backup / "keep.txt").write_text("keep\n", encoding="utf-8")

            bin_dir = root / "test-bin"
            bin_dir.mkdir()
            real_mv = shutil.which("mv")
            fake_mv = bin_dir / "mv"
            fake_mv.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in */root/spf-datto-backup) exit 30;; esac\n"
                f'exec "{real_mv}" "$@"\n',
                encoding="utf-8",
            )
            fake_mv.chmod(0o755)

            environment = dict(
                os.environ,
                RECOVERA_MIGRATION_ROOT=str(root),
                PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            )
            result = subprocess.run(
                ["bash", str(MIGRATOR)],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue((legacy_backup / "keep.txt").is_file())
            self.assertIn("preserving /root/spf-datto-backup", result.stdout)


if __name__ == "__main__":
    unittest.main()
