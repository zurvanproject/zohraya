import unittest
from neuropelvic import NeuroPelvic, CHAKRAS

class TestNeuroPelvic(unittest.TestCase):
    def test_bounds(self):
        for state in NeuroPelvic().run():
            for key, value in state.items():
                if isinstance(value, float) and key != "time":
                    self.assertTrue(0 <= value <= 1, (key, value))
            self.assertEqual(len(state["chakra"]), len(CHAKRAS))

    def test_phases(self):
        states = NeuroPelvic().run(seconds=21)
        self.assertEqual({s["phase"] for s in states},
                         {"baseline", "rising", "peak", "release", "recovery"})

    def test_recovery(self):
        states = NeuroPelvic().run(seconds=20)
        self.assertGreater(max(s["pelvic_tone"] for s in states
                               if s["phase"] == "peak"),
                           states[-1]["pelvic_tone"])

    def test_invalid_dt(self):
        with self.assertRaises(ValueError):
            NeuroPelvic().step(dt=0)

if __name__ == "__main__":
    unittest.main()
