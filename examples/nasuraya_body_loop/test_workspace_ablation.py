"""Adversarial and bounded checks for native 30-cycle workspace A/B experiment."""
import json
from pathlib import Path
import tempfile
import unittest

from . import workspace_ablation as experiment


class NativeWorkspaceAblationTests(unittest.TestCase):
    def test_all_thirty_native_cycles_are_real_and_paired(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new"
            report = experiment.run(output)
            self.assertEqual(report["schema"], experiment.SCHEMA)
            self.assertEqual(report["total_native_cycles"], 30)
            self.assertEqual(report["matched_preference_comparisons"], 15)
            self.assertEqual(report["fresh_native_software_sessions"], 10)
            self.assertEqual(report["sessions_cold_reopened"], 10)
            self.assertEqual(report["extra_cycles_on_idempotent_replay"], 0)
            self.assertEqual(report["baseline"]["native_cycles"], 15)
            self.assertEqual(report["workspace"]["native_cycles"], 15)
            self.assertEqual(report["baseline"]["recorded_workspace_receipts"], 0)
            self.assertEqual(report["workspace"]["recorded_workspace_receipts"], 15)
            self.assertEqual(len(report["pairs"]), 5)
            self.assertEqual([r["fixture"] for r in report["pairs"]],
                             list(experiment.FIXTURES))
            for pair in report["pairs"]:
                self.assertEqual(pair["baseline"]["fixture"],
                                 pair["workspace"]["fixture"])
                for arm in experiment.ARMS:
                    session = pair[arm]
                    self.assertTrue(session["cold_reopen_verified"])
                    self.assertEqual(session["replay_extra_cycles"], 0)
                    self.assertEqual(session["native_cycles"], 3)
                    self.assertEqual(len(session["steps"]), 3)
            self.assertEqual(report["api_calls"], 0)
            self.assertFalse(report["physical_actuation"])
            self.assertFalse(report["subjective_experience_inferred"])
            self.assertFalse(report["statistical_generalization_claim"])
            persisted = json.loads((output / "summary.json").read_text("utf-8"))
            self.assertEqual(report, persisted)

    def test_never_overwrites_a_previous_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing"
            output.mkdir()
            sentinel = output / "do-not-modify"
            sentinel.write_text("safe", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                experiment.run(output)
            self.assertEqual(sentinel.read_text("utf-8"), "safe")

    def test_predeclared_fixture_bounds(self):
        self.assertEqual(len(experiment.FIXTURES), 5)
        self.assertEqual(set(experiment.FIXTURES), {"normal", "sleep"})
        self.assertEqual(experiment.STEPS, 3)
        self.assertEqual(experiment.ARMS, ("baseline", "workspace"))


if __name__ == "__main__":
    unittest.main()
