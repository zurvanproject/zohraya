"""Behavioral and leakage checks for the finite forecast guard."""
import ast
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
from tools.bridge_jobs import forecast_guard_probe as guard

JOB = Path(__file__).resolve().parents[1] / "tools" / "bridge_jobs" / "forecast_guard_probe.py"


def rows(features, targets, prefix="v"):
    return [{"id": f"{prefix}-{i}", "features": (1.0, x, 0.0, 0.0, 0.0), "observed_next": y}
            for i, (x, y) in enumerate(zip(features, targets))]


class GuardTests(unittest.TestCase):
    def test_calibration_rejects_bad_model(self):
        gate = guard.calibrate((0.0,) * 5, rows([0.2, 0.8], [0.21, 0.79]))
        self.assertFalse(gate.use_model)
        self.assertEqual(gate.forecast((1.0, 0.65, 0.4, 0.0, 0.0)), 0.65)

    def test_calibration_accepts_independently_better_model(self):
        gate = guard.calibrate((0.5, 0.0, 0.0, 0.0, 0.0), rows([0.1, 0.9], [0.5, 0.5]))
        self.assertTrue(gate.use_model)
        self.assertEqual(gate.forecast((1.0, 0.7, 0.3, 0.0, 0.0)), 0.5)

    def test_zero_baseline_error_stays_with_baseline(self):
        self.assertFalse(guard.calibrate((0.0, 1.0, 0.0, 0.0, 0.0),
                                         rows([0.2, 0.8], [0.2, 0.8])).use_model)

    def test_gate_is_immutable(self):
        gate = guard.calibrate((0.0,) * 5, rows([0.2], [0.21]))
        with self.assertRaises(FrozenInstanceError):
            gate.use_model = True

    def test_rejects_invalid_external_values(self):
        for bad in (True, float("nan"), float("inf"), -0.1, 1.1, "0.5"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    guard.calibrate((0.0,) * 5, rows([bad], [0.5]))
                with self.assertRaises(ValueError):
                    guard.calibrate((0.0,) * 5, rows([0.5], [bad]))
        with self.assertRaises(ValueError):
            guard.calibrate((float("nan"),) * 5, rows([0.5], [0.5]))
        with self.assertRaises(ValueError):
            guard.calibrate((0.0,) * 5, [])

    def test_overlap_and_duplicate_ids_rejected(self):
        sample = rows([0.2], [0.3])
        with self.assertRaises(ValueError):
            guard.require_disjoint(sample, sample)
        with self.assertRaises(ValueError):
            guard.require_disjoint(sample * 2)
        with self.assertRaises(ValueError):
            guard.calibrate((0.0,) * 5, sample * 2)

    def test_all_predictions_precede_test_target_reads(self):
        gate = guard.calibrate((0.5, 0.0, 0.0, 0.0, 0.0), rows([0.1, 0.9], [0.5, 0.5]))
        seen = []
        class SealedRow(dict):
            def __getitem__(self, name):
                if name == "observed_next":
                    self_test.assertEqual(len(seen), 3)
                return super().__getitem__(name)
        self_test = self
        sample = [SealedRow(r) for r in rows([0.2, 0.4, 0.8], [0.3, 0.5, 0.7], "t")]
        original = guard.FrozenGate.forecast
        def record(instance, features):
            seen.append(features)
            return original(instance, features)
        with patch.object(guard.FrozenGate, "forecast", record):
            guard.score(gate, sample)

    def test_test_label_changes_cannot_adapt_gate(self):
        gate = guard.calibrate((0.5, 0.0, 0.0, 0.0, 0.0), rows([0.1, 0.9], [0.5, 0.5]))
        before = (gate.weights, gate.use_model, gate.validation_gain)
        a = guard.score(gate, rows([0.2, 0.4], [0.5, 0.5], "a"))
        b = guard.score(gate, rows([0.2, 0.4], [0.0, 1.0], "b"))
        self.assertNotEqual(a["guarded_mae"], b["guarded_mae"])
        self.assertEqual(before, (gate.weights, gate.use_model, gate.validation_gain))

    def test_protocol_partitions_and_counts(self):
        report = guard.benchmark()
        self.assertEqual(report["test_rows"], 3456)
        self.assertEqual(len(report["records"]), 36)
        seeds = []
        for r in report["records"]:
            seeds.extend((r["validation_seed"], r["test_seed"]))
        self.assertEqual(len(seeds), len(set(seeds)))
        training_seeds = {r["train_seed"] for r in report["records"]}
        self.assertTrue(training_seeds.isdisjoint(seeds))
        self.assertFalse(report["learning_applied_to_live_runtime"])
        self.assertEqual(report["actuator_calls"], 0)

    def test_repeatable_and_bridge_whitelisted(self):
        one, two = guard.benchmark(), guard.benchmark()
        self.assertEqual(one, two)
        summary = guard.bridge_summary(one)
        self.assertRegex(summary, r"\A[a-zA-Z0-9 .,:;=/_()+-]{1,180}\Z")
        for word in ("token", "password", "secret", "github_pat", "bearer"):
            self.assertNotIn(word, summary.lower())

    def test_isolated_standalone_entry_point(self):
        done = subprocess.run([sys.executable, "-I", str(JOB)], capture_output=True, text=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["summary"].startswith("GUARD=SYNTH;"))
        self.assertLess(len(JOB.read_bytes()), 24000)

    def test_source_has_no_external_io(self):
        tree = ast.parse(JOB.read_text(encoding="utf-8"))
        allowed = {"dataclasses", "hashlib", "math", "random", "json"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(n.name in allowed for n in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "__import__", "input"})


if __name__ == "__main__":
    unittest.main()

