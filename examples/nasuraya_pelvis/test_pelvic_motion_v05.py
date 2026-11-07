"""Acceptance tests for fixed-root, offline synthetic pelvic vascular motion."""
import json
import math
import unittest
from runtimes.tadash_body.pelvic_motion_v05 import (
    generate_synthetic_tail_sweep, evaluate_tail_neurovascular_motion,
)


class MotionV05Tests(unittest.TestCase):
    def test_default_has_101_frames_and_two_seconds(self):
        f = generate_synthetic_tail_sweep()
        self.assertEqual(len(f), 101)
        self.assertEqual((f[0]["t_s"], f[-1]["t_s"]), (0., 2.))

    def test_neutral_has_bilateral_symmetry(self):
        f = [{"t_s": 0, "tail_base_yaw_rad": 0},
             {"t_s": 1, "tail_base_yaw_rad": 0}]
        r = evaluate_tail_neurovascular_motion(motion_frames=f)
        self.assertEqual(r["review_frame_count"], 0)
        for kind in r["worst_by_side"]["L"]:
            self.assertAlmostEqual(
                r["worst_by_side"]["L"][kind]["margin_mm"],
                r["worst_by_side"]["R"][kind]["margin_mm"], places=3)

    def test_stress_motion_detects_overlap(self):
        r = evaluate_tail_neurovascular_motion()
        self.assertGreater(r["review_frame_count"], 0)
        self.assertIsNotNone(r["first_alert_t_s"])
        self.assertTrue(any("overlap" in reason for row in r["time_series"]
                            for reason in row["reasons"]))

    def test_small_motion_does_not_raise_synthetic_guard(self):
        f = generate_synthetic_tail_sweep(amplitude_rad=.3)
        r = evaluate_tail_neurovascular_motion(motion_frames=f)
        self.assertEqual(r["review_frame_count"], 0)
        self.assertIsNone(r["first_alert_t_s"])

    def test_fixed_anchor_is_not_translated_during_yaw(self):
        r = evaluate_tail_neurovascular_motion()
        self.assertEqual([round(x, 4) for x in r["fixed_tail_anchor_m"]],
                         [0., -.085, .9996])
        self.assertIn("root_fixed_yaw", r["tail_base_rotation"])

    def test_mirror_sweep_mirrors_side_specific_worst_margins(self):
        l = [{"t_s": 0, "tail_base_yaw_rad": 1.8},
             {"t_s": 1, "tail_base_yaw_rad": 1.8}]
        r = [{"t_s": 0, "tail_base_yaw_rad": -1.8},
             {"t_s": 1, "tail_base_yaw_rad": -1.8}]
        a = evaluate_tail_neurovascular_motion(motion_frames=l)
        b = evaluate_tail_neurovascular_motion(motion_frames=r)
        for kind in a["worst_by_side"]["L"]:
            self.assertAlmostEqual(
                a["worst_by_side"]["L"][kind]["margin_mm"],
                b["worst_by_side"]["R"][kind]["margin_mm"], places=3)

    def test_three_channels_are_independent(self):
        r = evaluate_tail_neurovascular_motion()
        self.assertEqual(set(r["worst_by_side"]["L"]),
                         {"pudendal_nerve", "internal_pudendal_artery",
                          "internal_pudendal_vein"})
        self.assertNotEqual(
            r["worst_by_side"]["L"]["pudendal_nerve"]["margin_mm"],
            r["worst_by_side"]["L"]["internal_pudendal_artery"]["margin_mm"])

    def test_scale_separation(self):
        a = evaluate_tail_neurovascular_motion(profile="portrait_170_78")
        b = evaluate_tail_neurovascular_motion(profile="runtime_250_195")
        self.assertNotEqual(
            a["worst_by_side"]["L"]["pudendal_nerve"]["margin_mm"],
            b["worst_by_side"]["L"]["pudendal_nerve"]["margin_mm"])

    def test_bad_frames_fail_closed(self):
        cases = (
            [], [{}], [1, 2],
            [{"t_s": 0, "tail_base_yaw_rad": 0},
             {"t_s": 0, "tail_base_yaw_rad": 1}],
            [{"t_s": 0, "tail_base_yaw_rad": 0},
             {"t_s": 1, "tail_base_yaw_rad": float("nan")}],
            [{"t_s": 0, "tail_base_yaw_rad": 0},
             {"t_s": 1, "tail_base_yaw_rad": True}],
            [{"t_s": 0, "tail_base_yaw_rad": 0, "unknown": 1},
             {"t_s": 1, "tail_base_yaw_rad": 0}],
        )
        for sample in cases:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                evaluate_tail_neurovascular_motion(motion_frames=sample)

    def test_bad_generator_arguments_fail_closed(self):
        for kw in ({"duration_s": -1}, {"step_s": float("inf")},
                   {"frequency_hz": True}, {"amplitude_rad": 2.3},
                   {"duration_s": 2., "step_s": .03},
                   {"duration_s": 10., "step_s": .01}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                generate_synthetic_tail_sweep(**kw)

    def test_both_invalid_profile_and_kinematic_pressure_rejected(self):
        for kw in ({"profile": "nope"},
                   {"intra_abdominal_pressure_kpa": 30},
                   {"floor_activation": True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                evaluate_tail_neurovascular_motion(**kw)

    def test_input_is_unchanged_and_provenance_unverified(self):
        f = generate_synthetic_tail_sweep(duration_s=1., step_s=.1)
        frozen = json.dumps(f, sort_keys=True)
        r = evaluate_tail_neurovascular_motion(motion_frames=f)
        self.assertEqual(json.dumps(f, sort_keys=True), frozen)
        self.assertEqual(r["source_authentication"], "none")

    def test_zero_native_ticks_and_no_clinical_claim(self):
        r = evaluate_tail_neurovascular_motion()
        self.assertEqual(r["native_cycles_caused"], 0)
        self.assertFalse(r["actuation_authorized"])
        self.assertFalse(r["anatomical_or_biological_safety_established"])
        self.assertFalse(r["vascular_flow_or_tissue_compression_calculated"])
        self.assertFalse(r["subjective_sensation_inferred"])

    def test_determinism_and_json_contract(self):
        a = evaluate_tail_neurovascular_motion()
        self.assertEqual(a, evaluate_tail_neurovascular_motion())
        json.dumps(a, allow_nan=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
