"""Falsification and boundary tests for motor-learning pilot, NO simulated motor claims."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from experiments import tadash_motor_learning as lab
from experiments import tadash_motion_episode as evidence
from experiments import tadash_weight_shift as motor


def measured(target, gain=.9):
    return {"held_com_y_delta_m": target*gain}


def rows(gain=.9):
    return [{"target_m": target, "friction": friction,
             "baseline_observed_m": target*gain,
             "learned_observed_m": target}
            for friction in lab.HOLDOUT_FRICTIONS
            for target in lab.HOLDOUT_TARGETS]


def native(command, friction, gain=.9):
    shift = command*gain
    return {"schema": "native-v03-bilateral-shift/1",
            "requested_shift_y_m": command, "friction": friction,
            "completed": True, "failure": None,
            "seconds_completed": 4., "held_com_y_delta_m": shift,
            "returned_com_y_delta_m": 0.,
            "peak_tilt_deg": .05, "peak_motor_fraction": .65,
            "peak_joint_limit_excess_rad": 0.,
            "last_half_second_max_speed": .001,
            "both_feet_loaded_fraction": 1., "nonfoot_contacts": [],
            "trace": [{"t_s": i*.05} for i in range(80)],
            "controller": "original_v03_contact_QP_both_feet_grounded",
            "no_weight_update": True, "no_root_actuator": True}


class MotorLearningTests(unittest.TestCase):
    def test_fit_uses_observed_feedback_and_changes_parameter(self):
        learned = lab.learn_gain(measured(.002), measured(-.002), measured(0.))
        self.assertAlmostEqual(learned["learned_plant_gain"], .9)
        self.assertAlmostEqual(learned["command_gain"], 1/.9)
        self.assertTrue(learned["parameter_updated_from_native_feedback"])

    def test_fit_changes_when_training_response_changes(self):
        a = lab.learn_gain(measured(.002, .9), measured(-.002, .9), measured(0.))
        b = lab.learn_gain(measured(.002, .8), measured(-.002, .8), measured(0.))
        self.assertNotEqual(a["command_gain"], b["command_gain"])
        self.assertGreater(b["command_gain"], a["command_gain"])

    def test_no_nontrivial_update_is_not_falsely_learning(self):
        with self.assertRaisesRegex(ValueError, "No nontrivial learning"):
            lab.learn_gain(measured(.002, 1.), measured(-.002, 1.), measured(0.))

    def test_unphysical_or_inconsistent_gain_rejected(self):
        with self.assertRaisesRegex(ValueError, "physically plausible"):
            lab.learn_gain(measured(.002, .1), measured(-.002, .1), measured(0.))

    def test_heldout_improvement_requires_all_frozen_criteria(self):
        result = lab.eval_metrics(rows(.9))
        self.assertEqual(result["heldout_wins"], 8)
        self.assertGreater(result["relative_improvement"], .9)
        self.assertTrue(result["criterion_met"])

    def test_unchanged_or_worse_on_holdout_fails(self):
        bad = rows(.9)
        for row in bad:
            row["learned_observed_m"] = row["baseline_observed_m"]
        self.assertFalse(lab.eval_metrics(bad)["criterion_met"])
        for row in bad:
            row["learned_observed_m"] = row["target_m"]*.6
        self.assertFalse(lab.eval_metrics(bad)["criterion_met"])

    def test_partial_win_does_not_suffice(self):
        data = rows(.9)
        for row in data[:3]:
            row["learned_observed_m"] = row["target_m"]*.6
        self.assertFalse(lab.eval_metrics(data)["criterion_met"])

    def test_friction_condition_cannot_be_hidden_in_average(self):
        data = rows(.9)
        for row in data[4:]:
            row["learned_observed_m"] = row["baseline_observed_m"]
        self.assertFalse(lab.eval_metrics(data)["criterion_met"])

    def test_absent_or_too_small_control_error_cannot_prove_gain(self):
        data = rows(1.)
        with self.assertRaisesRegex(ValueError, "Baseline error"):
            lab.eval_metrics(data)

    def test_missing_holdout_cases_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete heldout"):
            lab.eval_metrics(rows()[:-1])

    def test_tampered_nonfinite_data_rejected(self):
        data = rows()
        data[2]["learned_observed_m"] = float("nan")
        with self.assertRaises(ValueError):
            lab.eval_metrics(data)

    def test_end_to_end_synthetic_case_is_labelled_mock_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"source"
            source.mkdir()
            calls = []
            def child(argv, **kwargs):
                command, friction = float(argv[-2]), float(argv[-1])
                calls.append((command, friction))
                return SimpleNamespace(returncode=0,
                                       stdout=json.dumps(native(command, friction)),
                                       stderr="")
            with patch.object(evidence, "source_identity", return_value={"fixture": "synthetic"}), \
                 patch.object(lab.subprocess, "run", side_effect=child):
                result = lab.run(source, Path(tmp)/"out")
            self.assertEqual(len(calls), lab.MAX_TRIALS)
            self.assertEqual(result["native_trials"], 19)
            self.assertTrue(result["metrics"]["criterion_met"])
            self.assertNotEqual(result["learned_command_gain"], 1.)
            frozen = json.loads((Path(tmp)/"out"/"frozen-model.json").read_text())
            self.assertEqual(len(frozen["training_receipt_sha256"]), 3)
            self.assertEqual(result["frozen_model_sha256"], evidence.sha(Path(tmp)/"out"/"frozen-model.json"))

    def test_native_unknown_halts_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"source"
            source.mkdir()
            with patch.object(evidence, "source_identity", return_value={"fixture": "synthetic"}), \
                 patch.object(lab.subprocess, "run", return_value=SimpleNamespace(
                     returncode=3,stdout="",stderr="error")) as child:
                with self.assertRaisesRegex(RuntimeError, "exited"):
                    lab.run(source, Path(tmp)/"out")
                self.assertEqual(child.call_count, 1)
            status=json.loads((Path(tmp)/"out"/"status.json").read_text())
            self.assertEqual(status["status"], "failed_or_unknown")
            self.assertTrue(status["no_automatic_retry"])

    def test_existing_output_rejected_before_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"source"; source.mkdir()
            output = Path(tmp)/"out"; output.mkdir()
            with patch.object(evidence, "source_identity", return_value={"fixture": "synthetic"}), \
                 patch.object(lab.subprocess, "run") as child:
                with self.assertRaises(FileExistsError):
                    lab.run(source, output)
                child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
