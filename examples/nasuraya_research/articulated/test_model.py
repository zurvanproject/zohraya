"""Mechanical invariants and a real upstream import regression."""
import unittest
import numpy as np
import mujoco,yaml
from .build import OUT
from .evaluate import load,rollout

class ArticulatedTests(unittest.TestCase):
    def test_mass_inertia_and_morphology(self):
        m,d=load();names=[mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,i) for i in range(1,m.nbody)]
        self.assertAlmostEqual(float(m.body_mass.sum()),165.,places=8)
        self.assertTrue(np.all(m.body_inertia[1:]>0))
        self.assertEqual(m.nu,55)
        for side in ['L','R']:
            self.assertEqual(sum(n.startswith('finger_'+side+'_') for n in names),5)
            self.assertEqual(sum(n.startswith('toe_'+side+'_') for n in names),3)
        self.assertEqual(sum(n.startswith('tail_') for n in names),4)

    def test_ground_contact_area_and_no_initial_self_collision(self):
        m,d=load();area={s:0. for s in ['L','R']}
        for g in range(m.ngeom):
            n=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,g)
            if n.startswith(('ball_','toe_pad_')):
                side='L' if '_L' in n else 'R';area[side]+=4*m.geom_size[g,0]*m.geom_size[g,1]
        for a in area.values():self.assertAlmostEqual(a,.03926651524980653,places=10)
        floor=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'floor')
        self.assertTrue(all(floor in [c.geom1,c.geom2] for c in d.contact[:d.ncon]))

    def test_internal_tail_actuation_has_counter_rotation(self):
        fixed=rollout(seconds=.8,zero_g=True);moving=rollout(seconds=.8,zero_g=True,tail_motion=True)
        self.assertAlmostEqual(fixed['root_yaw_final_rad'],0,places=9)
        self.assertLess(moving['root_yaw_final_rad'],-.05)
        self.assertGreater(moving['tail_yaw_final_rad'],.2)
        self.assertEqual(moving['peak_ground_normal_n'],0.)
        self.assertLess(moving['max_physical_subtree_angular_momentum_norm'],.01)

    def test_upstream_prepare_keeps_all_joints(self):
        from wbc_mjlab.robots import custom
        info=custom.inspect_model(OUT/'nasuraya.xml')
        self.assertEqual(info['dof'],55)
        prepared,_=custom.prepare(OUT/'nasuraya.xml');m=prepared.compile()
        self.assertEqual(m.nv,61);self.assertEqual(m.nu,0) # upstream creates its own PD actuators
        self.assertEqual(len(yaml.safe_load((OUT/'robot.yaml').read_text())['joints']),55)

if __name__=='__main__':unittest.main()
