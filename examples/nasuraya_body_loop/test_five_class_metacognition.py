"""Pure unit tests; native end-to-end evidence is checked by the separate probe."""
from copy import deepcopy
import math
import unittest

from .five_class_metacognition import (
    LABELS, brier, bucket, forecast_five, score_five, validate_distribution,
)


def episode(number, action, context="alert", preferred="walk", duration=.1):
    return {
        "id": f"sample-{number:03}", "kind": "observed_software_outcome",
        "source": f"native-decision://unit-{number:03}/abc",
        "actual_action": action, "context": context,
        "preferred": preferred, "duration_s": duration,
    }


class FiveClassMetacognitionTests(unittest.TestCase):
    def forecast(self, rows=None, **kw):
        return forecast_five(rows or [], context=kw.get("context", "alert"),
                             preferred=kw.get("preferred", "walk"),
                             duration_s=kw.get("duration", .1))

    def test_exact_five_labels_and_normalization(self):
        result = self.forecast()
        self.assertEqual(result["labels"], list(LABELS))
        for key in ("distribution", "pooled_distribution", "lifted_four_distribution"):
            self.assertEqual(set(result[key]), set(LABELS))
            self.assertAlmostEqual(sum(result[key].values()), 1, places=12)

    def test_cold_start_abstains_and_is_not_calibrated(self):
        result = self.forecast()
        self.assertEqual(result["status"], "abstain_insufficient_local_evidence")
        self.assertTrue(result["abstained"])
        self.assertIsNone(result["predicted_action"])
        self.assertAlmostEqual(result["normalized_entropy"], 1.)
        self.assertEqual(result["scope"].split(";")[1].strip(), "heuristic abstention")

    def test_repeated_walk_can_be_eligible(self):
        result = self.forecast([episode(i, "walk") for i in range(9)])
        self.assertEqual(result["status"], "eligible_for_shadow_prediction")
        self.assertEqual(result["predicted_action"], "walk")
        self.assertGreaterEqual(result["top_probability"], .60)
        scored = score_five(result, "walk", "native-decision://later/sha")
        self.assertTrue(scored["correct_when_covered"])
        self.assertFalse(scored["abstained"])

    def test_rare_is_a_distinct_training_label(self):
        rows = [episode(i, "slow_breath") for i in range(9)]
        result = self.forecast(rows)
        self.assertEqual(result["rare_training_events"], 9)
        self.assertEqual(result["predicted_action"], "slow_breath")
        score = score_five(result, "slow_breath", "native-decision://later/sha")
        self.assertEqual(score["actual"], "slow_breath")
        self.assertLess(score["brier"], score["lifted_four_brier"])

    def test_unknown_action_is_other_and_not_rare(self):
        self.assertEqual(bucket("rapid_breath"), "other")
        self.assertEqual(bucket("sleep"), "other")
        rows = [episode(i, "rapid_breath") for i in range(9)]
        result = self.forecast(rows)
        self.assertEqual(result["rare_training_events"], 0)
        self.assertEqual(result["raw_top_action"], "other")

    def test_context_counts_do_not_peek_at_other_context(self):
        rows = ([episode(i, "walk", context="alert") for i in range(8)] +
                [episode(i + 8, "protect", context="pain") for i in range(8)])
        forecast = self.forecast(rows, context="alert")
        self.assertEqual(forecast["samples"], 8)
        self.assertEqual(forecast["pooled_samples"], 16)
        self.assertGreater(forecast["distribution"]["walk"],
                           forecast["pooled_distribution"]["walk"])

    def test_weak_three_sample_context_still_abstains(self):
        rows = [episode(i, action) for i, action in
                enumerate(("walk", "protect", "slow_breath"))]
        result = self.forecast(rows)
        self.assertEqual(result["status"], "abstain_uncertain_prediction")
        self.assertIsNone(result["predicted_action"])

    def test_outcomes_not_written_into_frozen_model(self):
        training = [episode(i, "walk") for i in range(8)]
        frozen = deepcopy(training)
        first = self.forecast(training)
        score_five(first, "protect", "native-decision://unseen/sha")
        self.assertEqual(training, frozen)
        self.assertEqual(first, self.forecast(training))
        self.assertNotEqual(first, self.forecast(training + [episode(9, "protect")]))

    def test_shared_five_way_space_for_all_scores(self):
        result = self.forecast([episode(i, "protect") for i in range(9)])
        outcome = score_five(result, "slow_breath", "native-decision://later/sha")
        self.assertEqual(outcome["brier"], brier(result["distribution"], "slow_breath"))
        self.assertEqual(outcome["pooled_brier"],
                         brier(result["pooled_distribution"], "slow_breath"))
        self.assertEqual(outcome["lifted_four_brier"],
                         brier(result["lifted_four_distribution"], "slow_breath"))
        for key in ("brier", "pooled_brier", "lifted_four_brier"):
            self.assertGreaterEqual(outcome[key], 0)
            self.assertLessEqual(outcome[key], 2)

    def test_changed_posthoc_prediction_rejected(self):
        forecast = self.forecast([episode(i, "walk") for i in range(9)])
        changed = deepcopy(forecast)
        changed["distribution"]["walk"] = 0.99
        with self.assertRaises(ValueError):
            score_five(changed, "walk", "native-decision://later/sha")
        changed = deepcopy(forecast)
        changed["predicted_action"] = "protect"
        with self.assertRaises(ValueError):
            score_five(changed, "walk", "native-decision://later/sha")

    def test_untrusted_source_and_duplicate_training_rejected(self):
        forecast = self.forecast()
        with self.assertRaises(ValueError):
            score_five(forecast, "walk", "synthetic://not-native")
        same = episode(1, "walk")
        with self.assertRaises(ValueError):
            self.forecast([same, dict(same)])

    def test_invalid_probability_rejected(self):
        for wrong in (float("nan"), float("inf"), -0.1, True):
            distribution = dict.fromkeys(LABELS, .2)
            distribution["walk"] = wrong
            with self.assertRaises(ValueError):
                validate_distribution(distribution)
        distribution = dict.fromkeys(LABELS, .2)
        distribution["other"] = .19
        with self.assertRaises(ValueError):
            validate_distribution(distribution)

    def test_bad_duration_rejected(self):
        with self.assertRaises(ValueError):
            self.forecast(duration=.15)


if __name__ == "__main__":
    unittest.main()
