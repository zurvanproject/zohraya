"""Regression and injected-defect tests for the read-only v03 connection gate."""
import copy
import unittest
import xml.etree.ElementTree as ET

from experiments.tadash_connection_audit import MODEL, audit_tree, audit_native


class ConnectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = ET.parse(MODEL).getroot()

    def mutated(self, change, expected_failure):
        candidate = copy.deepcopy(self.reference)
        change(candidate)
        receipt = audit_tree(candidate)
        self.assertFalse(receipt["pass"])
        self.assertIn(expected_failure, receipt["failures"])

    def test_original_has_complete_authored_rigid_topology(self):
        result = audit_tree(self.reference)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["pass"])
        self.assertEqual(result["metrics"]["actuated_joints"], 55)
        self.assertEqual(result["metrics"]["tail_segments"], 4)

    def test_detached_thigh_parent_fails(self):
        def mutate(r):
            pelvis = r.find(".//body[@name='pelvis']")
            thigh = pelvis.find("body[@name='thigh_L']")
            pelvis.remove(thigh)
            pelvis.find("body[@name='torso']").append(thigh)
        self.mutated(mutate, "parent:thigh_L")

    def test_detached_head_parent_fails(self):
        def mutate(r):
            pelvis = r.find(".//body[@name='pelvis']")
            torso = pelvis.find("body[@name='torso']")
            head = torso.find("body[@name='head']")
            torso.remove(head)
            pelvis.append(head)
        self.mutated(mutate, "parent:head")

    def test_wrong_shin_parent_fails(self):
        def mutate(r):
            thigh = r.find(".//body[@name='thigh_R']")
            shin = thigh.find("body[@name='shin_R']")
            thigh.remove(shin)
            r.find(".//body[@name='pelvis']").append(shin)
        self.mutated(mutate, "parent:shin_R")

    def test_missing_toe_fails(self):
        def mutate(r):
            foot = r.find(".//body[@name='foot_L']")
            foot.remove(foot.find("body[@name='toe_L_3']"))
        self.mutated(mutate, "three_toes:L")

    def test_unwanted_fourth_toe_fails(self):
        def mutate(r):
            r.find(".//body[@name='foot_R']").append(
                ET.Element("body", name="toe_R_4", pos="0 0 0"))
        self.mutated(mutate, "three_toes:R")

    def test_missing_toe_hinge_fails(self):
        def mutate(r):
            toe = r.find(".//body[@name='toe_R_2']")
            toe.remove(toe.find("joint"))
        self.mutated(mutate, "toe_joint:R:2")

    def test_missing_toe_pad_fails(self):
        def mutate(r):
            toe = r.find(".//body[@name='toe_L_1']")
            toe.remove(toe.find("geom"))
        self.mutated(mutate, "toe_pad:L:1")

    def test_foot_contact_site_wrong_body_fails(self):
        def mutate(r):
            foot = r.find(".//body[@name='foot_L']")
            site = foot.find("site[@name='foot_contact_L']")
            foot.remove(site)
            r.find(".//body[@name='thigh_L']").append(site)
        self.mutated(mutate, "contact_site_on_foot:L")

    def test_tail_link_socket_gap_fails(self):
        def mutate(r):
            r.find(".//body[@name='tail_3']").set("pos", "-0.3 0 -0.0359512491768")
        self.mutated(mutate, "tail_link_seam:2->3")

    def test_tail_tip_gap_fails(self):
        def mutate(r):
            r.find(".//site[@name='tail_tip']").set("pos", "-0.4 0 0")
        self.mutated(mutate, "tail_tip_seam")

    def test_tail_length_mismatch_fails(self):
        def mutate(r):
            r.find(".//geom[@name='tail_geom_4']").set("fromto", "0 0 0 -0.4 0 0")
        self.mutated(mutate, "tail_length_0p85m")

    def test_horn_join_gap_fails(self):
        def mutate(r):
            r.find(".//geom[@name='horn_L_1']").set(
                "fromto", "-0.2 0.0748 0.257934285714 -0.068 0.0748 0.35642")
        self.mutated(mutate, "horn_seam:L:0->1")

    def test_missing_horn_segment_fails(self):
        def mutate(r):
            head = r.find(".//body[@name='head']")
            head.remove(head.find("geom[@name='horn_R_2']"))
        self.mutated(mutate, "horn_rigid_geoms_on_head:R")

    def test_motor_deletion_fails(self):
        def mutate(r):
            actuator = r.find("actuator")
            actuator.remove(actuator.find("motor[@joint='hip_pitch_L']"))
        self.mutated(mutate, "motor_joint_bijection")

    def test_motor_collision_fails(self):
        def mutate(r):
            actuator = r.find("actuator")
            actuator.append(copy.deepcopy(actuator.find("motor[@joint='hip_pitch_L']")))
        self.mutated(mutate, "motor_joint_bijection")

    def test_unbounded_motor_fails(self):
        def mutate(r):
            r.find(".//motor[@joint='knee_R']").set("ctrllimited", "false")
        self.mutated(mutate, "bounded_motor:knee_R")

    def test_invalid_joint_axis_fails(self):
        def mutate(r):
            r.find(".//joint[@name='knee_L']").set("axis", "0 0 0")
        self.mutated(mutate, "hinge_axis:knee_L")

    def test_nan_joint_limit_fails(self):
        def mutate(r):
            r.find(".//joint[@name='mtp_L']").set("range", "nan 0.7")
        self.mutated(mutate, "finite_range:mtp_L")

    def test_negative_mass_fails(self):
        def mutate(r):
            r.find(".//geom[@name='ball_L']").set("mass", "-1")
        self.mutated(mutate, "positive_explicit_geom_mass:ball_L")

    def test_total_mass_change_fails(self):
        def mutate(r):
            r.find(".//geom[@name='pelvis_mass']").set("mass", "10")
        self.mutated(mutate, "authored_mass_78kg")

    def test_duplicate_joint_name_fails(self):
        def mutate(r):
            r.find(".//joint[@name='toe_flex_L_3']").set("name", "toe_flex_L_2")
        self.mutated(mutate, "unique_joint_names")

    def test_native_mujo_co_kinematic_probes(self):
        try:
            import mujoco  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("MuJoCo/Numpy unavailable; CI installs them")
        receipt = audit_native(MODEL)
        self.assertTrue(receipt["pass"], receipt)
        self.assertEqual(receipt["metrics"]["native_nu"], 55)


if __name__ == "__main__":
    unittest.main()
