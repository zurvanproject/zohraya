"""Cross-platform, offline recovery contracts for 90-day continuity kit."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ops.continuity.guardian import (
    check_sqlite, preflight, restore_drill, simulate_90_days,
    snapshot, verify,
)


class ContinuitySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nasuraya-ops-test-")
        self.root = Path(self.temp.name)
        self.db = self.root / "awake.sqlite3"
        self.snapshots = self.root / "backup-root"
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE ticks (seq INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO ticks(value) VALUES ('first')")

    def tearDown(self):
        self.temp.cleanup()

    def backup(self):
        return snapshot([self.db], self.snapshots)

    def test_online_wal_backup_copies_committed_data(self):
        result = self.backup()
        self.assertTrue(result["verified"])
        copy = Path(result["snapshot"]) / "awake.sqlite3"
        with sqlite3.connect(copy) as conn:
            row = conn.execute("SELECT value FROM ticks").fetchone()
        self.assertEqual(row, ("first",))
        self.assertEqual(verify(result["snapshot"])["files"], 1)

    def test_backup_snapshot_is_stable_against_future_live_writes(self):
        first = self.backup()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO ticks(value) VALUES ('second')")
        with sqlite3.connect(Path(first["snapshot"]) / "awake.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0], 1)
        second = self.backup()
        with sqlite3.connect(Path(second["snapshot"]) / "awake.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0], 2)

    def test_restore_drill_never_overwrites_live_database(self):
        backed = self.backup()
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO ticks(value) VALUES ('after backup')")
        prior = self.db.read_bytes()
        result = restore_drill(backed["snapshot"])
        self.assertTrue(result["no_live_database_modified"])
        self.assertEqual(self.db.read_bytes(), prior)

    def test_tampered_backup_fails_hash_check(self):
        backed = self.backup()
        data = Path(backed["snapshot"]) / "awake.sqlite3"
        with data.open("ab") as f:
            f.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "backup_file_hash_mismatch"):
            verify(backed["snapshot"])

    def test_tampered_manifest_count_fails(self):
        backed = self.backup()
        meta = Path(backed["snapshot"]) / "manifest.json"
        obj = json.loads(meta.read_text(encoding="utf-8"))
        obj["file_count"] = 2
        meta.write_text(json.dumps(obj), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory_count_mismatch"):
            verify(backed["snapshot"])

    def test_source_must_exist_and_be_sqlite(self):
        with self.assertRaisesRegex(ValueError, "source_must"):
            snapshot([self.root / "missing.db"], self.snapshots)
        text = self.root / "secret.txt"
        text.write_text("not a database", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source_must"):
            snapshot([text], self.snapshots)

    def test_backup_filename_cannot_escape_snapshot(self):
        backed = self.backup()
        meta = Path(backed["snapshot"]) / "manifest.json"
        obj = json.loads(meta.read_text(encoding="utf-8"))
        obj["files"][0]["file"] = "../outside.sqlite"
        meta.write_text(json.dumps(obj), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe_backup_filename"):
            verify(backed["snapshot"])

    @unittest.skipUnless(hasattr(os, "symlink"), "OS lacks symlinks")
    def test_source_symlink_rejected_when_permitted(self):
        shortcut = self.root / "source.db"
        try:
            shortcut.symlink_to(self.db)
        except (OSError, NotImplementedError):
            self.skipTest("symlink privilege unavailable")
        with self.assertRaisesRegex(ValueError, "source_must"):
            snapshot([shortcut], self.snapshots)

    def test_preflight_never_asserts_offsite_exists(self):
        self.backup()
        state = preflight([self.db], self.snapshots)
        self.assertTrue(state["no_network_requests_performed"])
        self.assertIn("OFFSITE_COPY_AND_BILLING_NOT_VERIFIED_BY_THIS_TOOL", state["issues"])
        self.assertTrue(state["local_snapshot_found"])

    def test_preflight_detects_absent_backups(self):
        state = preflight([self.db], self.root / "never-backed")
        self.assertIn("NO_LOCAL_BACKUP_DIRECTORY", state["issues"])

    def test_90day_disconnected_simulation_with_restore(self):
        result = simulate_90_days(90)
        self.assertTrue(result["pass"])
        self.assertEqual(result["offline_days_simulated"], 90)
        self.assertEqual(result["recovery_checkpoints"][-1]["rows_recovered"], 90)
        self.assertTrue(result["does_not_prove_llm_autonomy"])

    def test_bounds_on_timewarp(self):
        with self.assertRaisesRegex(ValueError, "invalid_simulated_days"):
            simulate_90_days(181)


if __name__ == "__main__":
    unittest.main()
