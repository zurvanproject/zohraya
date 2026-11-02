"""Adversarial and falsifiable tests of Tadash small-world predictions.

All fixtures below are MOCK observations. Native MuJoCo proof is CI-only.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from experiments import tadash_epistemic_world_model as w
from experiments import tadash_motion_episode as evidence


def training_rows(effect=lambda x,f:(.91+.025*(f-.55))*x):
    return [{"command_m":x,"friction":f,"observed_m":effect(x,f)} for x,f in w.TRAIN]


def mock_native(x,f):
    y=(.91+.025*(f-.55))*x
    return {"schema":"native-v03-bilateral-shift/1",
            "requested_shift_y_m":x,"friction":f,"completed":True,"failure":None,
            "seconds_completed":4.,"held_com_y_delta_m":y,
            "returned_com_y_delta_m":0.,"peak_tilt_deg":.05,
            "peak_motor_fraction":.64,"peak_joint_limit_excess_rad":0.,
            "last_half_second_max_speed":.0001,"both_feet_loaded_fraction":1.,
            "nonfoot_contacts":[],"trace":[{"t_s":i*.05} for i in range(80)],
            "controller":"original_v03_contact_QP_both_feet_grounded",
            "no_weight_update":True,"no_root_actuator":True}


class WorldModelTests(unittest.TestCase):
    def test_domain_boundary_abstains_outside_known_world(self):
        with self.assertRaisesRegex(ValueError,"abstain"):
            w.validate_point(.0035,.55)
        with self.assertRaisesRegex(ValueError,"abstain"):
            w.validate_point(.002,.45)

    def test_finite_guards_forbid_unknown(self):
        for val in (float("nan"),float("inf"),True):
            with self.subTest(val=str(val)),self.assertRaises(ValueError):
                w.validate_point(val,.55)

    def test_linear_hypothesis_fits_linear_physics(self):
        data=training_rows(lambda x,f:.90*x)
        g=w.coefficients("linear",data)[0]
        self.assertAlmostEqual(g,.90,places=10)

    def test_friction_hypothesis_explains_conditional_response(self):
        data=training_rows()
        a,b=w.coefficients("friction",data)
        self.assertAlmostEqual(a,.91,places=9)
        self.assertAlmostEqual(b,.025,places=9)
        self.assertAlmostEqual(w.estimate("friction",[a,b],.002,.55),.00182,places=8)

    def test_stronger_complex_model_requires_crossvalidation(self):
        name,cross,models=w.choose_model(training_rows())
        self.assertEqual(name,"friction")
        self.assertLess(cross["friction"],cross["linear"]*.9)
        self.assertEqual(set(models),set(w.KINDS))

    def test_simple_world_prefers_simple_model(self):
        name,cross,models=w.choose_model(training_rows(lambda x,f:.91*x))
        self.assertEqual(name,"linear")
        self.assertAlmostEqual(models["linear"][0],.91)

    def test_unidentifiable_model_rejected(self):
        only=[{"command_m":.001,"friction":.55,"observed_m":.0009} for _ in range(8)]
        with self.assertRaisesRegex(ValueError,"Unidentifiable"):
            w.coefficients("friction",only)

    def test_incomplete_training_cannot_claim_world_model(self):
        with self.assertRaisesRegex(ValueError,"Missing"):
            w.choose_model(training_rows()[:-1])

    def test_heldout_models_compete_with_strong_prior(self):
        data=[]
        for x,f in w.HOLDOUT:
            y=(.91+.025*(f-.55))*x
            data.append({"command_m":x,"friction":f,"observed_m":y,"returned_m":0.,
                         "predictions":{"chosen":y,"prior":w.PRIOR_GAIN*x,
                                        "identity":x,"zero":0.}})
        report=w.evaluate(data)
        self.assertTrue(report["all_strong_prior_gates_met"])
        self.assertGreater(report["mae_m"]["prior"],report["mae_m"]["chosen"])
        self.assertTrue(report["criteria"]["returned_to_center_within_0_1mm"])

    def test_model_that_only_beats_zero_not_strong_prior_is_not_a_discovery(self):
        rows=[]
        for x,f in w.HOLDOUT:
            y=w.PRIOR_GAIN*x
            rows.append({"command_m":x,"friction":f,"observed_m":y,"returned_m":0.,
                         "predictions":{"chosen":.90*x,"prior":y,"identity":x,"zero":0.}})
        report=w.evaluate(rows)
        self.assertFalse(report["all_strong_prior_gates_met"])
        self.assertFalse(report["criteria"]["better_than_prior_by_10_percent"])

    def test_native_mock_records_predictions_prior_to_native_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"motion"
            source.mkdir()
            calls=[]
            def fake(argv,**kw):
                x,f=float(argv[-2]),float(argv[-1])
                calls.append((x,f))
                return SimpleNamespace(returncode=0,stdout=json.dumps(mock_native(x,f)),stderr="")
            with patch.object(evidence,"source_identity",return_value={"fixture":"mock only"}), \
                 patch.object(w.subprocess,"run",side_effect=fake):
                result=w.run(source,Path(tmp)/"run")
            self.assertEqual(len(calls),16)
            self.assertTrue(result["metrics"]["all_strong_prior_gates_met"])
            frozen=json.loads((Path(tmp)/"run"/"frozen-world-model.json").read_text())
            self.assertEqual(len(frozen["training_receipts"]),8)
            holdout_intent=json.loads((Path(tmp)/"run"/"trial-09-intent.json").read_text())
            self.assertEqual(holdout_intent["phase"],"holdout")
            self.assertIn("chosen",holdout_intent["predictions"])
            self.assertEqual(result["native_trials"],16)

    def test_unknown_native_error_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"motion"
            source.mkdir()
            with patch.object(evidence,"source_identity",return_value={"fixture":"mock only"}), \
                 patch.object(w.subprocess,"run",return_value=SimpleNamespace(returncode=1,stdout="",stderr="failure")) as fake:
                with self.assertRaisesRegex(RuntimeError,"Native failed"):
                    w.run(source,Path(tmp)/"run")
                self.assertEqual(fake.call_count,1)
            status=json.loads((Path(tmp)/"run"/"status.json").read_text())
            self.assertEqual(status["status"],"failed_or_unknown")
            self.assertTrue(status["no_automatic_retry"])


if __name__=="__main__":
    unittest.main()
