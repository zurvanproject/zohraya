"""Regressions for unactuated equilibrium, actuator indexing, and motor bounds."""
import unittest
import numpy as np
import mujoco
from .resize import SMALL
from .evaluate import load
from .balance import BalanceController


class BalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, _ = load(SMALL)
        cls.controller = BalanceController(cls.model)

    def test_unactuated_equilibrium_forward_dynamics(self):
        m, c = self.model, self.controller
        d = mujoco.MjData(m)
        d.qpos[:] = c.q0
        d.ctrl[:] = c.u0
        mujoco.mj_forward(m,d)
        self.assertLess(np.max(abs(d.qacc)),1e-4)
        self.assertTrue(np.all(m.actuator_trnid[:,0] > 0))
        self.assertEqual(m.neq,0)
        self.assertTrue(np.all(d.xfrc_applied==0))
        self.assertTrue(np.all(d.qfrc_applied==0))

    def test_actuator_mapping_is_not_dof_order(self):
        m,c = self.model,self.controller
        self.assertFalse(np.array_equal(c.va,np.arange(6,m.nv)))
        d = mujoco.MjData(m)
        d.qpos[:] = c.q0
        mujoco.mj_inverse(m,d)
        np.testing.assert_allclose(c.u0,d.qfrc_inverse[c.va],atol=1e-8)

    def test_large_state_error_respects_original_motor_limits(self):
        m,c = self.model,self.controller
        d = mujoco.MjData(m)
        d.qpos[:] = c.q0
        d.qvel[:] = 100.
        before = d.qpos.copy()
        command,saturation = c.command(d)
        self.assertGreater(saturation,0)
        self.assertTrue(np.all(command <= m.actuator_ctrlrange[:,1]))
        self.assertTrue(np.all(command >= m.actuator_ctrlrange[:,0]))
        np.testing.assert_array_equal(before,d.qpos)
        self.assertTrue(np.all(d.xfrc_applied==0))

if __name__=='__main__':unittest.main()
