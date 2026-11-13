"""Offline failure injection plus native MuJoCo experiment contracts."""
import copy
import math
import tempfile
import unittest
from pathlib import Path

from experiments.tadash_embodied_origin import (
    CAPTURE_STEPS, SAMPLE_EVERY, MODEL, THRESHOLD,
    deviation, interpret, run_experiment, source_identity,
)


def fixture(command=0.0, tail=0.0, yaw=0.0, contact=0.0):
    frames = []
    for i in range(CAPTURE_STEPS // SAMPLE_EVERY):
        frames.append({
            "t_s": (i + 1) * 0.02,
            "pelvis_yaw_rad": yaw,
            "tail_yaw_rad": tail,
            "com_x_m": 0.0, "com_y_m": 0.0,
            "foot_left_n": contact, "foot_right_n": contact,
        })
    return {"quality": "native_simulated", "source_sha256": "fixture_source",
            "command_nm": command, "frames": frames}


class BodyOriginTests(unittest.TestCase):
    def setUp(self):
        self.baseline = fixture()
        self.predicted = fixture(command=8.0, tail=0.18)

    def test_no_command_is_no_detectable_change_not_verified_absence(self):
        result = interpret(self.baseline, self.baseline, copy.deepcopy(self.baseline), 0.)
        self.assertEqual(result["state"], "no_detectable_change")

    def test_self_command_matches_native_signature(self):
        self.assertEqual(interpret(self.baseline, self.predicted,
                                   copy.deepcopy(self.predicted), 8.)["state"],
                         "command_consistent")

    def test_uncommanded_change_stays_unexplained(self):
        observation = fixture(tail=0.4)
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unexplained_change")

    def test_command_without_expected_motion_fails(self):
        self.assertEqual(interpret(self.baseline, self.predicted, self.baseline, 8.)["state"],
                         "command_outcome_mismatch")

    def test_command_with_external_deviation_fails(self):
        observation = fixture(command=8.0, tail=0.18, yaw=0.2)
        self.assertEqual(interpret(self.baseline, self.predicted, observation, 8.)["state"],
                         "command_outcome_mismatch")

    def test_hidden_different_motor_command_is_not_consistent(self):
        observation = fixture(command=4.0, tail=0.18)
        self.assertEqual(interpret(self.baseline, self.predicted, observation, 8.)["state"],
                         "command_outcome_mismatch")

    def test_small_noise_never_certifies_no_stimulus(self):
        observation = fixture(tail=0.002)
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "no_detectable_change")

    def test_explicit_noisy_trace_abstains(self):
        observation = fixture(tail=2.)
        observation["quality"] = "synthetic_noise_not_native"
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_missing_afference_abstains(self):
        observation = fixture()
        del observation["frames"][0]["tail_yaw_rad"]
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_nan_contact_abstains(self):
        observation = fixture()
        observation["frames"][2]["foot_left_n"] = math.nan
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_negative_contact_abstains(self):
        observation = fixture(contact=-2.)
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_out_of_order_time_abstains(self):
        observation = fixture()
        observation["frames"][5]["t_s"] = observation["frames"][4]["t_s"]
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_wrong_model_identity_abstains(self):
        observation = fixture()
        observation["source_sha256"] = "wrong_source"
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_prediction_intent_mismatch_abstains(self):
        self.assertEqual(interpret(self.baseline, self.predicted, self.predicted, 3.)["state"],
                         "unverified")

    def test_non_identifying_expected_signature_abstains(self):
        prediction = fixture(command=8.)
        actual = fixture(command=8.)
        self.assertEqual(interpret(self.baseline, prediction, actual, 8.)["state"],
                         "unverified")

    def test_invalid_intent_abstains(self):
        self.assertEqual(interpret(self.baseline, self.predicted, self.predicted,
                                   float("nan"))["state"], "unverified")

    def test_time_grid_mismatch_abstains(self):
        observation = fixture()
        observation["frames"][3]["t_s"] += 0.005
        self.assertEqual(interpret(self.baseline, self.baseline, observation, 0.)["state"],
                         "unverified")

    def test_source_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "model.xml"
            fp.write_text("<mujoco/>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "model_source_pin_mismatch"):
                source_identity(fp)

    def test_native_MuJoCo_five_scenarios(self):
        try:
            import mujoco  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("MuJoCo unavailable; native CI required")
        report = run_experiment(MODEL)
        self.assertTrue(report["pass"], report)
        self.assertEqual(len(report["scenario_checks"]), 5)
        self.assertEqual(report["scenario_checks"],
                         {name: True for name in report["scenario_checks"]})


if __name__ == "__main__":
    unittest.main()
