"""Tests for the isolated prediction-error EMA research component."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).with_name("prediction_error_ema.py")
spec = importlib.util.spec_from_file_location("prediction_error_ema", MODULE)
import sys
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
PredictionErrorEMA = module.PredictionErrorEMA


class TestPredictionErrorEMA(unittest.TestCase):
    def test_first_observation_initializes_to_error(self):
        t = PredictionErrorEMA(alpha=0.2)
        self.assertAlmostEqual(t.observe(1, 1.5), 0.5)

    def test_ema_updates(self):
        t = PredictionErrorEMA(alpha=0.2)
        t.observe(1, 1.5)
        self.assertAlmostEqual(t.observe(1, 1.1), 0.42)

    def test_snapshot_resume(self):
        t = PredictionErrorEMA()
        t.observe(2, 3)
        restored = PredictionErrorEMA.restore(t.snapshot())
        self.assertEqual(t.snapshot(), restored.snapshot())
        self.assertEqual(t.observe(2, 2.5), restored.observe(2, 2.5))

    def test_rejects_bad_alpha(self):
        for alpha in (0, -1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                PredictionErrorEMA(alpha)

    def test_rejects_nonfinite_measurements(self):
        t = PredictionErrorEMA()
        with self.assertRaises(ValueError):
            t.observe(float("inf"), 0)
        self.assertEqual(t.state.observations, 0)

    def test_rejects_corrupted_snapshot(self):
        t = PredictionErrorEMA()
        bad = {**t.snapshot(), "observations": -2}
        with self.assertRaises(ValueError):
            PredictionErrorEMA.restore(bad)


if __name__ == "__main__":
    unittest.main()
