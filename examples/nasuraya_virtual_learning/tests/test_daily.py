"""Replay-safe, finite daily virtual lessons."""
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

from examples.nasuraya_virtual_learning import daily


class DailyTests(unittest.TestCase):
    def test_once_and_same_day_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "ritual.sqlite"
            day = date(2026, 11, 6)
            first = daily.run_day(db, day)
            self.assertEqual(first["total_synthetic_episodes"], 3)
            self.assertTrue(all(not x["replayed"] for x in first["events"]))
            replay = daily.run_day(db, day)
            self.assertEqual(replay["total_synthetic_episodes"], 3)
            self.assertTrue(all(x["replayed"] for x in replay["events"]))
            next_day = daily.run_day(db, date(2026, 11, 7))
            self.assertEqual(next_day["total_synthetic_episodes"], 6)
            self.assertEqual(next_day["native_body_actions"], 0)
            self.assertEqual(next_day["external_api_calls"], 0)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM learning_episodes").fetchone()[0], 6)

    def test_reject_symlink_to_existing_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            existing = base / "other.sqlite"
            existing.touch()
            (base / "link.sqlite").symlink_to(existing)
            with self.assertRaises(ValueError):
                daily.run_day(base / "link.sqlite", date(2026, 11, 6))


if __name__ == "__main__":
    unittest.main()
