"""Read-only observer integration checks, including a source-pinned V06 record."""
import copy
import json
import math
import unittest

from runtimes.tadash_body.pelvis_observer_v02 import observe_pelvis


# Extracted coordinates from examples/nasuraya_body_mirror/frames.json:
# normal, first revision, recorded snapshot; neither measured human data nor
# live PostureLoop commands. The checkpoint is a label, not an authentication.
RECORD = {
    "source": "body_mirror_v06_record",
    "record": {
        "revision": 1,
        "checkpoint_sha256": "e1524943820cd6ad4dcea477a75ff6b44bbbdcb12befb5b3a93f623eb58db1f2",
        "phase": "shift",
        "com_m": [0.05165674067075586, 0.0],
        "tail_angle_rad": [0.0, 0.0],
        "joints_m": {
            "L": {"hip": [0.1916567406707559, 0.0, 1.42]},
            "R": {"hip": [-0.08834325932924415, 0.0, 1.42]},
        },
    },
}


def live_report(*, x=.03, y=.01, phase="shift", valid=True, margin=.01):
    return {
        "source": "posture_step_v06_report",
        "posture": {
            "phase": phase,
            "com_m": [x, y],
            "tail_angle_rad": [.1, -.05],
            "kinematics": {
                "L": {"joints_m": {"hip": [x + .14, y, 1.42]}},
                "R": {"joints_m": {"hip": [x - .14, y, 1.42]}},
            },
        },
        "balance": {"model_valid": valid, "capture_margin_m": margin},
    }


class ObserverV02Tests(unittest.TestCase):
    def test_recorded_v06_snapshot_matches_pinned_hips(self):
        out = observe_pelvis(RECORD)
        self.assertEqual(out["revision_label"], 1)
        self.assertEqual(out["checkpoint_label"], RECORD["record"]["checkpoint_sha256"])
        self.assertAlmostEqual(out["hip_anchors_m"]["L"][0], .1916567406707559)
        self.assertEqual(out["gait_phase"], "shift")

    def test_passthrough_snapshot_world_translation(self):
        out = observe_pelvis(live_report(x=.03, y=.01))
        self.assertEqual(out["pelvis_landmarks_world_m"]["hip_L"], [.17, .01, 1.42])
        self.assertEqual(out["pelvis_landmarks_world_m"]["hip_R"], [-.11, .01, 1.42])
        self.assertEqual(out["source_declared"], "posture_step_v06_report")
        self.assertEqual(out["source_authentication"], "not_cryptographically_verified_by_observer")

    def test_tail_root_geometry_is_finite_and_length_preserved(self):
        out = observe_pelvis(live_report())
        self.assertAlmostEqual(out["tail_root_distance_m"], 1.20, places=5)
        self.assertLess(out["sacral_tail_tip_m"][1], out["pelvis_landmarks_world_m"]["sacrum_tail_root"][1])

    def test_pathway_is_paired_and_geometric_only(self):
        out = observe_pelvis(live_report())
        nodes = out["lumbar_sacral_and_perineal_proxy_nodes_m"]
        self.assertEqual(set(out["hypothetical_afferent_routes"]), {"L", "R"})
        self.assertTrue(all(all(key in nodes for key in path)
                            for path in out["hypothetical_afferent_routes"].values()))
        self.assertAlmostEqual(nodes["sacral_root_L"][0] - out["com_m"][0],
                               -(nodes["sacral_root_R"][0] - out["com_m"][0]))
        self.assertIn("not_anatomic_nerve_trace", out["route_scope"])

    def test_pressure_increases_synthetic_afferent_signal(self):
        lo = observe_pelvis(live_report(), intra_abdominal_pressure_kpa=0.)
        hi = observe_pelvis(live_report(), intra_abdominal_pressure_kpa=8.)
        self.assertLess(lo["afferent_mechanical_load_proxy"], hi["afferent_mechanical_load_proxy"])
        self.assertNotIn("sexual", lo["afferent_scope"])

    def test_high_graded_floor_load_reports_guard_not_success(self):
        out = observe_pelvis(live_report(), intra_abdominal_pressure_kpa=25.)
        self.assertEqual(out["guard"], "review_required")
        self.assertIn("synthetic_floor_capacity_exceeded", out["guard_reasons"])
        self.assertGreater(out["pelvic_floor"]["residual_load_n"], 0.)

    def test_stumble_in_model_marks_failure_without_actuation(self):
        out = observe_pelvis(live_report(phase="failed", valid=False, margin=-.01))
        self.assertEqual(out["guard"], "review_required")
        self.assertIn("V06_posture_failed", out["guard_reasons"])
        self.assertIn("capture_point_outside_support", out["guard_reasons"])
        self.assertEqual(out["native_cycles_caused"], 0)
        self.assertFalse(out["actuation_authorized"])

    def test_reject_bad_hip_anchor_and_wrong_scale(self):
        bad = live_report()
        bad["posture"]["kinematics"]["R"]["joints_m"]["hip"][2] += .05
        with self.assertRaisesRegex(ValueError, "hip anchors"):
            observe_pelvis(bad)
        with self.assertRaisesRegex(ValueError, "no portrait rescaling"):
            observe_pelvis(live_report(), profile="portrait_170_78")

    def test_reject_incomplete_malformed_and_forged_inputs(self):
        cases = [
            {} ,
            {**live_report(), "source": "human_nerve_reading"},
            {**live_report(), "balance": {"model_valid": "yes"}},
            {**live_report(), "posture": {"phase": "walk"}},
        ]
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                observe_pelvis(bad)

    def test_nonfinite_tail_and_bad_provenance_are_rejected(self):
        for item in (float("nan"), 1.0, True):
            bad = live_report()
            bad["posture"]["tail_angle_rad"][0] = item
            with self.subTest(value=item), self.assertRaises(ValueError):
                observe_pelvis(bad)
        bad = copy.deepcopy(RECORD)
        bad["record"]["checkpoint_sha256"] = "not a hash"
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            observe_pelvis(bad)

    def test_read_only_input_unmodified_and_reproducible(self):
        frame = live_report()
        saved = copy.deepcopy(frame)
        x = observe_pelvis(frame)
        self.assertEqual(frame, saved)
        self.assertEqual(x, observe_pelvis(frame))
        json.dumps(x, allow_nan=False)
        self.assertFalse(x["sexual_state_inferred"])
        self.assertFalse(x["subjective_state_inferred"])
        self.assertEqual(x["native_cycles_caused"], 0)

    def test_shift_moments_respond_to_com_directions(self):
        left = observe_pelvis(live_report(x=.05, y=.02))
        right = observe_pelvis(live_report(x=-.05, y=-.02))
        self.assertAlmostEqual(left["hip_roll_moment_nm"], -right["hip_roll_moment_nm"])
        self.assertAlmostEqual(left["hip_pitch_moment_nm"], -right["hip_pitch_moment_nm"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
