"""Synthetic contract tests only. Never touch the VPS or a private Awake DB."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
import urllib.request

from tools import nasu_unified_status as hub
from tools import nasuraya_offline_continuity as continuity
from tools import nasu_autonomous_cognition as cognition
from tools import nasu_frontier_lab as frontier
from tools import nasu_feedback_learning as feedback

NOW = dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc)


class UnifiedStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "nasuraya"
        self.home.mkdir()

    def path(self, rel):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def snap(self):
        return hub.collect(self.home, now=NOW)

    def make_awake(self, rel="awake-stage/awake.sqlite3", *,
                   schema="tadash-awake/1", private=False):
        p = self.path(rel)
        with sqlite3.connect(p) as db:
            db.executescript("""
                CREATE TABLE control(name TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE evidence(id TEXT PRIMARY KEY,topic TEXT,payload TEXT);
                CREATE TABLE questions(topic TEXT PRIMARY KEY,question TEXT);
                CREATE TABLE ticks(seq INTEGER PRIMARY KEY,at TEXT);
                CREATE TABLE ledger(seq INTEGER PRIMARY KEY,detail TEXT);
            """)
            db.executemany("INSERT INTO control VALUES(?,?)",
                           [("schema", schema), ("paused", "1")])
            if private:
                db.execute("INSERT INTO evidence VALUES(?,?,?)",
                           ("1", "test", "PRIVATE_SECRET_PATIENT_INFORMATION"))
                db.execute("INSERT INTO questions VALUES(?,?)",
                           ("test", "PRIVATE_SECRET_PATIENT_INFORMATION"))
        return p

    def test_missing_is_not_healthy_and_creates_nothing(self):
        before = list(self.home.rglob("*"))
        result = self.snap()
        self.assertEqual(before, list(self.home.rglob("*")))
        self.assertEqual(set(result["components"]), {
            "continuity", "frontier", "cognition", "feedback", "awake"})
        self.assertTrue(all(x["status"] == "missing"
                            for x in result["components"].values()))
        self.assertEqual(result["overall"], "PARTIAL_NOT_LIVE_INTEGRATED")

    def test_local_continuity_chain_is_checked(self):
        root = self.home / "continuity"
        db = continuity.open_db(root)
        hour = "2026-11-19T00:00Z"
        stamp = NOW.isoformat()
        raw = '{"load":0.5}'
        digest = continuity.digest(continuity.ZERO, hour, stamp, raw)
        db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) "
                   "VALUES (?,?,?,?,?)", (hour, stamp, raw, continuity.ZERO, digest))
        db.close()
        p = root / "continuity.sqlite3"
        fingerprint = hashlib.sha256(p.read_bytes()).hexdigest()
        result = self.snap()["components"]["continuity"]
        self.assertEqual(result["status"], "verified_history")
        self.assertEqual(result["records"], 1)
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), fingerprint)
        with sqlite3.connect(p) as db:
            db.execute("UPDATE observations SET metrics='{}'")
        self.assertEqual(self.snap()["components"]["continuity"]["status"], "invalid")

    def test_frontier_is_a_historical_draft_not_live_ai(self):
        db = frontier.connect(self.path("frontier-lab/frontier.sqlite3"))
        frontier.run(db, now=NOW, sample={
            "load_1min": 0.2, "memory_available_pct": 70.0,
            "disk_available_pct": 80.0}, questioner=False)
        db.close()
        result = self.snap()
        self.assertEqual(result["components"]["frontier"]["status"], "verified_history")
        self.assertEqual(result["components"]["frontier"]["days"], 1)
        self.assertIn("live_dios_body_ritual_visual_integration",
                      result["unverified_gates"])

    def test_cognition_model_draft_is_not_exposed(self):
        db = cognition.connect(self.path("cognitive-growth/cycles.sqlite3"))
        record = {"slot": "2026-11-19T00", "stamp": NOW.isoformat(),
                  "topic": "continuity", "source_path": "trusted.py",
                  "source_sha": "f" * 64, "fixed_result": "PASS",
                  "model_status": "UNVERIFIED_DRAFT",
                  "proposal": '{"hypothesis":"PRIVATE_SECRET_TEXT"}',
                  "next_topic": "", "previous_sha": cognition.ZERO}
        receipt = cognition.sha(record)
        db.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (*record.values(), receipt, "completed"))
        db.close()
        result = self.snap()["components"]["cognition"]
        self.assertEqual(result["status"], "verified_history")
        self.assertEqual(result["latest"]["model_status"], "UNVERIFIED_DRAFT")
        self.assertNotIn("PRIVATE_SECRET_TEXT", json.dumps(result))
        with sqlite3.connect(self.home / "cognitive-growth/cycles.sqlite3") as db:
            db.execute("UPDATE cycles SET model_status='APPROVED'")
        self.assertEqual(self.snap()["components"]["cognition"]["status"], "invalid")

    def test_rehashed_cognition_metadata_cannot_publish_private_text(self):
        db = cognition.connect(self.path("cognitive-growth/cycles.sqlite3"))
        self.addCleanup(db.close)
        base = {"slot": "2026-11-19T00", "stamp": NOW.isoformat(),
                "topic": "continuity", "source_path": "trusted.py",
                "source_sha": "f" * 64, "fixed_result": "PASS",
                "model_status": "UNVERIFIED_DRAFT", "proposal": "{}",
                "next_topic": "", "previous_sha": cognition.ZERO}
        for field in ("slot", "topic", "model_status"):
            with self.subTest(field=field):
                db.execute("DELETE FROM cycles")
                record = {**base, field: "PRIVATE_SECRET_METADATA"}
                db.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (*record.values(), cognition.sha(record), "completed"))
                result = self.snap()["components"]["cognition"]
                self.assertEqual(result["status"], "invalid")
                self.assertNotIn("PRIVATE_SECRET_METADATA", json.dumps(result))
        db.execute("DELETE FROM cycles")
        record = {**base, "model_status": "source_unavailable:PRIVATE_SECRET_METADATA"}
        db.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (*record.values(), cognition.sha(record), "completed"))
        result = self.snap()["components"]["cognition"]
        self.assertEqual(result["latest"]["model_status"], "source_unavailable")
        self.assertNotIn("PRIVATE_SECRET_METADATA", json.dumps(result))

    def test_rehashed_continuity_timestamp_cannot_publish_private_text(self):
        db = continuity.open_db(self.home / "continuity")
        self.addCleanup(db.close)
        hour = "PRIVATE_SECRET_TIMESTAMP"
        stamp = NOW.isoformat()
        digest = continuity.digest(continuity.ZERO, hour, stamp, "{}")
        db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) "
                   "VALUES (?,?,?,?,?)", (hour, stamp, "{}", continuity.ZERO, digest))
        result = self.snap()["components"]["continuity"]
        self.assertEqual(result["status"], "invalid")
        self.assertNotIn(hour, json.dumps(result))

    def test_read_snapshot_includes_uncheckpointed_wal_rows(self):
        db = continuity.open_db(self.home / "continuity")
        self.addCleanup(db.close)
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        hour = "2026-11-19T00:00Z"
        stamp = NOW.isoformat()
        digest = continuity.digest(continuity.ZERO, hour, stamp, "{}")
        db.execute("INSERT INTO observations(hour,observed_at,metrics,previous,digest) "
                   "VALUES (?,?,?,?,?)", (hour, stamp, "{}", continuity.ZERO, digest))
        self.assertGreater((self.home / "continuity/continuity.sqlite3-wal").stat().st_size, 0)
        result = self.snap()
        self.assertEqual(result["components"]["continuity"]["records"], 1)
        self.assertIn("WAL/SHM", result["note"])

    def test_verification_and_projection_share_one_read_snapshot(self):
        writer = cognition.connect(self.path("cognitive-growth/cycles.sqlite3"))
        self.addCleanup(writer.close)
        first = {"slot": "2026-11-19T00", "stamp": NOW.isoformat(),
                 "topic": "continuity", "source_path": "trusted.py",
                 "source_sha": "f" * 64, "fixed_result": "PASS",
                 "model_status": "UNVERIFIED_DRAFT", "proposal": "{}",
                 "next_topic": "", "previous_sha": cognition.ZERO}
        writer.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (*first.values(), cognition.sha(first), "completed"))
        second = {**first, "slot": "2026-11-19T06", "topic": "frontier",
                  "previous_sha": cognition.sha(first)}
        verify = cognition.verify
        def verify_then_commit(reader):
            verified = verify(reader)
            writer.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (*second.values(), cognition.sha(second), "completed"))
            return verified
        with mock.patch.object(cognition, "verify", side_effect=verify_then_commit):
            result = self.snap()["components"]["cognition"]
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["latest"]["topic"], "continuity")
        self.assertEqual(self.snap()["components"]["cognition"]["completed"], 2)

    def test_feedback_receipts_are_distinguished_from_training(self):
        db = feedback.connect(self.path("learning-lab/feedback.sqlite3"))
        record = {"day": "2026-11-19", "task_index": 0,
                  "payload": {"status": "MODEL_UNAVAILABLE"},
                  "previous_sha": feedback.ZERO}
        digest = feedback.sha(record)
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                   (record["day"], 0, "completed", feedback.canon(record["payload"]),
                    feedback.ZERO, digest))
        db.close()
        result = self.snap()["components"]["feedback"]
        self.assertEqual(result["status"], "verified_history")
        self.assertEqual(result["comparable"], 0)
        self.assertIn("not_weight_training", result["evidence"])

    def test_incomplete_receipt_is_not_reported_as_pass(self):
        db = feedback.connect(self.path("learning-lab/feedback.sqlite3"))
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                   ("2026-11-19", 0, "reserved", "{}", feedback.ZERO, ""))
        db.close()
        result = self.snap()
        self.assertEqual(result["components"]["feedback"]["status"], "incomplete")
        self.assertEqual(result["priority"], "review_invalid_or_incomplete_local_receipts")

    def test_awake_is_never_called_authenticated(self):
        self.make_awake(private=True)
        result = self.snap()["components"]["awake"]
        self.assertEqual(result["status"], "structural_only")
        self.assertTrue(result["paused"])
        self.assertEqual(result["counts"]["evidence"], 1)
        self.assertNotIn("PRIVATE_SECRET_PATIENT_INFORMATION",
                         json.dumps(self.snap(), ensure_ascii=False))

    def test_awake_wrong_schema_fails_closed(self):
        self.make_awake(schema="unknown/1")
        self.assertEqual(self.snap()["components"]["awake"]["status"], "invalid")

    def test_migrated_awake_is_found_only_under_approved_working_root(self):
        p = self.make_awake("migration/working/controlled/awake.sqlite3")
        m = self.path("migration/latest-import.json")
        m.write_text(json.dumps({"id": "controlled", "working_db": str(p)}))
        self.assertEqual(self.snap()["components"]["awake"]["status"],
                         "structural_only")
        m.write_text(json.dumps({"working_db": "/etc/shadow"}))
        self.assertEqual(self.snap()["components"]["awake"]["status"], "invalid")

    def test_nonobject_migration_manifest_fails_closed(self):
        manifest = self.path("migration/latest-import.json")
        for value in ([], None, "PRIVATE_SECRET_MANIFEST", 42, True):
            with self.subTest(value=value):
                manifest.write_text(json.dumps(value))
                result = self.snap()["components"]["awake"]
                self.assertEqual(result["status"], "invalid")
                self.assertNotIn("PRIVATE_SECRET_MANIFEST", json.dumps(result))

    def test_symlink_above_home_is_rejected(self):
        parent_link = Path(self.temp.name) / "linked_parent"
        parent_link.symlink_to(self.home.parent, target_is_directory=True)
        result = hub.collect(parent_link / self.home.name, now=NOW)
        self.assertTrue(all(item["status"] == "invalid"
                            for item in result["components"].values()))

    def test_symlinked_db_is_rejected(self):
        outside = Path(self.temp.name) / "real.sqlite3"
        sqlite3.connect(outside).close()
        p = self.path("frontier-lab/frontier.sqlite3")
        p.symlink_to(outside)
        result = self.snap()["components"]["frontier"]
        self.assertEqual(result["status"], "invalid")

    def test_no_network_no_subprocess_no_write_on_read(self):
        self.make_awake()
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("network")):
            with mock.patch("subprocess.run",
                            side_effect=AssertionError("command")):
                self.assertEqual(self.snap()["execution"], "OFFLINE_READ_ONLY")
        self.assertFalse((self.home / "cognitive-growth").exists())

    def test_rejects_non_utc_clock(self):
        not_utc = dt.datetime(2026, 11, 19,
                              tzinfo=dt.timezone(dt.timedelta(hours=3)))
        with self.assertRaises(ValueError):
            hub.collect(self.home, now=not_utc)


if __name__ == "__main__":
    unittest.main()
