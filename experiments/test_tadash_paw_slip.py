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

    @unittest.skipUnless(mujoco.__version__.split(".")[0] == "4", "native linvel in the 4.0 comparison")
    def test_native_linvel_crosscheck(self):
        model = mujoco.MjModel.from_xml_string("""<mujoco><worldbody>
        <geom name="ground" type="plane" size="2 2 .1"/>
        <body pos="0 0 .099"><freejoint/><geom name="pad" type="sphere" size=".1"/></body>
        </worldbody><sensor><contact geom1="ground" geom2="pad" data="found linvel"/></sensor></mujoco>""")
        data = mujoco.MjData(model)
        data.qvel[:] = [.03, .04, -.02, 1., 0., 0.]
        mujoco.mj_forward(model, data)
        self.assertEqual(data.sensordata[0], 1)
        via_sensor = float(np.linalg.norm(data.sensordata[2:4]))
        measured = contact_speed(model, data, data.contact[0])
        self.assertAlmostEqual(via_sensor, measured, places=10)
        print(f"sensor_linvel_tangent_m_s={via_sensor:.10f}, jacobian_m_s={measured:.10f}")
