"""Independent integrity and scope tests for the Windows read-only bridge probe."""
import json
import math
import subprocess
import sys
import unittest

from tools.bridge_jobs import worldmodel_probe as probe


class WorldModelProbeTests(unittest.TestCase):
    def test_bounded_rows_and_no_overlapping_evaluation(self):
        train = probe.simulate(probe.TRAIN_SEED, probe.TRAIN_SEQUENCES)
        test = probe.simulate(probe.HOLDOUT_SEED, probe.HOLDOUT_SEQUENCES)
        self.assertEqual((len(train), len(test)), (288, 96))
        self.assertTrue({x["id"] for x in train}.isdisjoint({x["id"] for x in test}))

    def test_deterministic_protocol(self):
        self.assertEqual(probe.benchmark(), probe.benchmark())

    def test_numeric_metrics_finite_and_bounded(self):
        r = probe.benchmark()
        self.assertTrue(math.isfinite(r["mae"]))
        self.assertTrue(0 <= r["mae"] <= 1)
        self.assertTrue(0 < r["persistence_baseline_mae"] <= 1)

    def test_no_claim_of_runtime_training_or_actuation(self):
        r = probe.benchmark()
        self.assertFalse(r["learning_applied_to_runtime"])
        self.assertEqual((r["native_cycles_caused"], r["physical_actuator_calls"], r["network_calls"]), (0, 0, 0))

    def test_finite_weights_and_holdout_immutable(self):
        train = probe.simulate(probe.TRAIN_SEED, probe.TRAIN_SEQUENCES)
        holdout = probe.simulate(probe.HOLDOUT_SEED, probe.HOLDOUT_SEQUENCES)
        w = probe.fit(train)
        old = tuple(w)
        [probe.predict(w, x["features"]) for x in holdout]
        self.assertEqual(w, old)

    def test_boundary_precedence(self):
        for fatigue in (0., 1.):
            self.assertEqual(probe.decide(boundary=True, pain=1., fatigue=fatigue, familial=True), "respect_boundary")

    def test_pain_and_fatigue_rest(self):
        for kwargs in ({"pain": .8, "fatigue": .1}, {"pain": .1, "fatigue": .9}):
            self.assertEqual(probe.decide(boundary=False, familial=False, **kwargs), "regulate_and_rest")

    def test_familial_is_nonsexual(self):
        self.assertEqual(probe.decide(boundary=False, pain=0., fatigue=0., familial=True), "nonsexual_affiliation")

    def test_bad_inputs_fail_closed(self):
        for bad in (float("nan"), float("inf"), -1., 1.1, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                probe.unit(bad)
        with self.assertRaises(ValueError):
            probe.decide(boundary=1, pain=0., fatigue=0., familial=False)

    def test_public_output_only_safe_aggregate(self):
        out = subprocess.check_output([sys.executable, "-I", "tools/bridge_jobs/worldmodel_probe.py"], text=True)
        result = json.loads(out)
        self.assertEqual(result["status"], "ok")
        summary = result["summary"]
        import re
        self.assertRegex(summary, r"^[A-Za-z0-9 .,:;=/_()+-]{1,180}$")
        self.assertTrue("WORLD=SYNTHETIC" in summary and "ACT=0" in summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
