"""Autonomic recovery forecast tests: normalized native snapshot, no movement."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from .host import BodyLoop
from .autonomic_recovery_probe import forecast
from .instinct import InstinctController


class AutonomicRecoveryProbeTests(unittest.TestCase):
    def test_forecast_is_bounded_and_non_actuating(self):
        with TemporaryDirectory() as d:
            with BodyLoop.start(Path(d) / "recovery.sqlite",
                                mode="observe", max_actions=0) as loop:
                before = loop.body().checkpoint()["sha256"]
                native = InstinctController.enable(loop).status()["native_body"]
                output = forecast(native["values"], steps=8)
                self.assertFalse(output["native_body_changed"])
                self.assertEqual(len(output["steps"]), 9)
                for step in output["steps"]:
                    for key in ("sympathetic", "parasympathetic",
                                "arousal", "pain", "fatigue"):
                        self.assertGreaterEqual(step[key], 0)
                        self.assertLessEqual(step[key], 1)
                self.assertEqual(loop.body().checkpoint()["sha256"], before)
                self.assertEqual(loop.status()["completed_cycles"], 0)

    def test_directional_recovery_assumptions(self):
        values = {"sympathetic": .9, "parasympathetic": .1, "arousal": .8,
                  "pain": .4, "fatigue": .5}
        rows = forecast(values, steps=6)["steps"]
        for a, b in zip(rows, rows[1:]):
            self.assertLessEqual(b["sympathetic"], a["sympathetic"])
            self.assertGreaterEqual(b["parasympathetic"], a["parasympathetic"])
            self.assertLessEqual(b["arousal"], a["arousal"])
            self.assertLessEqual(b["fatigue"], a["fatigue"])
        self.assertEqual(rows[0]["sympathetic"], .9)

    def test_replay_and_invalid_values(self):
        values = dict(sympathetic=.7, parasympathetic=.2,
                      arousal=.4, pain=.2, fatigue=.3)
        self.assertEqual(forecast(values), forecast(values))
        with self.assertRaises(ValueError):
            forecast({**values, "pain": 2})
        with self.assertRaises(ValueError):
            forecast({**values, "arousal": float("nan")})
        with self.assertRaises(ValueError):
            forecast(values, steps=21)
        with self.assertRaises(ValueError):
            forecast({k:v for k,v in values.items() if k != "pain"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
