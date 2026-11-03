"""Pure offline tests; no source-pinned runtime or paid API required.

The separate CI native-shadow-eval step exercises the actual verified
BodyLoop fixture in its original isolated worker.
"""
from copy import deepcopy
import math
import unittest

from . import native_shadow as bridge
from .mechanisms import PrototypeCycle


class NativeShadowPureTests(unittest.TestCase):
    def test_protocol_is_fixed_and_has_no_command_authority(self):
        p = bridge.PROTOCOL
        self.assertEqual(len(p["fixtures"]) * len(p["preferences"]) *
                         len(p["durations_s"]), 8)
        self.assertEqual(8 * (p["train_rounds"] + p["holdout_rounds"]), 64)
        self.assertEqual(p["observer_permissions"],
                         "read_only_after_observe; no motor policy output")
        self.assertEqual(set(bridge.CONDITIONS), {"intact","ablated","corrupted"})

    def test_matched_real_signal_shadow_ablations_change_internal_traces(self):
        signals = {
            "visual_proxy_energy": 0.7,
            "audio_proxy_inv_fatigue": 0.8,
            "danger_proxy": 0.8,
            "goal_proxy_inv_fatigue": 0.9,
            "noise_proxy": 0.1,
            "sensory_proxy_sleep_pressure": 0.6,
        }
        a = bridge.shadow_observe(bridge._new_prototype("intact"), signals)
        b = bridge.shadow_observe(bridge._new_prototype("ablated"), signals)
        c = bridge.shadow_observe(bridge._new_prototype("corrupted"),
                                  signals, corrupted=True)
        self.assertTrue(any(a["broadcast_inboxes"].values()))
        self.assertTrue(all(not values for values in b["broadcast_inboxes"].values()))
        self.assertNotEqual(a["query_plan"], c["query_plan"])
        self.assertEqual(signals["danger_proxy"], 0.8)
        self.assertEqual(a["scope"],
                         "read-only toy mechanism trace on native synthetic-body proxies")

    def test_shadow_does_not_modify_input(self):
        data = {
            "visual_proxy_energy": .4, "audio_proxy_inv_fatigue": .4,
            "danger_proxy": .4, "goal_proxy_inv_fatigue": .5,
            "noise_proxy": .1, "sensory_proxy_sleep_pressure": .5,
        }
        old = deepcopy(data)
        bridge.shadow_observe(PrototypeCycle(), data)
        self.assertEqual(data, old)

    def test_probabilities_cannot_be_nan_bool_negative_or_unbalanced(self):
        cases = [
            {"walk": 0.5, "observe": 0.5, "protect": 0, "other": 0},
            {"walk": 1, "observe": 0, "protect": 0, "other": 0},
        ]
        for ok in cases:
            self.assertGreaterEqual(bridge.score(ok, "walk"), 0)
        for invalid in (
            {"walk": float("nan"), "observe": 0, "protect": 0, "other": 0},
            {"walk": True, "observe": 0, "protect": 0, "other": 0},
            {"walk": -.1, "observe": 1.1, "protect": 0, "other": 0},
            {"walk": .1, "observe": .1, "protect": .1, "other": .1},
            {"walk": 1.0},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                bridge.score(invalid, "walk")

    def test_three_condition_grading_on_matched_outcome(self):
        a = {"walk": .75, "observe": .10, "protect": .10, "other": .05}
        b = {"walk": .25, "observe": .25, "protect": .25, "other": .25}
        c = {"walk": .10, "observe": .75, "protect": .10, "other": .05}
        rows = [{"pre": {"forecasts": {"intact": a, "ablated": b, "corrupted": c}},
                 "actual_action": "walk"}] * 4
        report = bridge.grade(rows)
        self.assertLess(report["intact"]["mean_brier"], report["ablated"]["mean_brier"])
        self.assertLess(report["ablated"]["mean_brier"], report["corrupted"]["mean_brier"])
        self.assertEqual(report["intact"]["top_action_accuracy"], 1.0)
        self.assertEqual(report["corrupted"]["top_action_accuracy"], 0.0)

    def test_empty_grade_never_claims_success(self):
        with self.assertRaises(ValueError):
            bridge.grade([])

    def test_unrecognized_body_snapshot_proxy_never_silently_accepted(self):
        with self.assertRaises(ValueError):
            bridge.shadow_observe(PrototypeCycle(),
                                  {"visual_proxy_energy": .7})

    def test_artifact_hash_reproducible(self):
        a = {"a": 1, "b": [1, 2]}
        self.assertEqual(bridge.digest(a), bridge.digest({"b": [1, 2], "a": 1}))
        self.assertNotEqual(bridge.digest(a), bridge.digest({"a": 1, "b": [2, 1]}))


if __name__ == "__main__":
    unittest.main()
