"""Trust-boundary, contact-hull and synthetic-learning regression tests."""
from dataclasses import replace
import math
import unittest
from examples.nasuraya_proprioception.engine import (
    Foot, Packet, assess, convex_hull, signed_margin, SOURCE, SCHEMA
)
from examples.nasuraya_proprioception.benchmark import evaluate


def foot(side, *, contact=(True, True, True), normal=383.0, mu=0.8,
         tangent=(5.0, 2.0)):
    y = 0.105 if side == "left" else -0.105
    positions = ((0.00, y - 0.045), (0.09, y), (0.00, y + 0.045))
    return Foot(positions, contact, normal, tangent, mu)


def packet(**updates):
    fields = dict(timestamp_ms=100, dt_s=0.02, source_type=SOURCE,
        com_xyz_m=(0.025, 0.0, 0.954), velocity_xyz_m_s=(0, 0, 0),
        gravity_xyz_m_s2=(0, 0, -9.81),
        left=foot("left"), right=foot("right"))
    fields.update(updates)
    return Packet(**fields)


class ProprioceptionReview(unittest.TestCase):
    def test_actual_convex_hull_not_bounding_rectangle(self):
        p = ((0, 0), (1, 0), (0, 1))
        h = convex_hull(p)
        self.assertEqual(len(h), 3)
        self.assertGreater(signed_margin((0.1, 0.1), h), 0)
        # This point lies inside the rectangle but outside the triangle.
        self.assertLess(signed_margin((0.9, 0.9), h), 0)

    def test_baseline_has_support_but_no_actuation(self):
        out = assess(packet())
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["action_advisory"], "OBSERVE_ONLY")
        self.assertFalse(out["motion_execution"])
        self.assertGreater(out["signed_margin_m"], 0)
        self.assertEqual(len(out["support_polygon_xy_m"]), 4)

    def test_commanded_motion_is_not_authorized(self):
        out = assess(packet(), intent="STEP")
        self.assertEqual(out["action_advisory"], "DENY_MOTION")
        self.assertIn("NO_AUTHORIZED_MOTOR_ACTUATOR", out["reasons"])

    def test_unknown_joint_torque_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            assess(packet(), requested_torques_nm={"UNSPECIFIED_JOINT": 1})

    def test_over_torque_fails_closed(self):
        out = assess(packet(), requested_torques_nm={"TAIL_PITCH": 99.0})
        self.assertIn("JOINT_TORQUE_LIMIT", out["reasons"])
        self.assertEqual(out["action_advisory"], "DENY_MOTION")

    def test_joint_rom_fails_closed(self):
        out = assess(packet(joint_angles_deg={"ANKLE_L": 100.0}))
        self.assertIn("JOINT_ROM_LIMIT", out["reasons"])

    def test_nonfinite_inputs_rejected(self):
        for updates in [
            {"dt_s": math.nan}, {"timestamp_ms": math.inf},
            {"com_xyz_m": (0, math.nan, 1.0)},
            {"sensor_delay_ms": math.nan},
            {"gravity_xyz_m_s2": (0, 0, math.inf)},
            {"joint_angles_deg": {"TAIL_PITCH": math.nan}},
        ]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                assess(packet(**updates))
        with self.assertRaises(ValueError):
            assess(packet(), requested_torques_nm={"TAIL_PITCH": math.nan})

    def test_false_sensor_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "synthetic"):
            assess(packet(source_type="REAL_ACCELEROMETER"))

    def test_no_contacts_denies(self):
        air = foot("left", contact=(False, False, False), normal=0.0)
        out = assess(packet(left=air, right=air))
        self.assertIn("NO_VALID_SUPPORT_POLYGON", out["reasons"])
        self.assertIsNone(out["signed_margin_m"])

    def test_just_one_contact_point_denies(self):
        alone = foot("left", contact=(False, True, False))
        air = foot("right", contact=(False, False, False), normal=0)
        out = assess(packet(left=alone, right=air))
        self.assertIn("NO_VALID_SUPPORT_POLYGON", out["reasons"])

    def test_tilted_gravity_unmodelled(self):
        out = assess(packet(gravity_xyz_m_s2=(2.5, -1.2, -9.4)))
        self.assertIn("UNSUPPORTED_TILTED_GRAVITY", out["reasons"])
        self.assertIsNone(out["xcom_xy_m"])

    def test_stale_sensor_rejected(self):
        out = assess(packet(sensor_delay_ms=120))
        self.assertIn("STALE_SENSOR", out["reasons"])

    def test_high_slip_denies_without_safety_claim(self):
        slippery = foot("right", mu=0.15, tangent=(90, 0))
        out = assess(packet(right=slippery))
        self.assertIn("FRICTION_CONE_VIOLATION", out["reasons"])

    def test_xcom_outside_support(self):
        out = assess(packet(com_xyz_m=(0.45, 0, 0.954)))
        self.assertLess(out["signed_margin_m"], 0)
        self.assertIn("XCOM_OUTSIDE_SUPPORT", out["reasons"])

    def test_no_friction_does_not_divide_by_zero(self):
        slippery = foot("right", mu=0)
        out = assess(packet(right=slippery))
        self.assertIsNone(out["slip_ratio_max"])
        self.assertIn("FRICTION_CONE_VIOLATION", out["reasons"])

    def test_invalid_foot_mismatch_rejected(self):
        invalid = foot("left", contact=(False, False, False))
        with self.assertRaises(ValueError):
            assess(packet(left=invalid))

    def test_benchmark_recomputed_from_unseen_samples(self):
        result = evaluate()
        self.assertEqual(result["training_samples"], 240)
        self.assertEqual(result["heldout_samples"], 80)
        self.assertLess(result["post_holdout_rmse_mm"], result["pre_holdout_rmse_mm"])
        self.assertGreater(result["improvement_pct"], 40)
        self.assertFalse(result["real_proprioception"])

    def test_no_hidden_state_changes(self):
        p = packet()
        a = assess(p)
        b = assess(p)
        self.assertEqual(a, b)
        self.assertEqual(p.com_xyz_m, (0.025, 0.0, 0.954))


if __name__ == "__main__":
    unittest.main(verbosity=2)
