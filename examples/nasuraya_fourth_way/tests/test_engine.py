"""Offline three-center and SQLite contract tests; no native Tadash calls."""
from dataclasses import replace
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from examples.nasuraya_fourth_way import FourthWay, Ledger
from examples.nasuraya_fourth_way.__main__ import fixture


class ThreeCenterTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture()
        self.walk = next(a for a in self.case.actions if a.name == "walk")

    def changed_walk(self, **kwargs):
        item = replace(self.walk, **kwargs)
        return replace(self.case, actions=tuple(item if a.name == "walk" else a
                                                for a in self.case.actions))

    def get_walk(self, plan):
        return next(o for o in plan["options"] if o["action"] == "walk")

    def test_three_centers_have_distinct_reports(self):
        plan = FourthWay().decide(self.case)
        self.assertEqual(plan["selected_action"], "walk")
        self.assertEqual(plan["execution"], "none; advisory simulated decision only")
        row = self.get_walk(plan)
        self.assertTrue(row["eligible"])
        self.assertEqual(set(row["centers"]), {"thinking", "feeling", "moving"})
        self.assertTrue(0 <= row["harmony"] <= 1)
        self.assertTrue(0 <= row["integration_index"] <= 1)
        self.assertEqual(plan["self_remembering"]["intention"], self.case.purpose)

    def test_unknown_or_denied_protection_vetoes(self):
        for protection in ("unknown", "deny"):
            with self.subTest(protection=protection):
                plan = FourthWay().decide(self.changed_walk(protection=protection))
                self.assertEqual(plan["selected_action"], "observe")
                self.assertIn("protection_not_cleared", self.get_walk(plan)["veto"])

    def test_high_risk_veto_survives_high_reward(self):
        plan = FourthWay().decide(self.changed_walk(risk=.95))
        self.assertEqual(plan["selected_action"], "observe")
        self.assertIn("modeled_risk_too_high", self.get_walk(plan)["veto"])

    def test_energy_and_stability_veto(self):
        for field, value, expected in (
            ("energy", .2, "insufficient_modeled_energy"),
            ("stability", .2, "insufficient_modeled_stability"),
        ):
            with self.subTest(field=field):
                plan = FourthWay().decide(replace(self.case, **{field: value}))
                self.assertEqual(plan["selected_action"], "observe")
                self.assertIn(expected, self.get_walk(plan)["veto"])

    def test_low_evidence_veto(self):
        plan = FourthWay().decide(self.changed_walk(evidence=.1))
        self.assertEqual(plan["selected_action"], "observe")
        self.assertIn("evidence_too_weak_for_action", self.get_walk(plan)["veto"])

    def test_value_conflict_veto(self):
        plan = FourthWay().decide(self.changed_walk(values=.1))
        self.assertEqual(plan["selected_action"], "observe")
        self.assertIn("value_conflict", self.get_walk(plan)["veto"])

    def test_feeling_can_change_choice_without_veto(self):
        plan = FourthWay().decide(self.changed_walk(values=.41, care=.1, affective_load=1))
        self.assertTrue(self.get_walk(plan)["eligible"])
        self.assertEqual(plan["selected_action"], "observe")

    def test_higher_arousal_increases_affective_load_penalty(self):
        low = FourthWay().decide(replace(self.case, arousal=0))
        high = FourthWay().decide(replace(self.case, arousal=1))
        self.assertLess(self.get_walk(high)["centers"]["feeling"]["score"],
                        self.get_walk(low)["centers"]["feeling"]["score"])

    def test_decision_is_order_invariant(self):
        plan1 = FourthWay().decide(self.case)
        plan2 = FourthWay().decide(replace(self.case, actions=tuple(reversed(self.case.actions))))
        self.assertEqual(plan1["selected_action"], plan2["selected_action"])

    def test_all_vetoed_means_abstention(self):
        case = replace(self.case, actions=(replace(self.walk, protection="unknown"),))
        plan = FourthWay().decide(case)
        self.assertIsNone(plan["selected_action"])
        self.assertEqual(plan["reason"], "abstain_all_vetoed")

    def test_new_actions_fail_closed_without_clearance(self):
        case = replace(self.case, actions=(replace(self.walk,
                    name="unknown_effect", protection="unknown"),))
        self.assertIsNone(FourthWay().decide(case)["selected_action"])

    def test_invalid_numbers_labels_and_duplicate_actions(self):
        for bad in (float("nan"), float("inf"), -1, 2, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                replace(self.walk, risk=bad)
        with self.assertRaises(ValueError):
            replace(self.walk, protection="maybe")
        with self.assertRaises(ValueError):
            replace(self.case, actions=(self.walk, self.walk))


class LedgerTests(unittest.TestCase):
    def test_persistent_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fourth-way.sqlite"
            case = fixture()
            with Ledger(path) as ledger:
                plan = ledger.decide(case)
                self.assertEqual(plan, ledger.decide(case))
                report = ledger.feedback(case.event_id, actual_goal_progress=.80,
                                         witness_ref="synthetic://test-v01")
                self.assertAlmostEqual(report["prediction_error"], -.15)
                self.assertFalse(report["policy_changed"])
                self.assertEqual(report, ledger.feedback(case.event_id,
                    actual_goal_progress=.80, witness_ref="synthetic://test-v01"))
                self.assertEqual(ledger.status()["native_actions"], 0)
            with Ledger(path) as ledger:
                self.assertEqual(ledger.status()["decisions"], 1)
                self.assertEqual(ledger.status()["feedback"], 1)
                self.assertEqual(ledger.decide(case), plan)

    def test_conflicting_event_replay_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, Ledger(Path(tmp) / "f.sqlite") as db:
            case = fixture()
            db.decide(case)
            with self.assertRaisesRegex(ValueError, "conflicting decision"):
                db.decide(replace(case, purpose="different"))

    def test_conflicting_feedback_replay_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, Ledger(Path(tmp) / "f.sqlite") as db:
            case = fixture()
            db.decide(case)
            db.feedback(case.event_id, actual_goal_progress=.8, witness_ref="synthetic://a")
            with self.assertRaisesRegex(ValueError, "conflicting feedback"):
                db.feedback(case.event_id, actual_goal_progress=.1, witness_ref="synthetic://a")

    def test_feedback_requires_known_decision_and_witness(self):
        with tempfile.TemporaryDirectory() as tmp, Ledger(Path(tmp) / "f.sqlite") as db:
            with self.assertRaises(ValueError):
                db.feedback("missing", actual_goal_progress=.5, witness_ref="synthetic://a")
            db.decide(fixture())
            with self.assertRaises(ValueError):
                db.feedback(fixture().event_id, actual_goal_progress=.5, witness_ref="")
            with self.assertRaises(ValueError):
                db.feedback(fixture().event_id, actual_goal_progress=.5,
                            witness_ref="synthetic://a", origin="verified_native")

    def test_feedback_not_allowed_after_abstention(self):
        with tempfile.TemporaryDirectory() as tmp, Ledger(Path(tmp) / "f.sqlite") as db:
            case = fixture()
            walk = next(a for a in case.actions if a.name == "walk")
            case = replace(case, actions=(replace(walk, protection="unknown"),))
            db.decide(case)
            with self.assertRaisesRegex(ValueError, "abstained"):
                db.feedback(case.event_id, actual_goal_progress=.5, witness_ref="synthetic://a")

    def test_offline_cli_is_finite_and_no_native_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.sqlite"
            result = subprocess.run([sys.executable, "-m", "examples.nasuraya_fourth_way",
                "demo", "--db", str(path)], capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["plan"]["selected_action"], "walk")
            self.assertEqual(report["ledger"]["native_actions"], 0)
            self.assertEqual(report["ledger"]["autonomous_cycles"], 0)


if __name__ == "__main__":
    unittest.main()
