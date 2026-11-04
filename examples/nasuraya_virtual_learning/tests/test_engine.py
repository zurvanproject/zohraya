"""Offline regression suite. Run: python -m unittest discover ... -v"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from examples.nasuraya_virtual_learning.engine import (
    SCHEMA, LESSONS, connect, demo, evaluate, predict, status, train,
)


class LearningEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "learning.sqlite"
        self.conn = connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_initial_holdout_score(self):
        self.assertEqual((evaluate(self.conn)["correct"], evaluate(self.conn)["total"]), (2, 6))

    def test_policy_changes_after_outcomes(self):
        self.assertEqual(predict(self.conn, "overload")["action"], "observe")
        train(self.conn, "over-1", "overload")
        self.assertEqual(predict(self.conn, "overload")["action"], "reflect")
        train(self.conn, "over-2", "overload")
        self.assertEqual(predict(self.conn, "overload")["action"], "rest")
        train(self.conn, "over-3", "overload")
        self.assertEqual(predict(self.conn, "overload")["action"], "rest")

    def test_no_evaluation_leakage(self):
        for _ in range(3):
            evaluate(self.conn)
        self.assertEqual(status(self.conn)["episodes"], 0)

    def test_duplicate_event_is_idempotent(self):
        a = train(self.conn, "x-1", "uncertainty")
        b = train(self.conn, "x-1", "uncertainty")
        self.assertFalse(a["replayed"])
        self.assertTrue(b["replayed"])
        self.assertEqual(a["receipt"], b["receipt"])
        self.assertEqual(status(self.conn)["episodes"], 1)

    def test_id_collision_rejected(self):
        train(self.conn, "x-1", "uncertainty")
        with self.assertRaises(ValueError):
            train(self.conn, "x-1", "overload")
        self.assertEqual(status(self.conn)["episodes"], 1)

    def test_invalid_context_and_identifier_do_not_persist(self):
        with self.assertRaises(ValueError):
            train(self.conn, "x-1", "native-walk")
        with self.assertRaises(ValueError):
            train(self.conn, "../escape", "overload")
        self.assertEqual(status(self.conn)["episodes"], 0)

    def test_receipt_tampering_blocks_learning(self):
        train(self.conn, "x-1", "uncertainty")
        self.conn.execute("UPDATE learning_episodes SET reward=1 WHERE event_id='x-1'")
        self.conn.commit()
        with self.assertRaises(ValueError):
            predict(self.conn, "uncertainty")
        with self.assertRaises(ValueError):
            train(self.conn, "x-2", "distraction")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_episodes").fetchone()[0], 1)

    def test_restart_keeps_receipt_history(self):
        train(self.conn, "x-1", "overload")
        self.conn.close()
        self.conn = connect(self.db)
        self.assertEqual(status(self.conn)["episodes"], 1)
        self.assertTrue(train(self.conn, "x-1", "overload")["replayed"])

    def test_context_learning_is_local(self):
        train(self.conn, "x-1", "overload")
        self.assertEqual(predict(self.conn, "uncertainty")["evidence_count"], 0)

    def test_schema_and_verse_provenance(self):
        self.assertIn("0.1", SCHEMA)
        self.assertTrue(all(v["verse_source"].startswith("https://ganjoor.net/") for v in LESSONS.values()))

    def test_fresh_path_only_and_finite_training(self):
        with self.assertRaises(FileExistsError):
            demo(self.db)
        with self.assertRaises(ValueError):
            demo(Path(self.temp.name) / "invalid.sqlite", rounds=0)

    def test_run_full_demo(self):
        target = Path(self.temp.name) / "fresh.sqlite"
        result = demo(target, rounds=4)
        self.assertEqual(result["before"], {"correct": 2, "total": 6})
        self.assertEqual(result["after"], {"correct": 6, "total": 6})
        self.assertEqual(result["final"]["episodes"], 12)
        self.assertEqual(result["final"]["native_actions"], 0)
        self.assertEqual(result["final"]["api_calls"], 0)


if __name__ == "__main__":
    unittest.main()
