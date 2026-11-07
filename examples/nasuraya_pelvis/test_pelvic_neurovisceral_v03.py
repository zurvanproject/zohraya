"""Acceptance tests for optional read-only neurovisceral pelvic sidecar."""
import copy
import json
import unittest
from runtimes.tadash_body.pelvic_neurovisceral_v03 import assess_neurovisceral_pelvis


class NeurovisceralPelvisV03Tests(unittest.TestCase):
    def test_default_portrait_and_runtime_are_separate(self):
        portrait = assess_neurovisceral_pelvis(intra_abdominal_pressure_kpa=5., floor_activation=0.)
        runtime = assess_neurovisceral_pelvis(profile="runtime_250_195", intra_abdominal_pressure_kpa=5., floor_activation=0.)
        self.assertEqual((portrait["stature_m"], portrait["mass_kg"]), (1.7, 78.))
        self.assertEqual((runtime["stature_m"], runtime["mass_kg"]), (2.5, 195.))
        self.assertNotEqual(portrait["pelvic_floor"], runtime["pelvic_floor"])

    def test_somatic_and_visceral_channels_are_not_conflated(self):
        low = assess_neurovisceral_pelvis(pudendal_left=0, pudendal_right=0)
        high = assess_neurovisceral_pelvis(pudendal_left=1, pudendal_right=1)
        self.assertLess(low["somatic"]["external_sphincter_support_proxy"],
                        high["somatic"]["external_sphincter_support_proxy"])
        self.assertEqual(low["autonomic"], high["autonomic"])

    def test_sacral_parasympathetic_changes_visceral_not_somatic(self):
        lo = assess_neurovisceral_pelvis(sacral_parasympathetic=0)
        hi = assess_neurovisceral_pelvis(sacral_parasympathetic=1)
        self.assertLess(lo["autonomic"]["detrusor_drive_proxy"],
                        hi["autonomic"]["detrusor_drive_proxy"])
        self.assertEqual(lo["somatic"], hi["somatic"])

    def test_sympathetic_changes_vasomotor_not_detrusor(self):
        lo = assess_neurovisceral_pelvis(hypogastric_sympathetic=0)
        hi = assess_neurovisceral_pelvis(hypogastric_sympathetic=1)
        self.assertLess(lo["autonomic"]["pelvic_vasomotor_proxy"],
                        hi["autonomic"]["pelvic_vasomotor_proxy"])
        self.assertEqual(lo["autonomic"]["detrusor_drive_proxy"],
                         hi["autonomic"]["detrusor_drive_proxy"])

    def test_vagina_and_uterus_independent_observation_only(self):
        lo = assess_neurovisceral_pelvis(uterine_activity=0, vaginal_wall_load=.2)
        hi = assess_neurovisceral_pelvis(uterine_activity=1, vaginal_wall_load=.2)
        self.assertEqual(lo["viscera"]["vaginal_wall_load_proxy"],
                         hi["viscera"]["vaginal_wall_load_proxy"])
        self.assertNotEqual(lo["viscera"]["uterine_activity_proxy"],
                            hi["viscera"]["uterine_activity_proxy"])
        self.assertFalse(hi["reproductive_function_verified"])

    def test_overloaded_floor_fails_closed(self):
        out = assess_neurovisceral_pelvis(profile="runtime_250_195",
                  intra_abdominal_pressure_kpa=25, floor_activation=0)
        self.assertEqual(out["guard"], "review_required")
        self.assertIn("synthetic_floor_load_limit", out["guard_reasons"])
        self.assertGreater(out["pelvic_floor"]["residual_load_n"], 0)

    def test_high_fill_low_somatic_control_reports_attention(self):
        out = assess_neurovisceral_pelvis(pudendal_left=0,
               pudendal_right=0, floor_activation=0, bladder_fill=.95)
        self.assertIn("low_synthetic_somatic_control_reserve_at_high_fill", out["guard_reasons"])

    def test_unbalanced_bilateral_pudendal_detected(self):
        out = assess_neurovisceral_pelvis(pudendal_left=1, pudendal_right=0)
        self.assertIn("marked_paired_somatic_asymmetry", out["guard_reasons"])

    def test_tail_load_competing_with_floor_is_not_claimed_safe(self):
        out = assess_neurovisceral_pelvis(profile="runtime_250_195",
              tail_root_load=1, intra_abdominal_pressure_kpa=8, floor_activation=0)
        self.assertEqual(out["guard"], "review_required")
        self.assertIn("tail_load_and_floor_strain_compete_clearance_unverified", out["guard_reasons"])
        self.assertFalse(out["anatomical_clearance_validated"])

    def test_vagus_cannot_become_a_pelvic_actuator(self):
        out = assess_neurovisceral_pelvis()
        self.assertIsNone(out["autonomic"]["vagal_direct_transfer"])
        self.assertEqual(out["pathways"]["vagus_CN_X"]["effect_in_this_model"], "none")
        with self.assertRaisesRegex(ValueError, "vagus-to-pelvis"):
            assess_neurovisceral_pelvis(vagus_direct_to_pelvis=.4)

    def test_bad_nonfinite_bool_and_bogus_inputs_rejected(self):
        for kwargs in ({"pudendal_left": float("nan")}, {"bladder_fill": float("inf")},
                       {"tail_root_load": True}, {"uterine_activity": -1},
                       {"vaginal_wall_load": "0.1"}, {"profile": "fake"},
                       {"intra_abdominal_pressure_kpa": True},
                       {"intra_abdominal_pressure_kpa": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                assess_neurovisceral_pelvis(**kwargs)

    def test_snapshot_rejects_cross_scale(self):
        with self.assertRaisesRegex(ValueError, "cannot be rescaled"):
            assess_neurovisceral_pelvis(posture_snapshot={"source":"fake"})

    def test_runtime_posture_snapshot_is_read_only(self):
        snapshot = {
            "source": "posture_step_v06_report",
            "posture": {"phase": "shift", "com_m": [.01, 0],
                        "tail_angle_rad": [0, 0],
                        "kinematics": {
                            "L": {"joints_m": {"hip": [.15, 0, 1.42]}},
                            "R": {"joints_m": {"hip": [-.13, 0, 1.42]}},
                        }},
            "balance": {"model_valid": True, "capture_margin_m": .01},
        }
        saved = copy.deepcopy(snapshot)
        out = assess_neurovisceral_pelvis(profile="runtime_250_195", posture_snapshot=snapshot)
        self.assertEqual(snapshot, saved)
        self.assertEqual(out["posture_phase"], "shift")
        self.assertEqual(out["native_cycles_caused"], 0)
        self.assertFalse(out["actuation_authorized"])

    def test_report_cannot_mutate_global_anatomy(self):
        a = assess_neurovisceral_pelvis()
        a["pathways"]["pudendal_somatic_S2_S4"]["class"] = "changed"
        b = assess_neurovisceral_pelvis()
        self.assertEqual(b["pathways"]["pudendal_somatic_S2_S4"]["class"], "somatic_sensory_motor")

    def test_deterministic_json_safe_and_non_subjective(self):
        x = assess_neurovisceral_pelvis()
        self.assertEqual(x, assess_neurovisceral_pelvis())
        json.dumps(x, allow_nan=False)
        self.assertFalse(x["sexual_state_inferred"])
        self.assertFalse(x["subjective_sensation_inferred"])
        self.assertFalse(x["clinical_validity"])
        self.assertEqual(x["native_cycles_caused"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
