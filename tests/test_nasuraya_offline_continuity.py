"""Offline continuity safety tests; no network required."""
import datetime as dt
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / "tools" / "nasuraya_offline_continuity.py"
spec = importlib.util.spec_from_file_location("nasu_offline_continuity", FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class OfflineContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.db = module.open_db(self.path)
        self.addCleanup(self.db.close)
        self.now = dt.datetime(2026, 11, 14, 1, 30, tzinfo=dt.timezone.utc)

    def test_hourly_tick_persists_and_is_idempotent(self):
        with patch.object(module, "observe", return_value={"cpu": 1}):
            a = module.tick(self.db, self.path, self.now)
            b = module.tick(self.db, self.path, self.now)
        self.assertEqual(a["status"], "recorded")
        self.assertEqual(b["status"], "already_recorded")
        self.assertEqual(module.verify(self.db)["records"], 1)

    def test_tampering_fails_hash_chain(self):
        with patch.object(module, "observe", return_value={"cpu": 1}):
            module.tick(self.db, self.path, self.now)
        self.db.execute("UPDATE observations SET metrics='{}'")
        with self.assertRaisesRegex(RuntimeError, "hash chain"):
            module.verify(self.db)

    def test_clock_rollback_fails(self):
        with patch.object(module, "observe", return_value={}):
            module.tick(self.db, self.path, self.now)
        with self.assertRaisesRegex(RuntimeError, "Clock rollback"):
            module.tick(self.db, self.path, self.now - dt.timedelta(hours=2))

    def test_backup_integrity(self):
        with patch.object(module, "observe", return_value={}):
            result = module.tick(self.db, self.path, self.now)
        target = self.path / "backups" / "continuity-2026-11-14.sqlite3"
        self.assertTrue(target.exists())
        self.assertTrue(result["backup_sha256"])
        check = sqlite3.connect(target)
        try:
            self.assertEqual(check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            check.close()

if __name__ == "__main__":
    unittest.main()
