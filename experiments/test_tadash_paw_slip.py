import unittest
import numpy as np
import mujoco

from experiments.tadash_paw_slip import PawSlip, contact_speed


class SlipTests(unittest.TestCase):
    def setUp(self):
        self.m = mujoco.MjModel.from_xml_string("""<mujoco><worldbody>
        <geom type="plane" size="2 2 .1"/>
        <body pos="0 0 .099"><freejoint/><geom name="ball_L" type="sphere" size=".1"/></body>
        </worldbody></mujoco>""")
        self.d = mujoco.MjData(self.m)

    def test_only_tangent_counts(self):
        self.d.qvel[:3] = [.03, .04, -.2]
        mujoco.mj_forward(self.m, self.d)
        self.assertEqual(self.d.ncon, 1)
        self.assertAlmostEqual(contact_speed(self.m, self.d, self.d.contact[0]), .05)
        self.d.qvel[:2] = 0
        mujoco.mj_forward(self.m, self.d)
        self.assertAlmostEqual(contact_speed(self.m, self.d, self.d.contact[0]), 0.)

    def test_rotation_includes_lever_arm(self):
        self.d.qvel[3] = 1.
        mujoco.mj_forward(self.m, self.d)
        c = self.d.contact[0]
        omega_cross_r = np.cross([1,0,0], c.pos - self.d.xpos[1])
        self.assertGreater(contact_speed(self.m, self.d, c), .09)
        self.assertAlmostEqual(contact_speed(self.m, self.d, c), np.linalg.norm(omega_cross_r[:2]))

    def test_unloaded_is_missing(self):
        mujoco.mj_forward(self.m, self.d)
        wrench = np.zeros(6)
        mujoco.mj_contactForce(self.m, self.d, 0, wrench)
        observer = PawSlip()
        observer.sample(self.m, self.d, [wrench[0], 0.])
        self.assertIsNone(observer.rows[0][3])
        with self.assertRaisesRegex(ValueError, "right"):
            observer.result()
