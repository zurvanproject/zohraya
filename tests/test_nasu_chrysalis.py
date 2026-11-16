"""Synthetic, isolated Chrysalis tests; never reach a real VPS or an API."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import nasu_chrysalis as c

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def control(last, *, armed=True, revision=1):
    return {"schema": c.SCHEMA, "armed": armed, "revision": revision, "last_seen_utc": c.stamp(last)}


class ChrysalisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.marker_dir = self.base / "protected"
        self.marker_dir.mkdir(mode=0o700)
        self.marker = self.marker_dir / "control.json"
        self.state = self.base / "state"
        self.mission = self.base / "fake-mission.py"
        self.mission.write_text("synthetic only\n", encoding="utf-8")
        self.owner = os.getuid()

    def put(self, obj):
        self.marker.write_text(json.dumps(obj), encoding="utf-8")
        self.marker.chmod(0o644)

    def call_tick(self, now=NOW, runner=None):
        with patch.object(c.os, "geteuid", return_value=10001):
            with patch.object(c, "verify_mission", return_value=True):
                return c.tick(now=now, control_path=self.marker, state_dir=self.state,
                              mission_path=self.mission, marker_uid=self.owner,
                              mission_uid=self.owner,
                              runner=runner or (lambda _: {"status": "completed"}))

    def test_unarmed_default_does_not_create_work(self):
        response = self.call_tick()
        self.assertEqual(response["mode"], "DISARMED")
        self.assertFalse(self.state.exists())
        self.put(control(NOW - dt.timedelta(days=8), armed=False))
        self.assertEqual(self.call_tick()["mode"], "DISARMED")

    def test_24h_precise_threshold_and_not_a_war_detector(self):
        self.put(control(NOW - dt.timedelta(hours=23, minutes=59, seconds=59)))
        self.assertEqual(self.call_tick()["mode"], "ARMED")
        self.put(control(NOW - dt.timedelta(hours=24)))
        result = self.call_tick()
        self.assertEqual((result["mode"], result["mission"]), ("CHRYSALIS", "completed"))
        self.assertFalse(result["trigger_is_war_detection"])

    def test_root_owned_marker_required_by_production(self):
        self.put(control(NOW - dt.timedelta(hours=25)))
        with self.assertRaisesRegex(ValueError, "insecure-chrysalis-control-ownership"):
            c.read_control(self.marker, required_uid=self.owner + 100)
        with self.assertRaisesRegex(ValueError, "insecure-chrysalis-control-ownership"):
            self.marker.chmod(0o666)
            c.read_control(self.marker, required_uid=self.owner)

    def test_future_timestamp_hold_and_fail_closed(self):
        self.put(control(NOW + dt.timedelta(hours=6)))
        result = self.call_tick()
        self.assertEqual(result["mode"], "HOLD")
        self.assertFalse(self.state.exists())

    def test_old_clock_cannot_arm_time_travel(self):
        self.put(control(NOW))
        with patch.object(c.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "clock-rollback"):
                c.set_owner_control("heartbeat", path=self.marker, now=NOW - dt.timedelta(hours=1))

    def test_root_heartbeat_resets_24h_clock_and_can_disarm(self):
        self.put(control(NOW - dt.timedelta(hours=30), revision=2))
        with patch.object(c.os, "geteuid", return_value=0):
            outcome = c.set_owner_control("heartbeat", path=self.marker, now=NOW)
        self.assertEqual(outcome["revision"], 3)
        self.assertEqual(self.call_tick()["mode"], "ARMED")
        with patch.object(c.os, "geteuid", return_value=0):
            c.set_owner_control("disarm", path=self.marker, now=NOW)
        self.assertEqual(self.call_tick()["mode"], "DISARMED")
        self.assertFalse(self.state.exists())

    def test_only_once_each_utc_day_across_restart(self):
        self.put(control(NOW - dt.timedelta(days=2)))
        attempts = []
        def runner(_):
            attempts.append(1)
            return {"status": "completed_without_qwen"}
        self.assertEqual(self.call_tick(runner=runner)["mission"], "completed_without_qwen")
        self.assertEqual(self.call_tick(runner=runner)["cause"], "daily-mission-already-reserved")
        self.assertEqual(len(attempts), 1)
        with sqlite3.connect(self.state / "runs.sqlite3") as db:
            row = db.execute("SELECT state, heartbeat_revision FROM runs").fetchone()
        self.assertEqual(row, ("completed_without_qwen", 1))

    def test_crash_never_replays_uncertain_mission(self):
        self.put(control(NOW - dt.timedelta(hours=25)))
        attempts = []
        def crash(_):
            attempts.append(1)
            raise RuntimeError("simulated power failure")
        with self.assertRaisesRegex(RuntimeError, "power failure"):
            self.call_tick(runner=crash)
        self.assertEqual(self.call_tick(runner=crash)["cause"], "daily-mission-already-reserved")
        self.assertEqual(len(attempts), 1)
        with sqlite3.connect(self.state / "runs.sqlite3") as db:
            self.assertEqual(db.execute("SELECT state FROM runs").fetchone()[0], "reserved")

    def test_new_heartbeat_before_dispatch_prevents_mission(self):
        old = control(NOW - dt.timedelta(hours=30))
        new = control(NOW, revision=2)
        self.put(old)
        with patch.object(c, "read_control", side_effect=[old, new]):
            self.assertEqual(self.call_tick()["cause"], "fresh-owner-signal")
        with sqlite3.connect(self.state / "runs.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_missing_pinned_mission_fails_before_reservation(self):
        self.put(control(NOW - dt.timedelta(days=1, minutes=1)))
        with patch.object(c.os, "geteuid", return_value=10001):
            result = c.tick(now=NOW, control_path=self.marker, state_dir=self.state,
                            mission_path=self.mission, marker_uid=self.owner)
        self.assertEqual(result["mode"], "HOLD")
        self.assertEqual(result["cause"], "reviewed-local-mission-not-installed")
        self.assertFalse(self.state.exists())

    def test_signals_are_not_accepted_as_raw_model_or_document_text(self):
        self.marker.write_text('{"schema": "nasuraya-chrysalis/1", "armed": true,'
                               '"armed": false, "last_seen_utc":"2026-11-15T12:00:00Z",'
                               '"revision":1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate-control-field"):
            c.read_control(self.marker, required_uid=self.owner)

    def test_symlinked_marker_not_trusted(self):
        target = self.base / "untrusted.json"
        target.write_text(json.dumps(control(NOW - dt.timedelta(days=2))), encoding="utf-8")
        self.marker.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "nonregular-chrysalis-control"):
            c.read_control(self.marker, required_uid=self.owner)


if __name__ == "__main__":
    unittest.main()
