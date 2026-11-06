"""Security and integration-boundary tests for read-only Tadash observer."""
from pathlib import Path
import json
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_virtual_learning import bridge, engine


def good_status(count=1, source="verified-native-checkpoint"):
    return {
        "schema": bridge.NATIVE_SCHEMA, "ready": True,
        "synchronized": True, "recent_receipts_agree": True,
        "initial_source_pinned": True, "all_experience_flags_enabled": True,
        "software_only": True, "physical_actuation": False, "api_calls": 0,
        "pending_intents": [], "completed_cycles": count,
        "last_receipt_source": source if count else None,
        "counters": {key: count for key in bridge.EXPECTED_COUNTERS},
    }


class NativeBoundaryTests(unittest.TestCase):
    def test_verified_status(self):
        data = bridge.validate_native_status(good_status(2, "checkpoint:2"))
        self.assertEqual(data["completed_cycles"], 2)
        self.assertFalse(data["physical_actuation"])

    def test_reject_divergence_and_unverified_input(self):
        changes = [
            ("synchronized", False), ("ready", False),
            ("initial_source_pinned", False), ("pending_intents", ["orphan"]),
            ("physical_actuation", True), ("api_calls", 1),
            ("completed_cycles", -1), ("last_receipt_source", None),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                item = good_status()
                item[key] = value
                with self.assertRaises(ValueError):
                    bridge.validate_native_status(item)
        item = good_status()
        item["counters"]["native"] = 99
        with self.assertRaises(ValueError):
            bridge.validate_native_status(item)

    def test_native_probe_only_reads_snapshot_and_never_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body_root = root / "body"
            (body_root / "examples/nasuraya_body_loop").mkdir(parents=True)
            (body_root / "examples/nasuraya_body_loop/__main__.py").write_text("")
            session = root / "live.sqlite"
            with sqlite3.connect(session) as conn:
                conn.execute("CREATE TABLE witness (id INTEGER PRIMARY KEY)")
                conn.execute("INSERT INTO witness VALUES (42)")
            seen = []
            def fake_run(command, **kwargs):
                self.assertIn("unified-status", command)
                self.assertNotIn("unified-step", command)
                self.assertNotIn("api", command)
                self.assertNotEqual(command[-1], str(session))
                with sqlite3.connect(command[-1]) as conn:
                    seen.extend(conn.execute("SELECT id FROM witness").fetchall())
                self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps(good_status()), stderr="")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-secret"}):
                with patch.object(bridge.subprocess, "run", side_effect=fake_run) as run:
                    result = bridge.observe_native(body_root, session)
            self.assertEqual(seen, [(42,)])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(result["completed_cycles"], 1)
            with sqlite3.connect(session) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM witness").fetchone()[0], 1)

    def test_checkpoint_idempotence_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            with bridge._open_ledger(Path(directory) / "checkpoints.sqlite") as ledger:
                a = bridge.validate_native_status(good_status(0))
                b = bridge.validate_native_status(good_status(1, "native-1"))
                self.assertTrue(bridge.append_checkpoint(ledger, a))
                self.assertFalse(bridge.append_checkpoint(ledger, a))
                self.assertTrue(bridge.append_checkpoint(ledger, b))
                self.assertFalse(bridge.append_checkpoint(ledger, b))
                with self.assertRaises(ValueError):
                    bridge.append_checkpoint(ledger, a)
                with self.assertRaises(ValueError):
                    bridge.append_checkpoint(ledger, bridge.validate_native_status(
                        good_status(1, "different-native-1")))
                self.assertEqual(ledger.execute(
                    "SELECT count(*) FROM native_status_snapshots").fetchone()[0], 2)

    def test_finite_ritual_status_without_native_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ritual = root / "ritual.sqlite"
            engine.demo(ritual)
            report = bridge.run_once(ritual, root / "observer.sqlite", None, None)
            self.assertEqual(report["ritual"]["synthetic_episodes"], 12)
            self.assertEqual(report["ritual"]["synthetic_holdout"], 6)
            self.assertEqual(report["native"], "not_configured")
            self.assertFalse((root / "observer.sqlite").exists())

    def test_waiting_for_session_is_non_actuating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = bridge.run_once(root / "missing.sqlite", root / "observer.sqlite",
                                     root, root / "no-native.sqlite")
            self.assertEqual(result["native"], "waiting_for_session")
            self.assertFalse((root / "observer.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
