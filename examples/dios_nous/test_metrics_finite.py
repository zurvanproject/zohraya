"""Regression tests for finite serialization of valid prediction inputs."""
import json
import unittest

from examples.dios_nous.metrics import evaluate_binary_predictions


class FiniteMetricsTests(unittest.TestCase):
    def test_subnormal_baseline_does_not_emit_infinity(self):
        result = evaluate_binary_predictions([
            {"prediction": 1.0, "baseline": 1e-160, "outcome": 0}])
        self.assertEqual(result["model_brier"], 1.0)
        self.assertEqual(result["improvement_delta"], -1.0)
        self.assertIsNone(result["relative_improvement_pct"])
        self.assertEqual(result["relative_improvement_status"], "numeric_overflow")
        json.dumps(result, allow_nan=False)

    def test_zero_baseline_is_distinguished_from_overflow(self):
        result = evaluate_binary_predictions([
            {"prediction": 1.0, "baseline": 0.0, "outcome": 0}])
        self.assertIsNone(result["relative_improvement_pct"])
        self.assertEqual(result["relative_improvement_status"], "baseline_zero")
        json.dumps(result, allow_nan=False)

    def test_finite_relative_improvement_and_degradation_are_preserved(self):
        for prediction, expected in ((0.1, 96.0), (1.0, -300.0)):
            with self.subTest(prediction=prediction):
                result = evaluate_binary_predictions([
                    {"prediction": prediction, "baseline": 0.5, "outcome": 0}])
                self.assertEqual(result["relative_improvement_pct"], expected)
                self.assertEqual(result["relative_improvement_status"], "finite")
                json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
