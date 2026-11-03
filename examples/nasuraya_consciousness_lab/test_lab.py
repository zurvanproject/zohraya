"""Offline regression checks for a toy indicator workbench; NEVER call paid API."""
from copy import deepcopy
import unittest

from . import indicators as i, mechanisms as m, probes


class RegistryTests(unittest.TestCase):
    def test_exact_paper_families_and_total(self):
        self.assertEqual(len(i.INDICATORS), 14)
        self.assertEqual(len(set(i.BY_CODE)), 14)
        self.assertEqual({theory: sum(s.theory == theory for s in i.INDICATORS)
                          for theory in i.THEORIES},
                         {"RPT": 2, "GWT": 4, "HOT": 4, "AST": 1, "PP": 1, "AE": 2})

    def test_no_status_claim_without_evidence(self):
        report = i.audit()
        self.assertEqual(report["overall_consciousness_verdict"], None)
        self.assertTrue(all(row["toy_status"] == "not_tested" and
                            row["deployed_tadash_status"] == "not_assessed"
                            for row in report["indicators"]))
        self.assertEqual(report["paid_api_calls"], 0)

    def test_all_14_toy_ablation_probes_pass_but_never_certify_deployment(self):
        receipts = probes.probes()
        self.assertEqual(set(receipts), set(i.BY_CODE))
        report = i.audit(receipts)
        self.assertTrue(all(r["toy_status"] == "probe_passed" for r in report["indicators"]))
        self.assertTrue(all(r["deployed_tadash_status"] == "not_assessed"
                            for r in report["indicators"]))
        self.assertIsNone(report["overall_consciousness_verdict"])
        self.assertEqual(report["paid_api_calls"], 0)

    def test_failed_or_missing_probes_not_counted_as_success(self):
        receipts = probes.probes()
        receipts["AE-2"]["probe_passed"] = False
        del receipts["HOT-1"]
        rows = {r["code"]: r for r in i.audit(receipts)["indicators"]}
        self.assertEqual(rows["AE-2"]["toy_status"], "probe_failed")
        self.assertEqual(rows["HOT-1"]["toy_status"], "not_tested")

    def test_source_and_scope_must_be_explicit(self):
        with self.assertRaises(ValueError):
            i.audit({"FAKE-100": {"probe_passed": True, "source": "fiction",
                                  "scope": "isolated_toy_prototype"}})
        with self.assertRaises(ValueError):
            i.audit({"HOT-3": {"probe_passed": True, "source": "fiction",
                               "scope": "production_proven"}})
        with self.assertRaises(ValueError):
            i.audit({"HOT-3": {"probe_passed": 1, "source": "fiction",
                               "scope": "isolated_toy_prototype"}})

    def test_receipts_are_not_mutated(self):
        receipts = probes.probes()
        old = deepcopy(receipts)
        i.audit(receipts)
        self.assertEqual(receipts, old)


class MechanismTests(unittest.TestCase):
    def test_each_indicator_has_a_passing_explicit_causal_probe(self):
        for code, receipt in probes.probes().items():
            with self.subTest(code=code):
                self.assertTrue(receipt["probe_passed"])

    def test_cycle_is_finite_and_in_memory(self):
        cycle = m.PrototypeCycle()
        first = cycle.step(visual=0.6, audio=0.7, danger=0.1, goal=0.7,
                           noise=0.1, sensory=0.8)
        second = cycle.step(visual=0.6, audio=0.7, danger=0.9, goal=0.7,
                            noise=5, sensory=0.8)
        self.assertEqual(set(first["inboxes"]), {"perception", "memory", "planning"})
        self.assertNotEqual(first["query_plan"], second["query_plan"])
        self.assertNotEqual(first["reliability"], second["reliability"])
        self.assertNotEqual(first["prediction_error"], second["prediction_error"])
        self.assertEqual(len(first["quality_code"]), 5)
        self.assertEqual(first["interpretation"],
                         "Isolated computational prototype; no consciousness inference")

    def test_recurrent_and_predictive_controls_fail_closed_on_nonfinite_numbers(self):
        for bad in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.subTest(bad=str(bad)), self.assertRaises(ValueError):
                m.RecurrentBinder().observe(bad, 0.5)
        with self.assertRaises(ValueError):
            m.PredictiveCoder().step(float("nan"))
        with self.assertRaises(ValueError):
            m.GoalLearner().feedback("observe", True)
        with self.assertRaises(ValueError):
            m.SensorimotorModel().learn("left", 0, float("inf"))

    def test_workspace_capacity_and_selection_are_bounded(self):
        with self.assertRaises(ValueError):
            m.Workspace(capacity=0)
        with self.assertRaises(ValueError):
            m.Workspace(capacity=99)
        w = m.Workspace(capacity=1)
        self.assertEqual(len(w.publish({"a": 0.4, "b": 0.9})), 1)

    def test_quality_space_nonnegative_continuous_and_sparse(self):
        for j in range(1001):
            code = m.quality_code(j / 1000)
            self.assertTrue(all(0 <= x <= 1 for x in code))
            self.assertAlmostEqual(sum(code), 1)
            self.assertLessEqual(sum(x > 0 for x in code), 2)


if __name__ == "__main__":
    unittest.main()
