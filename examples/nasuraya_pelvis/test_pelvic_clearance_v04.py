"""Numerical and safety-boundary tests for fabricated 3-D pelvic clearance."""
import copy
import json
import math
import unittest

from runtimes.tadash_body.pelvic_clearance_v04 import (
    evaluate_pelvic_clearance, segment_distance_m,
)


class GeometryTests(unittest.TestCase):
    def test_orthogonal_crossing_is_zero(self):
        self.assertAlmostEqual(segment_distance_m([0,0,0], [1,0,0],
                                                  [.5,-1,0], [.5,1,0]), 0)

    def test_skew_segments_have_known_distance(self):
        self.assertAlmostEqual(segment_distance_m([0,0,0], [1,0,0],
                                                  [.5,-1,2], [.5,1,2]), 2)

    def test_parallel_segments_have_known_gap(self):
        self.assertAlmostEqual(segment_distance_m([0,0,0], [1,0,0],
                                                  [0,3,0], [1,3,0]), 3)

    def test_degenerate_segments(self):
        self.assertAlmostEqual(segment_distance_m([0,0,0], [0,0,0],
                                                  [3,4,0], [3,4,0]), 5)

    def test_nan_bool_bad_points_rejected(self):
        for a in ([0,math.nan,0], [True,0,0], [0,0], "abc"):
            with self.subTest(a=a), self.assertRaises(ValueError):
                segment_distance_m(a,[0,0,0],[0,0,0],[1,0,0])


