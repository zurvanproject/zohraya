"""Contact activation and unactuated torque mapping regressions."""
import unittest
import numpy as np
import mujoco
from .resize import SMALL
from .evaluate import load
from .balance import BalanceController
from .stepping import ContactController, can_lift


class ContactControlTests(unittest.TestCase):
    def setUp(self):
        self.model,self.data=load(SMALL)
        balance=BalanceController(self.model)
        self.data.qpos[:]=balance.q0
        self.data.ctrl[:]=balance.u0
        mujoco.mj_forward(self.model,self.data)
        self.controller=ContactController(self.model,self.data)

    def test_joint_torques_only_and_no_state_reset(self):
        m,d,c=self.model,self.data,self.controller
        before=d.qpos.copy()
        torque=c.command(d,c.com0,c.anchors,[True,True])
        np.testing.assert_array_equal(d.qpos,before)
        self.assertTrue(np.all(torque>=m.actuator_ctrlrange[:,0]))
        self.assertTrue(np.all(torque<=m.actuator_ctrlrange[:,1]))
        self.assertTrue(np.all(m.actuator_trnid[:,0]>0))
        self.assertEqual(m.neq,0)
        self.assertTrue(np.all(d.xfrc_applied==0))
        self.assertTrue(np.all(d.qfrc_applied==0))
        self.assertLess(c.max_residual,.01)

    def test_released_foot_has_no_planned_ground_wrench(self):
        c,d=self.controller,self.data
        c.command(d,c.com0,c.anchors,[False,True])
        np.testing.assert_allclose(c.last_wrenches[0],0,atol=1e-4)
        self.assertGreater(c.last_wrenches[1,2],0)
        self.assertFalse(can_lift(d,c,1,np.zeros(2)))

if __name__=='__main__':unittest.main()
