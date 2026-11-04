"""Matched native standing/observe test; no physiological efficacy is claimed."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .standing_demo import demo


class StandingIntegrationTests(unittest.TestCase):
    def test_standing_contact_balance_vitals_and_repeat(self):
        with TemporaryDirectory() as root:
            r = demo(Path(root) / "standing-check")
        self.assertEqual(r["total_native_cycles"], 6)
        self.assertTrue(r["matched_native_standing_behavior"])
        self.assertEqual(r["api_calls"], 0)
        self.assertFalse(r["actual_native_physiology_changed_by_overlay"])
        self.assertFalse(r["biomechanics_calibrated_for_170cm_78kg_body"])
        a, b = r["arms"]["baseline"], r["arms"]["neurovisceral"]
        self.assertEqual(a["snapshots"], b["snapshots"])
        self.assertEqual(a["native_cycles"], b["native_cycles"])
        self.assertEqual(len(b["overlay_counterfactuals"]), 3)
        self.assertEqual(b["overlay_receipts"], 3)
        self.assertEqual(a["overlay_receipts"], 0)
        self.assertTrue(a["cold_reopen_matches"])
        self.assertTrue(b["cold_reopen_matches"])
        self.assertEqual(a["replay_extra_cycles"], 0)
        self.assertTrue(all(action in ("observe", "protect")
                            for action in r["native_action_modes"]))
        for frame in b["snapshots"]:
            self.assertIn("balance_proxy", frame)
            self.assertIn("center_of_mass_xy_m", frame)
            self.assertIn("hr_bpm", frame)
            self.assertIn("rr_per_min", frame)
            self.assertIn("muscle_tone_proxy", frame)
            self.assertIn("tail_orientation_rad", frame)
            self.assertIn("foot_L", frame["feet"])
            self.assertIn("foot_R", frame["feet"])
            self.assertFalse(frame["full_collision_validation"])
        for row in b["overlay_counterfactuals"]:
            self.assertIn("heart_bpm", row["predicted_if_actuated_not_actuated"])
            self.assertIn("breaths_per_min", row["predicted_if_actuated_not_actuated"])


if __name__ == "__main__":
    unittest.main()
