"""Acceptance tests for read-only Tadash pelvic geometry v0.1."""
import json
import math
import unittest

from runtimes.tadash_body.pelvis_v01 import FIXTURES, evaluate_pelvis


class PelvisV01Tests(unittest.TestCase):
    def test_repo_source_pinned_runtime_landmarks(self):
        result = evaluate_pelvis()
        self.assertEqual(result["profile"], "runtime_250_195")
        self.assertEqual(result["mass_kg"], 195.)
        self.assertEqual(result["landmarks_m"]["hip_L"], [.14, 0., 1.42])
        self.assertEqual(result["landmarks_m"]["hip_R"], [-.14, 0., 1.42])
        self.assertAlmostEqual(result["hip_span_m"], .28)

    def test_170_78_profile_is_distinct_and_does_not_mutate_runtime(self):
        short = evaluate_pelvis(profile="portrait_170_78")
        tall = evaluate_pelvis()
        self.assertEqual((short["stature_m"], short["mass_kg"]), (1.70, 78.))
        self.assertEqual((tall["stature_m"], tall["mass_kg"]), (2.50, 195.))
        self.assertEqual(FIXTURES["runtime_250_195"].hip_height_m, 1.42)
        self.assertEqual(short["tail_length_m"], .85)

    def test_pelvis_rotation_preserves_hip_span_and_has_tail_root_behind_pubis(self):
        result = evaluate_pelvis(pitch_rad=.23, roll_rad=-.2, yaw_rad=.31)
        self.assertAlmostEqual(result["hip_span_m"], .28, places=6)
        neutral = evaluate_pelvis()["landmarks_m"]
        self.assertLess(neutral["sacrum_tail_root"][1], neutral["pubic_symphysis"][1])
        self.assertGreater(neutral["sacrum_tail_root"][2], neutral["pelvic_floor_center"][2])

    def test_pressure_load_is_not_body_weight(self):
        result = evaluate_pelvis(intra_abdominal_pressure_kpa=2.)
        self.assertAlmostEqual(result["floor_load_n"], 20.)
        self.assertAlmostEqual(result["weight_n"], 195. * 9.81)
        self.assertNotEqual(result["floor_load_n"], result["weight_n"])

    def test_activation_reduces_deflection_at_equal_pressure(self):
        passive = evaluate_pelvis(intra_abdominal_pressure_kpa=5., floor_activation=0.)
        active = evaluate_pelvis(intra_abdominal_pressure_kpa=5., floor_activation=.5)
        self.assertGreater(passive["floor_deflection_m"], active["floor_deflection_m"])
        self.assertEqual(active["floor_residual_load_n"], 0.)

    def test_overload_fails_closed_with_residual_and_guard(self):
        result = evaluate_pelvis(intra_abdominal_pressure_kpa=25., floor_activation=0.)
        self.assertTrue(result["floor_saturated"])
        self.assertGreater(result["floor_residual_load_n"], 0.)
        self.assertEqual(result["guard"], "needs_review")
        self.assertLessEqual(result["floor_deflection_m"], .018)

    def test_shift_reverses_hip_moment_sign(self):
        l = evaluate_pelvis(com_left_m=.05, com_forward_m=.10)
        r = evaluate_pelvis(com_left_m=-.05, com_forward_m=-.10)
        self.assertAlmostEqual(l["hip_roll_moment_nm"], -r["hip_roll_moment_nm"])
        self.assertAlmostEqual(l["hip_pitch_moment_nm"], -r["hip_pitch_moment_nm"])

    def test_invalid_or_nonfinite_inputs_rejected(self):
        for kwargs in ({"profile": "unknown"}, {"floor_activation": True},
                       {"intra_abdominal_pressure_kpa": float("nan")},
                       {"intra_abdominal_pressure_kpa": float("inf")},
                       {"intra_abdominal_pressure_kpa": -1},
                       {"pitch_rad": 1.}, {"com_left_m": ".1"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                evaluate_pelvis(**kwargs)

    def test_determinism_json_and_no_actuation_or_sensation_claim(self):
        left = evaluate_pelvis(profile="portrait_170_78", roll_rad=.1)
        right = evaluate_pelvis(profile="portrait_170_78", roll_rad=.1)
        self.assertEqual(left, right)
        json.dumps(left, allow_nan=False)
        self.assertEqual(left["native_cycles_caused"], 0)
        self.assertFalse(left["actuation_authorized"])
        self.assertFalse(left["subjective_or_sexual_response_inferred"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
