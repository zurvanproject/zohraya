"""Offline contract tests: no native runtime, no model or network required."""
from copy import deepcopy
import math
import unittest

from experiments.tadash_first_tick_ablation import EXPECTED, PLAN, summarize
from experiments.tadash_four_tracks.core import digest


def fixture():
    before = {"arousal": .282, "pain": .1, "fatigue": .1,
              "energy": .8, "hydration": .8}
    cells = []
    for context, action, route in sorted(EXPECTED):
        first = dict(before)
        first.update(
            arousal=.330 if route == "enabled" else .282,
            sympathetic=.20, parasympathetic=.60,
            emotion="curiosity" if route == "enabled" else "neutral",
            emotion_intensity=.20 if route == "enabled" else .0)
        second = dict(first)
        second["arousal"] = .329 if route == "enabled" else .283
        cells.append({
            "context": context, "requested": action, "route": route,
            "synthetic": True,
            "initial_checkpoint_sha256": digest({"context": context}),
            "initial": deepcopy(before),
            "readouts": [first, second],
            "executed": [action, action],
            "native_audits": [{"energy_error_J": 1e-10,
                               "water_error_L": 1e-12,
                               "neural_clock_error_s": 1e-12}]*2,
        })
    return cells


class AblationContract(unittest.TestCase):
    def test_exact_eight_cells_and_four_comparisons(self):
        report = summarize(fixture())
        self.assertEqual(report["cells"], 8)
        self.assertEqual(report["intervention_native_ticks"], 16)
        self.assertEqual(len(report["comparisons"]), 4)
        self.assertAlmostEqual(report["comparisons"][0]["first_tick_route_delta"], .048)
        self.assertFalse(report["human_physiology_claim"])

    def test_negative_result_is_preserved(self):
        rows = fixture()
        for row in rows:
            row["readouts"][0]["arousal"] = .282
            row["readouts"][1]["arousal"] = .282
        r = summarize(rows)
        self.assertTrue(all(x["first_tick_route_delta"] == 0 for x in r["comparisons"]))
        self.assertEqual(r["interpretation_status"], "admissible_software_ablation")

    def test_native_veto_does_not_claim_success(self):
        rows = fixture()
        rows[0]["executed"][0] = "protect"
        self.assertEqual(summarize(rows)["interpretation_status"],
                         "inconclusive_native_action_veto")

    def test_missing_cell_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize(fixture()[:-1])

    def test_duplicate_cell_is_rejected(self):
        rows = fixture()
        rows[1] = deepcopy(rows[0])
        with self.assertRaises(ValueError):
            summarize(rows)

    def test_mismatched_full_checkpoint_is_rejected(self):
        rows = fixture()
        rows[0]["initial_checkpoint_sha256"] = "a"*64
        with self.assertRaises(ValueError):
            summarize(rows)

    def test_nonfinite_arousal_is_rejected(self):
        rows = fixture()
        rows[0]["readouts"][0]["arousal"] = math.nan
        with self.assertRaises(ValueError):
            summarize(rows)

    def test_missing_conservation_evidence_is_rejected(self):
        rows = fixture()
        rows[0]["native_audits"] = []
        with self.assertRaises(ValueError):
            summarize(rows)


if __name__ == "__main__":
    unittest.main()