class ClearanceTests(unittest.TestCase):
    def test_neutral_profile_has_two_paired_corridors(self):
        result = evaluate_pelvic_clearance()
        self.assertEqual(set(result["pudendal_routes"]), {"L","R"})
        self.assertEqual(result["guard"], "within_synthetic_fixture")
        self.assertGreater(result["minimum_hypothetical_clearance_mm"], 0)
        self.assertAlmostEqual(result["pudendal_routes"]["L"]["hypothetical_tube_clearance_mm"],
                               result["pudendal_routes"]["R"]["hypothetical_tube_clearance_mm"])

    def test_lateral_offset_intersects_only_hypothetical_route(self):
        neutral = evaluate_pelvic_clearance()
        moved = evaluate_pelvic_clearance(tail_socket_lateral_fraction=.8)
        self.assertLess(moved["pudendal_routes"]["L"]["hypothetical_tube_clearance_mm"],
                        neutral["pudendal_routes"]["L"]["hypothetical_tube_clearance_mm"])
        self.assertEqual(moved["guard"], "review_required")
        self.assertIn("hypothetical_tail_nerve_corridor_overlap", moved["guard_reasons"])

    def test_left_right_mirror_symmetry_of_offset(self):
        l = evaluate_pelvic_clearance(tail_socket_lateral_fraction=.8)
        r = evaluate_pelvic_clearance(tail_socket_lateral_fraction=-.8)
        self.assertAlmostEqual(l["pudendal_routes"]["L"]["hypothetical_tube_clearance_mm"],
                               r["pudendal_routes"]["R"]["hypothetical_tube_clearance_mm"])

    def test_profile_stature_scales_clearance_but_not_mixing(self):
        small = evaluate_pelvic_clearance(profile="portrait_170_78")
        large = evaluate_pelvic_clearance(profile="runtime_250_195")
        self.assertAlmostEqual(small["minimum_hypothetical_clearance_mm"]/
                               large["minimum_hypothetical_clearance_mm"], 1.70/2.50, places=3)
        self.assertNotEqual(small["landmarks_m"]["sacrum_tail_root"],
                            large["landmarks_m"]["sacrum_tail_root"])

    def test_vagina_perturbation_does_not_move_uterus(self):
        low = evaluate_pelvic_clearance(vaginal_wall_load=0)
        high = evaluate_pelvic_clearance(vaginal_wall_load=1)
        self.assertLess(low["visceral_compartments"]["vagina"]["radial_displacement_proxy_mm"],
                        high["visceral_compartments"]["vagina"]["radial_displacement_proxy_mm"])
        self.assertEqual(low["visceral_compartments"]["uterus"],
                         high["visceral_compartments"]["uterus"])
        self.assertIn("synthetic_vaginal_wall_shift_limit", high["guard_reasons"])

    def test_uterine_perturbation_does_not_move_vagina(self):
        low = evaluate_pelvic_clearance(uterine_activity=0)
        high = evaluate_pelvic_clearance(uterine_activity=1)
        self.assertEqual(low["visceral_compartments"]["vagina"],
                         high["visceral_compartments"]["vagina"])
        self.assertGreater(high["visceral_compartments"]["uterus"]["axial_displacement_proxy_mm"],
                           low["visceral_compartments"]["uterus"]["axial_displacement_proxy_mm"])
        self.assertIn("synthetic_uterine_displacement_limit", high["guard_reasons"])

    def test_overload_ancestor_guard_carries_through(self):
        bad = evaluate_pelvic_clearance(profile="runtime_250_195",
                     intra_abdominal_pressure_kpa=25, floor_activation=0)
        self.assertIn("synthetic_floor_load_limit", bad["guard_reasons"])
        self.assertEqual(bad["guard"], "review_required")

    def test_snapshot_rejects_cross_scale_or_wrong_source(self):
        with self.assertRaises(ValueError):
            evaluate_pelvic_clearance(posture_snapshot={"source":"fake"})
        with self.assertRaises(ValueError):
            evaluate_pelvic_clearance(profile="runtime_250_195",
                                     posture_snapshot={"source":"fake"})

    def test_bad_inputs_rejected(self):
        for kwargs in ({"tail_socket_lateral_fraction":True},
                       {"tail_socket_lateral_fraction":float("nan")},
                       {"tail_socket_lateral_fraction":3},
                       {"vaginal_wall_load":-1}, {"uterine_activity":float("inf")},
                       {"floor_activation": "0.5"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                evaluate_pelvic_clearance(**kwargs)

    def test_report_is_deterministic_json_and_no_actuation(self):
        a = evaluate_pelvic_clearance()
        b = evaluate_pelvic_clearance()
        self.assertEqual(a, b)
        json.dumps(a, allow_nan=False)
        self.assertFalse(a["anatomy_validated"])
        self.assertFalse(a["biological_clearance_or_tissue_safety_established"])
        self.assertEqual(a["native_cycles_caused"], 0)
        self.assertFalse(a["actuation_authorized"])
        self.assertFalse(a["subjective_sensation_inferred"])
        self.assertFalse(a["sexual_state_inferred"])

    def test_returned_structures_cannot_mutate_next_calculation(self):
        a = evaluate_pelvic_clearance()
        a["pudendal_routes"]["L"]["centerline_m"][0][0] = 999
        b = evaluate_pelvic_clearance()
        self.assertNotEqual(b["pudendal_routes"]["L"]["centerline_m"][0][0], 999)


class MoreClearanceTests(unittest.TestCase):
    def test_near_margin_has_separate_guard(self):
        r = evaluate_pelvic_clearance(tail_socket_lateral_fraction=.65)
        self.assertEqual(r["guard"], "review_required")
        self.assertTrue(set(r["guard_reasons"]) &
              {"hypothetical_corridor_narrow_margin",
               "hypothetical_tail_nerve_corridor_overlap"})

    def test_v06_posture_valid_snapshot_will_not_modify_input(self):
        snap = {
            "source":"posture_step_v06_report",
            "posture":{"phase":"shift","com_m":[.01, 0.],
                       "tail_angle_rad":[0.,0.],
                       "kinematics":{"L":{"joints_m":{"hip":[.15,0.,1.42]}},
                                     "R":{"joints_m":{"hip":[-.13,0.,1.42]}}}},
            "balance":{"model_valid":True,"capture_margin_m":.01},
        }
        saved = copy.deepcopy(snap)
        r = evaluate_pelvic_clearance(profile="runtime_250_195",posture_snapshot=snap)
        self.assertEqual(snap,saved)
        self.assertEqual(r["source"],"caller_declared_V06_snapshot_not_cryptographically_verified")
        self.assertEqual(r["native_cycles_caused"],0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
