"""Falsification lab regression: toy receipts only; never native body actions."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from examples.nasuraya_virtual_learning.engine import (
    _hash, _payload, connect, status, train,
)
from examples.nasuraya_virtual_learning.self_falsification import (
    SCHEMA, audit, demo, falsify,
)


class SelfFalsificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nvle.sqlite"
        self.conn = connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_empty_database_does_not_claim_perfection(self):
        result = audit(self.conn)
        self.assertEqual(result["errors_found"], 0)
        self.assertEqual(result["status"], "no_recorded_errors")
        self.assertEqual(falsify(self.conn)["status"], "no_observed_error_to_challenge")

    def test_detects_own_first_wrong_prediction(self):
        trial = train(self.conn, "u-001", "uncertainty")
        self.assertEqual(trial["receipt"]["action"], "observe")
        report = audit(self.conn)
        self.assertEqual(report["errors_found"], 1)
        mistake = report["errors"][0]
        self.assertEqual(mistake["event_id"], "u-001")
        self.assertEqual((mistake["predicted"], mistake["observed_oracle"]),
                         ("observe", "reflect"))
        self.assertEqual(mistake["evidence_before"], 0)
        self.assertEqual(mistake["mechanism"], "cold_start_or_score_tie")
        self.assertEqual(set(mistake["scores_before"].values()), {0.5})

    def test_proposes_refutable_plan_then_recovers_on_toy_fixture(self):
        train(self.conn, "u-001", "uncertainty")
        pre_bytes = self.path.read_bytes()
        before_count = status(self.conn)["episodes"]
        before_changes = self.conn.total_changes
        result = falsify(self.conn)
        self.assertEqual(result["status"], "finite_probe_completed")
        self.assertEqual(result["verdict"], "supported_in_predefined_synthetic_fixture")
        self.assertEqual(result["plan_frozen_before_probe"]["source_event_id"], "u-001")
        self.assertEqual(result["control"]["correct_on_holdout"], 0)
        self.assertEqual(result["feedback_arm"]["correct_on_holdout"], 2)
        self.assertEqual(len(result["feedback_arm"]["sequential_new_synthetic_receipts"]), 3)
        self.assertEqual(status(self.conn)["episodes"], before_count)
        self.assertEqual(self.conn.total_changes, before_changes)
        self.assertEqual(self.path.read_bytes(), pre_bytes)
        self.assertFalse(result["auto_promotion"])
        self.assertEqual(result["native_actions"], 0)
        self.assertEqual(result["api_calls"], 0)

    def test_overload_requires_two_sequential_corrections(self):
        train(self.conn, "o-first", "overload")
        train(self.conn, "o-second", "overload")
        mistakes = audit(self.conn)["errors"]
        self.assertEqual([m["predicted"] for m in mistakes], ["observe", "reflect"])
        result = falsify(self.conn)
        predictions = [p["action"] for p in result["feedback_arm"]["sequential_new_synthetic_receipts"]]
        self.assertEqual(predictions, ["observe", "reflect", "rest"])
        self.assertEqual(result["feedback_arm"]["predicted_after"], "rest")

    def test_chronology_uses_rowid_not_lexical_event_name(self):
        train(self.conn, "z-first", "overload")
        train(self.conn, "a-second", "overload")
        self.assertEqual([m["event_id"] for m in audit(self.conn)["errors"]],
                         ["z-first", "a-second"])

    def test_correct_predictions_not_mislabeled_errors(self):
        train(self.conn, "d-001", "distraction")
        self.assertEqual(audit(self.conn)["errors_found"], 0)

    def test_historical_mistake_remains_visible_after_learning(self):
        train(self.conn, "u-001", "uncertainty")
        train(self.conn, "u-002", "uncertainty")
        self.assertEqual(audit(self.conn)["episodes_checked"], 2)
        self.assertEqual(audit(self.conn)["errors_found"], 1)

    def test_corrupt_receipt_refuses_audit_and_probe(self):
        train(self.conn, "u-001", "uncertainty")
        self.conn.execute("UPDATE learning_episodes SET reward=1 WHERE event_id='u-001'")
        self.conn.commit()
        with self.assertRaises(ValueError):
            audit(self.conn)
        with self.assertRaises(ValueError):
            falsify(self.conn)

    def test_rehashed_but_unreplayable_prediction_is_rejected(self):
        train(self.conn, "u-001", "uncertainty")
        row = self.conn.execute("SELECT * FROM learning_episodes WHERE event_id='u-001'").fetchone()
        payload = _payload(row)
        payload["action"] = "rest"  # still wrong against reflect
        self.conn.execute(
            "UPDATE learning_episodes SET action=?,receipt_sha256=? WHERE event_id='u-001'",
            ("rest", _hash(payload)),
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "cannot be replayed"):
            audit(self.conn)

    def test_cold_restart_replays_same_falsification(self):
        train(self.conn, "u-001", "uncertainty")
        first = falsify(self.conn)
        self.conn.close()
        self.conn = connect(self.path)
        second = falsify(self.conn)
        self.assertEqual(first["plan_sha256"], second["plan_sha256"])
        self.assertEqual(first["verdict"], second["verdict"])

    def test_demo_is_deterministic_and_memory_only(self):
        x, y = demo(), demo()
        self.assertEqual(x["plan_sha256"], y["plan_sha256"])
        self.assertEqual(x["audit"]["errors_found"], 2)
        self.assertEqual(x["verdict"], "supported_in_predefined_synthetic_fixture")
        self.assertEqual(x["audit"]["schema"], SCHEMA)

    def test_cli_read_only_audit(self):
        train(self.conn, "u-001", "uncertainty")
        self.conn.close()
        cmd = [
            sys.executable, "-m",
            "examples.nasuraya_virtual_learning.self_falsification",
            "audit", "--db", str(self.path),
        ]
        cp = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(cp.stdout)["errors_found"], 1)
        self.conn = connect(self.path)
        self.assertEqual(status(self.conn)["episodes"], 1)

    def test_cli_rejects_missing_db_without_creation(self):
        unknown = Path(self.tmp.name) / "not-created.sqlite"
        cmd = [
            sys.executable, "-m",
            "examples.nasuraya_virtual_learning.self_falsification",
            "falsify", "--db", str(unknown),
        ]
        cp = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(cp.returncode, 0)
        self.assertFalse(unknown.exists())


if __name__ == "__main__":
    unittest.main()
