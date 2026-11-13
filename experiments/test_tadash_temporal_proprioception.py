"""Deterministic classifier controls; native MuJoCo probes required in CI."""
import copy
import unittest

from experiments.tadash_embodied_origin import (
    CAPTURE_STEPS, SAMPLE_EVERY, MODEL, capture_native, source_identity,
)
from experiments.tadash_temporal_proprioception import classify_temporal


def fixture(command=0., tail=None, pelvis=None, source="synthetic-test"):
    n = CAPTURE_STEPS // SAMPLE_EVERY
    tail = tail if tail is not None else [0.] * n
    pelvis = pelvis if pelvis is not None else [0.] * n
    return {
        "source_sha256": source, "quality": "native_simulated",
        "command_nm": command,
        "frames": [
            {
                "t_s": .04 * (i + 1), "pelvis_yaw_rad": pelvis[i],
                "tail_yaw_rad": tail[i], "com_x_m": 0., "com_y_m": 0.,
                "foot_left_n": 0., "foot_right_n": 0.,
            }
            for i in range(n)
        ],
    }


class TemporalProprioceptionTests(unittest.TestCase):
    def setUp(self):
        self.rest = fixture()

    def test_clean_idle(self):
        self.assertEqual(classify_temporal(self.rest, self.rest,
                         copy.deepcopy(self.rest), 0.)["state"],
                         "no_detectable_change")

    def test_repeated_motor_action(self):
        action = fixture(command=8., tail=[.20] * 12)
        self.assertEqual(classify_temporal(self.rest, action,
                         copy.deepcopy(action), 8.)["state"],
                         "command_consistent")

    def test_two_channel_coherent_residual(self):
        values = [0.03 * i for i in range(12)]
        actual = fixture(tail=values, pelvis=values)
        outcome = classify_temporal(self.rest, self.rest, actual, 0.)
        self.assertEqual(outcome["state"], "unexplained_change")
        self.assertEqual(len(outcome["supported_proprioceptive_channels"]), 2)

    def test_single_channel_not_enough(self):
        values = [0.03 * i for i in range(12)]
        actual = fixture(tail=values)
        self.assertEqual(classify_temporal(self.rest, self.rest,
                         actual, 0.)["state"], "uncertain_noise_or_weak_signal")

    def test_strong_alternating_noise_not_a_causal_event(self):
        noise = [0.26 * (-1) ** i for i in range(12)]
        actual = fixture(tail=noise, pelvis=noise)
        self.assertEqual(classify_temporal(self.rest, self.rest,
                         actual, 0.)["state"], "uncertain_noise_or_weak_signal")

    def test_noisy_motor_does_not_earn_positive_consistency(self):
        action = fixture(command=8., tail=[.20] * 12)
        actual = fixture(command=8., tail=[.20 + .25*(-1)**i for i in range(12)],
                         pelvis=[.25*(-1)**i for i in range(12)])
        self.assertEqual(classify_temporal(self.rest, action,
                         actual, 8.)["state"], "uncertain_noise_or_weak_signal")

    def test_contradictory_intent_abstains(self):
        action = fixture(command=8., tail=[.20] * 12)
        self.assertEqual(classify_temporal(self.rest, action,
                         action, 2.)["state"], "unverified")

    def test_source_mismatch_abstains(self):
        observed = fixture(source="other")
        self.assertEqual(classify_temporal(self.rest, self.rest,
                         observed, 0.)["state"], "unverified")

    def test_missing_channel_abstains(self):
        observed = fixture()
        del observed["frames"][3]["pelvis_yaw_rad"]
        self.assertEqual(classify_temporal(self.rest, self.rest,
                         observed, 0.)["state"], "unverified")

    def test_native_five_source_pinned_cases(self):
        try:
            import mujoco
            import numpy as np
        except ImportError:
            self.skipTest("native MuJoCo required in GitHub Actions")
        identity = source_identity(MODEL)
        model = mujoco.MjModel.from_xml_path(str(MODEL))
        rest = capture_native(model, mujoco, np, identity)
        command = capture_native(model, mujoco, np, identity, command_nm=8.)
        disturbance = capture_native(model, mujoco, np, identity, external_torque_nm=35.)
        combined = capture_native(model, mujoco, np, identity, command_nm=8.,
                                  external_torque_nm=35.)
        pairs = {
            "quiet": (rest, rest, rest, 0., "no_detectable_change"),
            "efference": (rest, command, command, 8., "command_consistent"),
            "uncommanded": (rest, rest, disturbance, 0., "unexplained_change"),
            "mismatch": (rest, command, combined, 8., "command_outcome_mismatch"),
        }
        for name, (reference, prediction, actual, command_nm, target) in pairs.items():
            with self.subTest(name=name):
                outcome = classify_temporal(reference, prediction, actual, command_nm)
                self.assertEqual(outcome["state"], target, outcome)


if __name__ == "__main__":
    unittest.main()
