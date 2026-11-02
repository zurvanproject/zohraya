"""Synthetic logic tests; they are not motion trials or proof of learning."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from experiments import tadash_weight_shift as lab
from experiments import tadash_motion_episode as original


def native(shift, held=None, return_delta=0.0001):
    return {"schema": "native-v03-bilateral-shift/1", "requested_shift_y_m": shift,
            "seconds_completed": 4.0, "completed": True, "failure": None,
            "held_com_y_delta_m": shift * .6 if held is None else held,
            "returned_com_y_delta_m": return_delta,
            "peak_tilt_deg": 0.45, "peak_motor_fraction": .90,
            "peak_joint_limit_excess_rad": 0.0, "last_half_second_max_speed": .001,
            "both_feet_loaded_fraction": 1., "nonfoot_contacts": [], "qp_solves": 800,
            "trace": [{"t_s": i / 20} for i in range(80)],
            "controller": "original_v03_contact_QP_both_feet_grounded",
            "body_model": "unchanged_78kg_v03", "no_weight_update": True,
            "no_root_actuator": True}


class ShiftTests(unittest.TestCase):
    def test_baseline_and_signed_threshold(self):
        baseline = native(0., held=.0001, return_delta=.0001)
        self.assertEqual(lab.outcome(native(.002, held=.0010), baseline)[0], "met")
        self.assertEqual(lab.outcome(native(-.002, held=-.0010), baseline)[0], "met")
        self.assertEqual(lab.outcome(native(.002, held=.0002), baseline)[0], "not_met")
        self.assertEqual(lab.outcome(native(-.002, held=.0008), baseline)[0], "not_met")

    def test_bad_return_is_not_a_pass(self):
        control = native(0., held=0., return_delta=0.)
        self.assertEqual(lab.outcome(native(.002, return_delta=.008), control)[0], "not_met")

    def test_repetition_and_simplification_rules(self):
        self.assertEqual(lab.next_magnitude(.002, "met"), (.002, "repeat_to_check_same_direction"))
        self.assertEqual(lab.next_magnitude(.002, "not_met"), (.001, "simplify_verified_insufficient_response"))
        self.assertEqual(lab.next_magnitude(.001, "not_met"), (None, "stop_at_smallest"))

    def test_bad_curriculum_state_rejected(self):
        for args in [(.003, "met"), (.002, "unknown"), (.0005, "not_met")]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                lab.next_magnitude(*args)

    def test_valid_native_requires_pinned_controller_and_complete_trace(self):
        self.assertTrue(lab.validate(native(.002), .002))
        wrong = native(.002)
        wrong["trace"] = []
        with self.assertRaisesRegex(ValueError, "time-series"):
            lab.validate(wrong, .002)

    def test_wrong_target_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "Wrong shift"):
            lab.validate(native(.002), -.002)

    def test_unsafe_contact_is_not_a_failure_to_simplify(self):
        wrong = native(.002)
        wrong["nonfoot_contacts"] = ["torso"]
        with self.assertRaisesRegex(ValueError, "Nonfoot"):
            lab.validate(wrong, .002)

    def test_excess_tilt_motor_load_speed_and_warnings(self):
        for key, value in [("peak_tilt_deg", 21), ("peak_motor_fraction", 1.5),
                           ("peak_joint_limit_excess_rad", .03),
                           ("last_half_second_max_speed", .15),
                           ("both_feet_loaded_fraction", .5)]:
            with self.subTest(key=key):
                wrong = native(.002)
                wrong[key] = value
                with self.assertRaisesRegex(ValueError, "guard"):
                    lab.validate(wrong, .002)
        bad = native(.002)
        bad["completed"] = False
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            lab.validate(bad, .002)

    def test_nan_is_rejected(self):
        wrong = native(.002)
        wrong["held_com_y_delta_m"] = float("nan")
        with self.assertRaises(ValueError):
            lab.validate(wrong, .002)

    def test_end_to_end_mock_keeps_intents_and_independent_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            seen = []
            def simulate(argv, **kwargs):
                shift = float(argv[-1])
                seen.append(shift)
                return SimpleNamespace(returncode=0, stdout=json.dumps(native(shift)), stderr="")
            with patch.object(original, "source_identity", return_value={"synthetic": True}), \
                    patch.object(lab.subprocess, "run", side_effect=simulate):
                summary = lab.run(source, Path(tmp) / "out")
            self.assertEqual(seen, [0., .002, .002, -.002, -.002])
            self.assertEqual(summary["trials"], 5)
            self.assertFalse(summary["learning_established"])
            self.assertEqual(json.loads((Path(tmp) / "out" / "status.json").read_text())["status"], "complete")

    def test_mock_failure_halves_magnitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            seen = []
            def simulate(argv, **kwargs):
                shift = float(argv[-1])
                seen.append(shift)
                held = 0.0 if abs(shift) == .002 else shift * .6
                return SimpleNamespace(returncode=0, stdout=json.dumps(native(shift, held=held)), stderr="")
            with patch.object(original, "source_identity", return_value={"synthetic": True}), \
                    patch.object(lab.subprocess, "run", side_effect=simulate):
                summary = lab.run(source, Path(tmp) / "out")
            self.assertEqual(seen, [0., .002, .001, -.002, -.001])
            self.assertEqual(summary["trials"], 5)

    def test_process_failure_halts_and_does_not_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            with patch.object(original, "source_identity", return_value={"synthetic": True}), \
                    patch.object(lab.subprocess, "run",
                                 return_value=SimpleNamespace(returncode=2, stdout="", stderr="native error")) as subprocess_mock:
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    lab.run(source, Path(tmp) / "out")
                self.assertEqual(subprocess_mock.call_count, 1)
            status = json.loads((Path(tmp) / "out" / "status.json").read_text())
            self.assertEqual(status["status"], "failed_or_unknown")
            self.assertTrue(status["no_automatic_retry"])

    def test_existing_output_rejected_before_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "out"
            source.mkdir()
            output.mkdir()
            with patch.object(original, "source_identity", return_value={"synthetic": True}), \
                    patch.object(lab.subprocess, "run") as subprocess_mock:
                with self.assertRaises(FileExistsError):
                    lab.run(source, output)
                subprocess_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
