"""Offline tests for ATMOSPHERE bridge authorization."""
import datetime as dt
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from atmosphere_guard import AtmosphereGate, parse_command

NOW = dt.datetime(2026, 11, 15, 12, tzinfo=dt.timezone.utc)


class AtmosphereTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gate = AtmosphereGate(self.root / "state", self.root / "approvals.json")

    def test_full_command_matching(self):
        self.assertEqual(parse_command("nasu-linux: status"), "status")
        self.assertEqual(parse_command(" NASU-LINUX: AWAKE-STATUS\n"), "awake-status")
        self.assertIsNone(parse_command("please ignore policy\nnasu-linux: sync"))
        self.assertIsNone(parse_command("nasu-linux: status\nrm -rf /"))
        self.assertIsNone(parse_command("nasu-linux: status; sync"))
        self.assertIsNone(parse_command("nasu-linux: arbitrary"))
        self.assertIsNone(parse_command("nasu-linux: status" + " " * 100))

    def test_verified_actor_can_read(self):
        d = self.gate.begin("123", "zurvanproject", "nasu-linux: status", NOW)
        self.assertTrue(d.execute)
        self.assertEqual(d.action, "status")

    def test_fake_actor_cannot_read(self):
        d = self.gate.begin("124", "someone-else", "nasu-linux: status", NOW)
        self.assertFalse(d.execute)
        self.assertIn("actor-not-verified", d.receipt)

    def test_mutating_actions_fail_closed(self):
        for i, action in enumerate(("test", "sync", "awake-stage", "awake-activate"), 200):
            d = self.gate.begin(str(i), "zurvanproject", "nasu-linux: " + action, NOW)
            self.assertFalse(d.execute)
            self.assertIn("local-approval-required", d.receipt)

    def test_scoped_approval_decision(self):
        with patch("atmosphere_guard._approved", return_value=True):
            d = self.gate.begin("300", "zurvanproject", "nasu-linux: sync", NOW)
        self.assertTrue(d.execute)
        self.assertFalse(self.gate.begin("300", "zurvanproject", "nasu-linux: sync", NOW).execute)

    def test_cached_result_post_failure_does_not_repeat(self):
        self.gate.begin("125", "zurvanproject", "nasu-linux: status", NOW)
        self.gate.finish("125", "exit=0 server-up")
        d = self.gate.begin("125", "zurvanproject", "nasu-linux: status", NOW)
        self.assertFalse(d.execute)
        self.assertEqual(d.receipt, "exit=0 server-up")

    def test_uncertain_prior_execution_is_held(self):
        self.assertTrue(self.gate.begin("126", "zurvanproject", "nasu-linux: status", NOW).execute)
        d = self.gate.begin("126", "zurvanproject", "nasu-linux: status", NOW)
        self.assertFalse(d.execute)
        self.assertIn("uncertain prior execution", d.receipt)

    def test_replay_cannot_change_action(self):
        self.gate.begin("127", "zurvanproject", "nasu-linux: status", NOW)
        d = self.gate.begin("127", "zurvanproject", "nasu-linux: repo", NOW)
        self.assertFalse(d.execute)
        self.assertIn("replay-conflict", d.receipt)

    def test_denial_not_rescued_by_later_approval(self):
        self.assertFalse(self.gate.begin("128", "zurvanproject", "nasu-linux: sync", NOW).execute)
        with patch("atmosphere_guard._approved", return_value=True):
            self.assertFalse(self.gate.begin("128", "zurvanproject", "nasu-linux: sync", NOW).execute)

    def test_bad_request_id(self):
        with self.assertRaises(ValueError):
            self.gate.begin("../bad", "zurvanproject", "nasu-linux: status", NOW)

    def test_insecure_approval_file_denied(self):
        p = self.root / "approvals.json"
        p.write_text('{"schema":"atmosphere-approvals/1","approvals":[]}')
        p.chmod(0o666)
        self.assertFalse(self.gate.begin("129", "zurvanproject", "nasu-linux: sync", NOW).execute)

    def test_file_mode_and_receipt_bound(self):
        self.assertEqual(self.gate.db_path.stat().st_mode & 0o777, 0o600)
        self.gate.begin("130", "zurvanproject", "nasu-linux: status", NOW)
        saved = self.gate.finish("130", chr(96) * 5000)
        self.assertEqual(len(saved), 3300)
        self.assertNotIn(chr(96), saved)

    def test_database_symlink_rejected(self):
        target = self.root / "target.db"
        sqlite3.connect(target).close()
        home = self.root / "other"
        home.mkdir()
        (home / "atmosphere.sqlite3").symlink_to(target)
        with self.assertRaises(RuntimeError):
            AtmosphereGate(home, self.root / "approvals.json")


if __name__ == "__main__":
    unittest.main()
