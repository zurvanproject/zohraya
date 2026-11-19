"""Offline static-contact bridge and defensive ritual safety tests."""
import copy
import unittest
from tools import atmosphere_ritual_posture_v03 as p
from tools import atmosphere_defensive_ritual_sim as rituals

class PostureRitualTests(unittest.TestCase):
    def test_actual_existing_contact_fixture_has_three_toes_each(self):
        design, provenance = p.fixture()
        self.assertEqual(provenance["contact_schema"], "tadash-contact-design/0.6")
        self.assertEqual(provenance["toes_each"], 3)
        self.assertTrue(provenance["digitigrade"])
        self.assertEqual({x["id"] for x in design["patches"]}, p.FOOT_IDS)

    def test_three_complete_repetitions_with_static_contact_every_phase(self):
        report = p.round_trip()
        self.assertEqual(report["complete_ritual_runs"], 9)
        self.assertEqual(report["static_contact_checks"], 27)
        self.assertEqual(report["static_contact_passed"], 27)
        self.assertTrue(report["all_passed"])
        self.assertEqual(report["previous_synthetic_security_checks"], 132)
        self.assertEqual(report["previous_synthetic_security_passed"], 132)
        for ritual in rituals.RITUALS:
            one = [r for r in report["rounds"] if r["ritual"] == ritual]
            self.assertEqual([r["round"] for r in one], [1, 2, 3])
            for run in one:
                self.assertEqual([x["phase"] for x in run["phases"]],
                                 ["jing", "qi", "shen"])
                self.assertTrue(all(x["actuation"] == "NO_ACTUATION" for x in run["phases"]))

    def test_static_baseline_uses_eight_contacts_and_positive_margin(self):
        design, _ = p.fixture()
        result = p.contact_probe(design)
        self.assertEqual(result["state"], "STATIC_CANDIDATE")
        self.assertEqual(result["contact_points"], 8)
        self.assertGreaterEqual(result["support_margin_m"], p.MIN_MARGIN_M)
        self.assertLessEqual(result["max_pressure_kpa"], design["pressure_ceiling_kpa"])

    def test_lost_toe_contact_fails_closed(self):
        design, _ = p.fixture()
        result = p.contact_probe(design, inactive={"L": ["toe_3"]})
        self.assertEqual(result["state"], "HOLD_CONTACT_DEGRADED")
        self.assertFalse(result["safe"])

    def test_outside_polygon_never_claims_stable(self):
        design, _ = p.fixture()
        result = p.contact_probe(design, target=(0.9, 0))
        self.assertEqual(result["state"], "HOLD_STATIC_LIMIT")

    def test_missing_trust_is_not_replaced_by_ritual_symbol(self):
        design, _ = p.fixture()
        self.assertEqual(p.contact_probe(design, evidence_valid=False)["state"],
                         "HOLD_EVIDENCE")

    def test_unknown_friction_never_claims_motion_safe(self):
        design, _ = p.fixture()
        self.assertEqual(p.contact_probe(design, friction_known=False)["state"],
                         "HOLD_FRICTION_UNKNOWN")

    def test_excessive_yaw_vetoes_exercise(self):
        design, _ = p.fixture()
        self.assertEqual(p.contact_probe(design, yaw_rad=0.9)["state"],
                         "HOLD_YAW_LIMIT")

    def test_pressure_over_ceiling_cannot_pass(self):
        design, _ = p.fixture()
        actual = p.ContactModel(design)
        class Tampered:
            def solve(self, *args):
                result = actual.solve(*args)
                result["pressure_kpa"]["L_ball"] = design["pressure_ceiling_kpa"] + 25
                return result
        result = p.contact_probe(design, solver=Tampered())
        self.assertEqual(result["state"], "HOLD_STATIC_LIMIT")

    def test_lost_normal_load_cannot_pass(self):
        design, _ = p.fixture()
        actual = p.ContactModel(design)
        class Tampered:
            def solve(self, *args):
                result = actual.solve(*args)
                result["total_normal_N"] -= 25
                return result
        self.assertEqual(p.contact_probe(design, solver=Tampered())["state"],
                         "HOLD_STATIC_LIMIT")

    def test_static_model_unavailable_or_invalid_fails(self):
        design, _ = p.fixture()
        for target in ((float("nan"), 0), (0,), "center"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                p.contact_probe(design, target=target)
        with self.assertRaises(ValueError):
            p.contact_probe(design, inactive={"X": ["toe_2"]})

    def test_stress_has_independent_good_and_bad_cases(self):
        result = p.stress()
        self.assertEqual(result["threats"], 18)
        self.assertEqual(result["passed"], 18)
        self.assertTrue(result["all_passed"])
        self.assertEqual(len({r["fault"] for r in result["by_case"]}), 6)

    def test_no_motion_no_crypto_no_live_atmosphere_claims(self):
        result = p.round_trip()
        self.assertTrue(result["no_body_motion_executed"])
        self.assertTrue(result["not_dynamically_validated"])
        self.assertFalse(result["live_atmosphere_secured"])
        self.assertTrue(result["no_keys_checked"])
        self.assertTrue(result["no_memory_changed"])

    def test_fixture_read_does_not_modify_source(self):
        before = p.CONTACTS.read_bytes(), p.DESIGN.read_bytes(), p.PHENOTYPE.read_bytes()
        p.round_trip()
        self.assertEqual(before, (p.CONTACTS.read_bytes(),
                                  p.DESIGN.read_bytes(),
                                  p.PHENOTYPE.read_bytes()))

    def test_ritual_cues_are_distinct(self):
        self.assertNotEqual(p.HAND_CUES["four_gates"], p.HAND_CUES["quiet_seal"])
        self.assertNotEqual(p.PHASE_COORDS["seven_stars"], p.PHASE_COORDS["quiet_seal"])

if __name__=="__main__":
    unittest.main()
