"""Deliberately narrow invariants for offline research, not physical certification."""
import copy
import math
import unittest

from experiments.tadash_body_microbench import (
    EXAMPLE_CONTACTS, EXAMPLE_CP, cardiopulmonary_0d, evidence_card,
    support_margin,
)


class ToeSupportTests(unittest.TestCase):
    def test_com_inside_support_polygon(self):
        out=support_margin(EXAMPLE_CONTACTS,(0,0))
        self.assertEqual(out["status"],"com_inside_contact_hull")
        self.assertGreater(out["signed_margin_m"],0)
        self.assertFalse(out["validated_dynamic_gait"])

    def test_com_outside_has_negative_margin(self):
        out=support_margin(EXAMPLE_CONTACTS,(.9,0))
        self.assertEqual(out["status"],"com_outside_contact_hull")
        self.assertLess(out["signed_margin_m"],0)

    def test_two_toes_cannot_claim_polygon_support(self):
        out=support_margin(EXAMPLE_CONTACTS[:2],(0,0))
        self.assertEqual(out["status"],"insufficient_support_geometry")
        self.assertIsNone(out["signed_margin_m"])

    def test_collinear_toes_fail_closed(self):
        pads=[{"pad":str(i), "x_m":float(i), "y_m":0., "normal_n":2.}
              for i in range(3)]
        self.assertEqual(support_margin(pads,(0,0))["status"],
                         "insufficient_support_geometry")

    def test_low_force_toe_lift_loses_support(self):
        pads=copy.deepcopy(EXAMPLE_CONTACTS)
        for p in pads[2:]:
            p["normal_n"]=0.
        self.assertIsNone(support_margin(pads,(0,0))["signed_margin_m"])

    def test_invalid_nan_duplicate_and_negative_force_rejected(self):
        for broken in (
            [dict(EXAMPLE_CONTACTS[0],x_m=math.nan)]+EXAMPLE_CONTACTS[1:],
            EXAMPLE_CONTACTS+[dict(EXAMPLE_CONTACTS[0])],
            [dict(EXAMPLE_CONTACTS[0],normal_n=-1.)]+EXAMPLE_CONTACTS[1:],
        ):
            with self.subTest(broken=broken[0]):
                with self.assertRaises(ValueError):
                    support_margin(broken,(0,0))


class CardiopulmonaryTests(unittest.TestCase):
    def test_reference_arithmetic(self):
        out=cardiopulmonary_0d(EXAMPLE_CP)
        self.assertAlmostEqual(out["co_l_min"],4.5)
        self.assertAlmostEqual(out["map_proxy_mmHg"],77.)
        self.assertAlmostEqual(out["alveolar_ventilation_l_min"],4.2)
        self.assertAlmostEqual(out["alveolar_pco2_proxy_mmHg"],.863*200/4.2,places=5)
        self.assertIsNone(out["predicted_spo2"])
        self.assertFalse(out["validated_biological_physiology"])

    def test_heart_rate_doubles_co_at_fixed_sv(self):
        cp=dict(EXAMPLE_CP,hr_bpm=120)
        self.assertEqual(cardiopulmonary_0d(cp)["co_l_min"],9.)

    def test_more_alveolar_ventilation_lowers_co2(self):
        cp=dict(EXAMPLE_CP,rr_min=18)
        self.assertLess(cardiopulmonary_0d(cp)["alveolar_pco2_proxy_mmHg"],
                        cardiopulmonary_0d(EXAMPLE_CP)["alveolar_pco2_proxy_mmHg"])

    def test_reject_apnea_nan_deadspace_and_missing_fields(self):
        for broken in (
            dict(EXAMPLE_CP,rr_min=0),
            dict(EXAMPLE_CP,hr_bpm=float("nan")),
            dict(EXAMPLE_CP,dead_space_ml=500),
            {k:v for k,v in EXAMPLE_CP.items() if k!="fio2"},
        ):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    cardiopulmonary_0d(broken)

    def test_report_never_promotes_visual_percent(self):
        card=evidence_card()
        self.assertIsNone(card["body_completion_percent"])
        self.assertFalse(card["visual_image_percent_is_evidence"])
        self.assertTrue(card["no_physical_sensor_or_actuator"])


if __name__ == "__main__":
    unittest.main()
