"""Isolation, bounded actuation and independent promotion-gate regressions."""
from copy import deepcopy
import unittest
import numpy as np
import mujoco
from .balance import BalanceController
from .evaluate import load
from .canon_trial import CANDIDATE
from . import stepping, landing_settle as trial
from .landing_study import comparison, eligible


class LandingControllerTests(unittest.TestCase):
    def test_terminal_change_starts_only_at_last_landing(self):
        for count in (2,6):
            for step in range(count):
                for phase in ('transfer','swing','landing'):
                    if step==count-1 and phase=='landing':continue
                    self.assertEqual(trial.terminal_blend(phase,step,count,.9,1.),0.)
            self.assertEqual(trial.terminal_blend('landing',count-1,count,0.,1.),0.)
            self.assertAlmostEqual(trial.terminal_blend('landing',count-1,count,.5,1.),.5)
            self.assertEqual(trial.terminal_blend('landing',count-1,count,1.,1.),1.)
            self.assertEqual(trial.terminal_blend('recenter',count,count,0.,1.),1.)
            self.assertEqual(trial.terminal_blend('settle',count,count,0.,1.),1.)

    def test_experiment_cannot_load_or_save_native_checkpoints(self):
        for opts in (dict(checkpoint={}),dict(retain_checkpoint=True),dict(geometry_support=False),
                     dict(model_dir='assets/nasuraya_articulated_v02'),dict(mode='automatic')):
            with self.subTest(opts=opts),self.assertRaises(ValueError):trial.walk_trial(**opts)

    def test_disabled_fork_has_identical_torques_and_solver_memory(self):
        m,d=load(CANDIDATE);standing=BalanceController(m,CANDIDATE)
        d.qpos[:]=standing.q0;d.ctrl[:]=standing.u0;mujoco.mj_forward(m,d)
        old=stepping.ContactController(m,d,geometry_support=True)
        new=trial.ContactController(m,d,geometry_support=True)
        for shift in (np.zeros(3),np.array([.003,-.002,0.])):
            a=old.command(d,old.com0+shift,old.anchors,[True,True])
            b=new.command(d,new.com0+shift,new.anchors,[True,True])
            np.testing.assert_array_equal(a,b)
            np.testing.assert_array_equal(old.previous_solution,new.previous_solution)
        self.assertEqual(old.max_residual,new.max_residual)

    def test_tail_task_does_not_reset_state_or_bypass_torque_constraints(self):
        m,d=load(CANDIDATE);standing=BalanceController(m,CANDIDATE)
        d.qpos[:]=standing.q0;d.ctrl[:]=standing.u0;mujoco.mj_forward(m,d)
        c=trial.ContactController(m,d,geometry_support=True);c.tail_blend=1.
        d.qvel[c.tail_dofs]=.06;mujoco.mj_forward(m,d)
        q=d.qpos.copy();v=d.qvel.copy();limits=m.actuator_ctrlrange.copy()
        torque=c.command(d,c.com0,c.anchors,[True,True])
        np.testing.assert_array_equal(d.qpos,q);np.testing.assert_array_equal(d.qvel,v)
        np.testing.assert_array_equal(m.actuator_ctrlrange,limits)
        self.assertTrue(np.all(torque>=limits[:,0]));self.assertTrue(np.all(torque<=limits[:,1]))
        self.assertTrue(np.all(d.xfrc_applied==0));self.assertTrue(np.all(d.qfrc_applied==0))
        self.assertTrue(np.all(m.actuator_trnid[:,0]>0));self.assertEqual(m.neq,0)
        self.assertLessEqual(c.max_residual,.01)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.case=dict(id='one',steps=2)
        self.good=dict(result=dict(walk_pass=True,accepted_steps=2,failure=None,
            final_max_generalized_speed=.001,tilt_rms_deg=1.,simulated_seconds=17.,max_motor_torque_fraction=1.))

    def test_completed_steps_do_not_hide_tail_or_execution_failure(self):
        self.assertTrue(eligible(self.good,self.case))
        for speed in (.05,.066517,float('nan'),float('inf')):
            r=deepcopy(self.good);r['result']['final_max_generalized_speed']=speed
            with self.subTest(speed=speed):self.assertFalse(eligible(r,self.case))
        r=deepcopy(self.good);r['execution_error']='solver error'
        self.assertFalse(eligible(r,self.case))
        r=deepcopy(self.good);r['result']['accepted_steps']=1
        self.assertFalse(eligible(r,self.case))

    def test_mean_improvement_cannot_hide_one_regression(self):
        cases=[dict(id=str(i),steps=2) for i in range(6)]
        plan=dict(holdouts=cases,candidate='combined6')
        rows={}
        for i,case in enumerate(cases):
            rows[(case['id'],'baseline')]=deepcopy(self.good)
            r=deepcopy(self.good);r['result']['tilt_rms_deg']=1.9763 if i==0 else .5
            rows[(case['id'],'combined6')]=r
        result=comparison(plan,rows,'baseline')
        self.assertGreater(result['geometric_mean_rms_reduction'],.05)
        self.assertFalse(result['performance_gate_pass'])

    def test_extra_time_or_bad_baseline_blocks_promotion(self):
        plan=dict(holdouts=[self.case],candidate='combined6')
        base=deepcopy(self.good);candidate=deepcopy(self.good)
        candidate['result']['tilt_rms_deg']=.5
        rows={('one','baseline'):base,('one','combined6'):candidate}
        self.assertTrue(comparison(plan,rows,'baseline')['performance_gate_pass'])
        candidate['result']['simulated_seconds']=17.101
        self.assertFalse(comparison(plan,rows,'baseline')['performance_gate_pass'])
        candidate['result']['simulated_seconds']=17.
        base['result']['final_max_generalized_speed']=.066517
        self.assertFalse(comparison(plan,rows,'baseline')['performance_gate_pass'])

if __name__=='__main__':unittest.main()
