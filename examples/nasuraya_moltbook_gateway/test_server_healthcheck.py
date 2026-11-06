"""Offline safety and freshness tests for the Windows bridge healthcheck."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from examples.nasuraya_moltbook_gateway import server_healthcheck as h


NOW = datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_snapshot(self, **changes):
        data = {
            "schema": h.SCHEMA,
            "source": "https://www.moltbook.com",
            "agent": "nasuraya",
            "claim_status": "claimed",
            "checked_at_utc": h._iso(NOW),
            "posts": [{"title": "PRIVATE POST TITLE THAT MUST NOT ESCAPE", "content": "SECRET"}],
        }
        data.update(changes)
        path = self.root / h.SNAPSHOT
        path.write_text(json.dumps(data), encoding="utf-8")
        import os
        ts = NOW.timestamp()
        os.utime(path, (ts, ts))
        return path

    def test_no_snapshot(self):
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "missing")

    def test_fresh_snapshot_no_post_text_ever_returns(self):
        self.write_snapshot()
        with patch.object(h, "task_status", return_value={"state": "recent_success", "last_run_utc": h._iso(NOW), "last_result": 0}):
            result = h.report(self.root, NOW)
        self.assertEqual(result["overall"], "recent_local_evidence")
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("PRIVATE POST TITLE", json.dumps(result))
        self.assertFalse(result["remote_control_enabled"])
        self.assertFalse(result["logoff_or_reboot_persistence_verified"])

    def test_wrong_agent_not_accepted(self):
        self.write_snapshot(agent="someone_else")
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "invalid_header")

    def test_stale_snapshot_not_accepted(self):
        self.write_snapshot(checked_at_utc=h._iso(NOW - timedelta(hours=2)))
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "stale")

    def test_future_time_not_accepted(self):
        self.write_snapshot(checked_at_utc=h._iso(NOW + timedelta(minutes=20)))
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "clock_anomaly")

    def test_link_not_followed(self):
        outside = self.root / "outside"
        outside.write_text("secret", encoding="utf-8")
        try:
            (self.root / h.SNAPSHOT).symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted in this runner")
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "unsafe_path")

    def test_invalid_or_large_snapshot(self):
        path = self.root / h.SNAPSHOT
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "invalid_json")
        path.write_bytes(b"x" * (h.MAX_SNAPSHOT_BYTES + 1))
        self.assertEqual(h.snapshot_status(self.root, NOW, 45)["state"], "invalid_size")

    def test_task_success_with_recent_result(self):
        payload = {"installed": True, "state": "Ready", "last_result": 0, "last_run_utc": h._iso(NOW)}
        proc = Mock(returncode=0, stdout=json.dumps(payload))
        with patch.object(h.platform, "system", return_value="Windows"), patch.object(h.subprocess, "run", return_value=proc):
            result = h.task_status(NOW, 45)
        self.assertEqual(result["state"], "recent_success")

    def test_task_failed_stale_and_missing(self):
        with patch.object(h.platform, "system", return_value="Windows"):
            for payload, expected in [
                ({"installed": False, "state": "missing"}, "missing"),
                ({"installed": True, "state": "Ready", "last_result": 1, "last_run_utc": h._iso(NOW)}, "failed"),
                ({"installed": True, "state": "Ready", "last_result": 0, "last_run_utc": h._iso(NOW - timedelta(hours=3))}, "stale"),
            ]:
                with self.subTest(expected=expected), patch.object(h.subprocess, "run", return_value=Mock(returncode=0, stdout=json.dumps(payload))):
                    self.assertEqual(h.task_status(NOW, 45)["state"], expected)

    def test_task_command_fixed_no_external_data(self):
        with patch.object(h.platform, "system", return_value="Windows"), patch.object(h.subprocess, "run", side_effect=OSError("do not leak this text")):
            result = h.task_status(NOW, 45)
        self.assertEqual(result["state"], "unavailable")
        self.assertNotIn("do not leak", json.dumps(result))
        self.assertNotIn("Invoke-WebRequest", h._POWERSHELL)
        self.assertNotIn("Start-Process", h._POWERSHELL)


if __name__ == "__main__":
    unittest.main()
