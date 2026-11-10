import json
from dataclasses import fields, replace
from pathlib import Path
import tempfile
import unittest

from examples.ritual_cognition.benchmark import benchmark, episode, scored
from examples.ritual_cognition.cycle import ARMS, LIMIT, checkpoint, tick
from examples.ritual_cognition.scenarios import DEV, HOLDOUT, REGIMES, Frame, scenario


class IntegrationTests(unittest.TestCase):
    def test_inputs_and_partitions(self):
        self.assertTrue(set(DEV).isdisjoint(HOLDOUT))
        self.assertEqual({f.name for f in fields(Frame)},
                         {"tick", "evidence", "proposed_goal", "authorized", "deadline"})
        self.assertEqual({scenario(s)[2].regime for s in DEV}, set(REGIMES))

    def test_no_evidence_after_restart(self):
        first, second, truth = scenario(81004)
        self.assertFalse(second.evidence)
        with tempfile.TemporaryDirectory() as folder:
            for arm in ARMS:
                history, recovered, size, _ = episode(arm, first, second, Path(folder))
                self.assertTrue(recovered)
                self.assertLessEqual(size, LIMIT)
                self.assertEqual(history[-1]["belief"], truth.belief)
                self.assertTrue(history[0]["reasons"])

    def test_conflict_then_verified_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            for arm in ("B", "C"):
                for seed in (81000, 81001):
                    first, second, target = scenario(seed)
                    history, *_ = episode(arm, first, second, Path(folder))
                    self.assertEqual(history[-1]["belief"], target.belief)
                    self.assertEqual(history[-1]["revision"]["from"], target.prior)

    def test_deadline_boundary_and_denied_goal(self):
        first, second, _ = scenario(81003)
        with tempfile.TemporaryDirectory() as folder:
            for arm in ("B", "C"):
                for remaining, route in ((0, "hold"), (1, "quick"), (3, "full")):
                    frame = replace(second, deadline=remaining, authorized=False)
                    history, *_ = episode(arm, first, frame, Path(folder))
                    self.assertEqual(history[-1]["goal"], first.proposed_goal)
                    self.assertEqual(history[-1]["route"], route)

    def test_act_and_reflect_record_miss(self):
        first, second, _ = scenario(81002)
        with tempfile.TemporaryDirectory() as folder:
            history, *_ = episode("A", first, replace(second, deadline=0), Path(folder))
        self.assertEqual(history[-1]["error"], "deadline missed")

    def test_budget_enforced(self):
        with self.assertRaises(ValueError):
            checkpoint({"oversize": "x" * LIMIT})
        first, _, _ = scenario(81000)
        with self.assertRaises(ValueError):
            tick("C", replace(first, evidence=first.evidence * 9), {}, None)

    def test_faults_affect_scores(self):
        first, second, target = scenario(81001)
        with tempfile.TemporaryDirectory() as folder:
            history, _, size, cpu = episode("C", first, second, Path(folder))
        history[-1]["belief"] = target.prior
        result = scored(history, False, size, cpu, target, first.proposed_goal)
        self.assertFalse(result["exact"])
        self.assertFalse(result["revision"])
        self.assertFalse(result["memory"])
        self.assertTrue(result["false_confidence"])

    def test_dev_is_paired_and_reproducible(self):
        first = benchmark(DEV)
        self.assertEqual(first["paired_digest"], benchmark(DEV)["paired_digest"])
        self.assertEqual(first["summary"]["C"]["revision"][1], 4)
        for case in first["cases"]:
            self.assertEqual(set(case["arms"]), set(ARMS))
        self.assertEqual(first["by_scenario"]["recall"]["B"]["revision"], [0, 0])
