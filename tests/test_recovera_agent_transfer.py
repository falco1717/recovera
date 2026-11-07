import importlib.machinery
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "agents" / "linux" / "recovera-agent-transfer"


def load_module():
    if "fcntl" not in sys.modules:
        try:
            __import__("fcntl")
        except ModuleNotFoundError:
            sys.modules["fcntl"] = SimpleNamespace(LOCK_EX=2, flock=lambda *_args: None)
    loader = importlib.machinery.SourceFileLoader("recovera_agent_transfer_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecoveraAgentTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.module = load_module()
        self.module.DB = self.root / "agent.sqlite"
        self.module.LOCK = self.root / "release.lock"
        with sqlite3.connect(self.module.DB) as database:
            database.execute("CREATE TABLE device (id integer, ip text, agentUUID text)")
            database.execute("CREATE TABLE config (id integer primary key, key text, value text)")
            database.execute("INSERT INTO device VALUES (1234, '10.0.3.10', '')")
            database.execute("INSERT INTO config VALUES (1, 'sirisAssetId', 'asset')")

    def tearDown(self):
        self.temp.cleanup()

    def test_release_removes_only_stale_ownership_and_keeps_backup(self):
        inactive = mock.Mock(returncode=3, stdout=b"", stderr=b"")
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module, "active_snapshots", return_value=False), \
                mock.patch.object(self.module, "run", return_value=inactive):
            result = self.module.release_enrollment(1234)
        self.assertTrue(result["released"])
        self.assertTrue(Path(result["backup"]).is_file())
        with sqlite3.connect(self.module.DB) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM device").fetchone()[0], 0)
            self.assertEqual(database.execute(
                "SELECT COUNT(*) FROM config WHERE key = 'sirisAssetId'"
            ).fetchone()[0], 0)

    def test_release_refuses_wrong_appliance_or_active_snapshot(self):
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module, "active_snapshots", return_value=False):
            with self.assertRaisesRegex(self.module.ReleaseError, "does not own"):
                self.module.release_enrollment(9999)
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module, "active_snapshots", return_value=True):
            with self.assertRaisesRegex(self.module.ReleaseError, "active backup"):
                self.module.release_enrollment(1234)
