"""Offline tests for Tadash first simulated-ground-contact exercise.

Mocks are synthetic unit tests. Real MuJoCo trials only run in pinned CI.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from experiments import tadash_first_touch_practice as ground
from experiments import tadash_motion_episode as evidence


def fixture(x,friction):
    trace=[]
    for i in range(80):
        t=i*.05
        force_d=(x/.001)*6.0
        trace.append({"t_s":round(t,3),
                      "commanded_y_shift_m":x if t<2 else 0.,
                      "observed_com_y_delta_m":x*.91,
                      "foot_normal_n":[390+force_d,390-force_d],
                      "tilt_deg":.1})
    return {"schema":"native-v03-bilateral-shift/1","requested_shift_y_m":x,
            "friction":friction,"completed":True,"failure":None,
            "seconds_completed":4.,"held_com_y_delta_m":x*.91,
            "returned_com_y_delta_m":x*.0002,
            "peak_tilt_deg":.1,"peak_motor_fraction":.65,
            "peak_joint_limit_excess_rad":0.,
            "last_half_second_max_speed":.001,
            "both_feet_loaded_fraction":1.,"nonfoot_contacts":[],
            "trace":trace,
            "controller":"original_v03_contact_QP_both_feet_grounded",
            "no_weight_update":True,"no_root_actuator":True}


class GroundTests(unittest.TestCase):
    def test_hypothesis_training_requires_three_distinct_observations(self):
        examples=[
            {"name":"still","measured_center_m":0.0},
            {"name":"left","measured_center_m":-.00091},
            {"name":"right","measured_center_m":.00091}]
        result=ground.fit_sensitivity(examples)
        self.assertAlmostEqual(result["response_gain"],.91)
        with self.assertRaisesRegex(ValueError,"three ordered"):
            ground.fit_sensitivity(examples[:-1])

    def test_native_trace_extracts_actual_two_foot_loads(self):
        observation=ground.trace_features(fixture(.001,.6))
        self.assertEqual(observation["sample_count"],80)
        self.assertTrue(observation["all_80_samples_both_loaded"])
        self.assertAlmostEqual(observation["hold_total_normal_n"],780.)
        self.assertAlmostEqual(observation["hold_left_minus_right_n"],12.)

    def test_slip_and_soil_are_explicitly_unmeasured(self):
        measured=ground.trace_features(fixture(0,.6))
        self.assertEqual(measured["slip_speed"],"not_measured_by_pinned_native_trace")
        self.assertEqual(measured["soil_texture"],"not_measured")
        self.assertEqual(measured["subjective_touch"],"not_established")

    def test_nonfinite_force_rejected(self):
        native=fixture(.001,.6)
        native["trace"][10]["foot_normal_n"][0]=float("nan")
        with self.assertRaises(ValueError):
            ground.trace_features(native)

    def test_contact_sample_missing_or_wrong_size_rejected(self):
        native=fixture(.001,.6)
        native["trace"][0]["foot_normal_n"]=[1]
        with self.assertRaisesRegex(ValueError,"Missing"):
            ground.trace_features(native)
        native=fixture(.001,.6)
        native["trace"].pop()
        with self.assertRaisesRegex(ValueError,"wrong size"):
            ground.trace_features(native)

    def test_native_time_grid_drift_rejected(self):
        native=fixture(.001,.6)
        native["trace"][15]["t_s"]=.777
        with self.assertRaisesRegex(ValueError,"sampling grid"):
            ground.trace_features(native)

    def test_heldout_predictions_are_evaluated_without_hidden_assumption(self):
        rows=[]
        for name,x,f in ground.TEST:
            row={"name":name,"phase":"holdout","measured_center_m":.91*x,
                 "returned_m":0.,
                 "contacts":ground.trace_features(fixture(x,f)),
                 "forecast_m":{"learned":.91*x,
                               "historical_prior":ground.PRIOR_GAIN*x,
                               "no_response":0.,"perfect_tracking":x}}
            rows.append(row)
        result=ground.report(rows,{"response_gain":.91})
        self.assertTrue(result["signed_response_measured"])
        self.assertTrue(result["two_feet_loaded_all_samples"])
        self.assertTrue(result["return_close_to_origin"])
        self.assertTrue(result["load_transfer_detected_by_native_force_difference"])
        self.assertFalse(result["slip_measured"])
        self.assertFalse(result["soil_measured"])

    def test_six_native_mock_trials_store_prediction_first(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            motion=root/"source"
            motion.mkdir()
            seen=[]
            def child(args,**kwargs):
                x,f=float(args[-2]),float(args[-1])
                seen.append((x,f))
                return SimpleNamespace(returncode=0,
                                       stdout=json.dumps(fixture(x,f)),stderr="")
            with patch.object(evidence,"source_identity",return_value={"fixture":"synthetic"}), \
                 patch.object(ground.subprocess,"run",side_effect=child):
                report=ground.run(motion,root/"out")
            self.assertEqual(len(seen),6)
            self.assertEqual(report["native_trials"],6)
            self.assertFalse(report["new_touch_sensation_created"])
            self.assertFalse(report["new_soil_or_slip_sensor_created"])
            holdout=json.loads((root/"out"/"trial-04-intent.json").read_text())
            self.assertIn("learned",holdout["predictions_before_native"])
            self.assertEqual(holdout["phase"],"holdout")
            frozen=json.loads((root/"out"/"frozen-contact-prediction.json").read_text())
            self.assertEqual(len(frozen["training_receipt_sha256"]),3)
            self.assertEqual(json.loads((root/"out"/"status.json").read_text())["status"],"complete")

    def test_crash_halts_further_trials_without_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"source";source.mkdir()
            with patch.object(evidence,"source_identity",return_value={"fixture":"synthetic"}), \
                 patch.object(ground.subprocess,"run",return_value=SimpleNamespace(
                    returncode=4,stdout="",stderr="error")) as child:
                with self.assertRaisesRegex(RuntimeError,"Native process"):
                    ground.run(source,root/"out")
                self.assertEqual(child.call_count,1)
            report=json.loads((root/"out"/"status.json").read_text())
            self.assertEqual(report["status"],"failed_or_unknown")
            self.assertTrue(report["no_automatic_retry"])

    def test_no_stale_output_folder_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"source";source.mkdir()
            out=root/"out";out.mkdir()
            with patch.object(evidence,"source_identity",return_value={"fixture":"synthetic"}):
                with self.assertRaises(FileExistsError):
                    ground.run(source,out)


if __name__=="__main__":
    unittest.main()
