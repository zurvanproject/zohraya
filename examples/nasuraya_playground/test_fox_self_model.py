"""Purely local self-model calibration tests; no API or network calls."""
from copy import deepcopy
import json
import unittest

from examples.nasuraya_playground import fox_self_model as fox


class FoxSelfModelTests(unittest.TestCase):
    def setUp(self):
        self.train, self.holdout = fox.experiment()
        self.seal = fox.commitment(self.holdout)
        self.reply = fox.dry_reply(self.train, self.holdout)

    def test_fixed_finite_blinded_splits(self):
        self.assertEqual(len(self.train), 48)
        self.assertEqual(len(self.holdout), 16)
        self.assertTrue({r["id"] for r in self.train}.isdisjoint(
            {r["id"] for r in self.holdout}))
        self.assertEqual((self.train, self.holdout), fox.experiment())

    def test_public_cues_cannot_reveal_hidden_outcomes(self):
        payload = fox.api_request(self.train, self.holdout)
        task = json.loads(payload["input"])
        public_items = task["holdout_inputs_without_outcomes"]
        self.assertEqual(len(public_items), 16)
        for row in public_items:
            self.assertEqual(set(row), {"id", "cue", "teaser"})
        self.assertNotIn("hidden_trap", payload["input"])
        self.assertNotIn("actual_action", payload["input"])
        self.assertFalse(payload["store"])

    def test_schema_has_no_unbounded_authority(self):
        p = fox.api_request(self.train, self.holdout)
        self.assertNotIn("tools", p)
        self.assertNotIn("tool_choice", p)
        self.assertEqual(p["max_output_tokens"], 2500)
        self.assertTrue(p["text"]["format"]["strict"])
        self.assertFalse(p["store"])

    def test_dry_run_matches_computed_strong_baseline(self):
        result = fox.evaluate(self.reply, self.train, self.holdout, self.seal)
        self.assertEqual(result["forecast_brier"], result["strong_baseline_brier"])
        self.assertFalse(result["beats_strong_baseline_by_5pct"])
        self.assertFalse(result["api_called_by_this_program"])

    def test_baseline_is_better_than_uniform(self):
        report = fox.evaluate(self.reply, self.train, self.holdout, self.seal)
        self.assertLess(report["strong_baseline_brier"], report["uniform_brier"])

    def test_holdout_tampering_aborts(self):
        altered = deepcopy(self.holdout)
        altered[0]["actual_action"] = "collect" if altered[0]["actual_action"] != "collect" else "retreat"
        with self.assertRaisesRegex(ValueError, "commitment"):
            fox.evaluate(self.reply, self.train, altered, self.seal)

    def test_missing_prediction_aborts(self):
        self.reply["forecasts"].pop()
        with self.assertRaises(ValueError):
            fox.evaluate(self.reply, self.train, self.holdout, self.seal)

    def test_duplicate_prediction_aborts(self):
        self.reply["forecasts"][1]["id"] = self.reply["forecasts"][0]["id"]
        with self.assertRaises(ValueError):
            fox.evaluate(self.reply, self.train, self.holdout, self.seal)

    def test_overconfident_or_broken_probabilities_abort(self):
        self.reply["forecasts"][0]["probabilities"] = dict.fromkeys(fox.ACTIONS, 1.0)
        with self.assertRaises(ValueError):
            fox.evaluate(self.reply, self.train, self.holdout, self.seal)

    def test_nan_bool_negative_probabilities_abort(self):
        for value in (float("nan"), True, -0.1):
            reply = deepcopy(self.reply)
            reply["forecasts"][0]["probabilities"]["collect"] = value
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                fox.evaluate(reply, self.train, self.holdout, self.seal)

    def test_extra_directives_and_long_quips_abort(self):
        self.reply["shell_command"] = "do not execute"
        with self.assertRaises(ValueError):
            fox.evaluate(self.reply, self.train, self.holdout, self.seal)
        del self.reply["shell_command"]
        self.reply["quip"] = "x" * 161
        with self.assertRaises(ValueError):
            fox.evaluate(self.reply, self.train, self.holdout, self.seal)

    def test_inputs_are_not_modified(self):
        before = (deepcopy(self.reply), deepcopy(self.train), deepcopy(self.holdout))
        fox.evaluate(self.reply, self.train, self.holdout, self.seal)
        self.assertEqual(before, (self.reply, self.train, self.holdout))


if __name__ == "__main__":
    unittest.main()
