"""Independent target/pressure checks for the isolated morphology experiment."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import mujoco
from .canon_trial import build_candidate, audit
from .evaluate import load
from .balance import BalanceController
from .stepping import ContactController, walk_trial
from .support_geometry import support_bounds
from .resize import SMALL


class CanonTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.folder=build_candidate(Path(cls.tmp.name))
        cls.model,_=load(cls.folder)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_target_dimensions_and_appendage_counts(self):
        r=audit(self.folder)
        for name,value in [('mass_kg',78.),('crown_height_m',1.70),
                           ('horn_upper_bound_m',1.92),('tail_centerline_length_m',.85)]:
            self.assertAlmostEqual(r[name],value,places=8)
        self.assertEqual(r['fingers_per_hand'],{'L':5,'R':5})
        self.assertEqual(r['toes_per_foot'],{'L':3,'R':3})
        self.assertEqual(r['actuated_joints'],55)
        self.assertTrue(r['positive_inertias'])
        self.assertEqual(r['initial_self_collisions'],[])

    def test_rebuild_deterministic_and_parent_unchanged(self):
        parent=(SMALL/'nasuraya.xml').read_bytes()
        before=(self.folder/'nasuraya.xml').read_bytes()
        build_candidate(self.folder)
        self.assertEqual(before,(self.folder/'nasuraya.xml').read_bytes())
        self.assertEqual(parent,(SMALL/'nasuraya.xml').read_bytes())

    def test_old_pressure_bounds_overhang_new_pad(self):
        self.assertGreater(audit(self.folder)['legacy_bound_max_overshoot_m'],.004)
        m=self.model; bounds=support_bounds(m)
        for row,side in zip(bounds,('L','R')):
            g=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'ball_'+side)
            s=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_SITE,'foot_contact_'+side)
            center=m.geom_pos[g]-m.site_pos[s]
            for x in row[:2]:
                for y in row[2:]:
                    self.assertLess(abs(x-center[0]),m.geom_size[g,0])
                    self.assertLess(abs(y-center[1]),m.geom_size[g,1])

    def test_proposed_wrench_pressure_stays_inside_pad(self):
        m,d=load(self.folder);b=BalanceController(m,self.folder)
        d.qpos[:]=b.q0;d.ctrl[:]=b.u0;mujoco.mj_forward(m,d)
        c=ContactController(m,d,geometry_support=True)
        before=d.qpos.copy()
        for dx,dy in [(0,0),(-.02,.02),(.02,-.02)]:
            torque=c.command(d,c.com0+[dx,dy,0],c.anchors,[True,True])
            for wrench,bounds in zip(c.last_wrenches,c.support_bounds):
                if wrench[2]>1:
                    x=-wrench[4]/wrench[2];y=wrench[3]/wrench[2]
                    self.assertTrue(bounds[0]-1e-5<=x<=bounds[1]+1e-5)
                    self.assertTrue(bounds[2]-1e-5<=y<=bounds[3]+1e-5)
            self.assertTrue(np.all(torque>=m.actuator_ctrlrange[:,0]))
            self.assertTrue(np.all(torque<=m.actuator_ctrlrange[:,1]))
        np.testing.assert_array_equal(before,d.qpos)
        self.assertTrue(np.all(d.xfrc_applied==0))
        self.assertTrue(np.all(d.qfrc_applied==0))
        self.assertEqual(m.neq,0)

    def test_rotated_contact_frame_rejected(self):
        m,_=load(self.folder)
        g=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'ball_L')
        m.geom_quat[g]=[.70710678,0,0,.70710678]
        with self.assertRaises(ValueError):support_bounds(m)

    def test_unintegrated_checkpoint_is_explicitly_rejected(self):
        with self.assertRaises(ValueError):
            walk_trial(model_dir=self.folder,retain_checkpoint=True)
        with self.assertRaises(ValueError):
            walk_trial(geometry_support=True,retain_checkpoint=True)


if __name__=='__main__':unittest.main()
