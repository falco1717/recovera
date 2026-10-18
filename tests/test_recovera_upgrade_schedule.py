import importlib.machinery
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / "upgrade" / "recovera-upgrade-schedule"


def load_schedule():
    loader = importlib.machinery.SourceFileLoader("recovera_upgrade_schedule", str(SCHEDULE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveraUpgradeScheduleTests(unittest.TestCase):
    def setUp(self):
        self.module = load_schedule()

    def run_inside_window(self, results):
        fake_datetime = mock.Mock()
        fake_datetime.now.return_value = mock.Mock(hour=22)
        policy = mock.Mock()
        policy.is_file.return_value = False
        with mock.patch.object(self.module, "POLICY", policy), mock.patch.object(
            self.module.datetime, "datetime", fake_datetime
        ), mock.patch.object(self.module.subprocess, "run", side_effect=results) as runner:
            status = self.module.main()
        return status, runner

    def test_available_release_is_installed_with_reboot(self):
        check = subprocess.CompletedProcess([], 0, json.dumps({"available": True}), "")
        install = subprocess.CompletedProcess([], 0, "", "")
        status, runner = self.run_inside_window([check, install])
        self.assertEqual(status, 0)
        self.assertEqual(
            runner.call_args_list,
            [
                mock.call([self.module.UPDATER, "check", "--cache"], check=False, capture_output=True, text=True),
                mock.call([self.module.UPDATER, "install", "--reboot"], check=False),
            ],
        )

    def test_current_release_does_not_install(self):
        check = subprocess.CompletedProcess([], 3, "", "")
        status, runner = self.run_inside_window([check])
        self.assertEqual(status, 0)
        self.assertEqual(runner.call_count, 1)

    def test_no_available_release_does_not_install(self):
        check = subprocess.CompletedProcess([], 0, json.dumps({"available": False}), "")
        status, runner = self.run_inside_window([check])
        self.assertEqual(status, 0)
        self.assertEqual(runner.call_count, 1)

    def test_invalid_check_output_fails_closed(self):
        check = subprocess.CompletedProcess([], 0, "not-json", "")
        status, runner = self.run_inside_window([check])
        self.assertEqual(status, 1)
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
