"""Safety and epistemic checks for Tadash Kimia-ye Khak charter.

These unit tests use fabricated contact measurements, not native MuJoCo.
"""
import tempfile
from pathlib import Path
import json
import unittest

from experiments import tadash_kimia_khak as khak


def event():
    return {"schema": "tadash-contact-observation/1",
            "event_id": "synthetic-contact-test",
            "provenance": "native_mujoco", "contact": True,
            "left_foot_force_n": 300., "right_foot_force_n": 300.,
            "slip_m_per_s": .001, "surface": "flat_simulated_floor"}


class TestKimia(unittest.TestCase):
    def test_poem_is_genuine_and_separate_from_sensor_contract(self):
        charter = khak.load_charter()
        self.assertEqual(charter["literary_anchor"]["ghazal"], 473)
        self.assertEqual(charter["literary_anchor"]["role"],
                         "poetic_and_ethical_metaphor_not_empirical_evidence")
        self.assertFalse(charter["grounding_rules"]["new_action_from_this_charter"])

    def test_bilateral_native_contact_never_becomes_physical_soil(self):
        report = khak.observe(event())
        self.assertEqual(report["contact_claim"],
                         "bilateral_load_on_declared_simulated_floor")
        self.assertFalse(report["physical_soil_touch_established"])
        self.assertFalse(report["conscious_tactile_sensation_established"])
        self.assertEqual(report["motor_commands_emitted"], 0)

    def test_synthetic_fixture_cannot_claim_native_contact(self):
        e = event()
        e["provenance"] = "synthetic_fixture"
        report = khak.observe(e)
        self.assertEqual(report["contact_claim"], "synthetic_fixture_only")

    def test_claim_with_one_foot_loaded_is_modest(self):
        e = event()
        e["right_foot_force_n"] = 0.
        self.assertEqual(khak.observe(e)["contact_claim"], "limited_contact_reported")

    def test_false_contact_cannot_be_reported_as_loaded(self):
        e = event()
        e["contact"] = False
        self.assertEqual(khak.observe(e)["contact_claim"], "contact_not_supported")

    def test_unverified_physical_sensor_cannot_be_impersonated(self):
        e = event()
        e["provenance"] = "physical_sensor"
        with self.assertRaisesRegex(ValueError, "provenance"):
            khak.observe(e)

    def test_actual_soil_label_cannot_be_invented(self):
        e = event()
        e["surface"] = "muddy_soil"
        with self.assertRaisesRegex(ValueError, "terrain"):
            khak.observe(e)

    def test_nan_infinity_bool_and_negative_force_rejected(self):
        for x in [float("nan"), float("inf"), True, -1., 6000.]:
            e = event()
            e["left_foot_force_n"] = x
            with self.subTest(x=x), self.assertRaises(ValueError):
                khak.observe(e)

    def test_missing_fields_rejected(self):
        e = event()
        del e["slip_m_per_s"]
        with self.assertRaisesRegex(ValueError, "fields"):
            khak.observe(e)

    def test_extra_field_fabricating_feeling_rejected(self):
        e = event()
        e["felt_warmth"] = 1.
        with self.assertRaisesRegex(ValueError, "fields"):
            khak.observe(e)

    def test_modified_poem_or_activation_rejected(self):
        contract = khak.load_charter()
        contract["literary_anchor"]["ghazal"] = 463
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "tampered.json"
            p.write_text(json.dumps(contract, ensure_ascii=False))
            with self.assertRaisesRegex(ValueError, "contract"):
                khak.load_charter(p)

    def test_output_has_unknowns_and_no_autonomy(self):
        out = khak.observe(event())
        self.assertIn("texture", out["unknown"])
        self.assertIn("felt_touch", out["unknown"])
        self.assertEqual(out["motor_commands_emitted"], 0)


if __name__ == "__main__":
    unittest.main()
