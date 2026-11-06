"""Numerical invariants, symmetry, rejection semantics and recovery tests."""
import unittest
from dataclasses import asdict,replace
import math
import numpy as np
from .running_balance import Profile,Apex,Runner,simulate


class RunningBalanceTests(unittest.TestCase):
    def test_matches_prior_planar_periodic_hop(self):
        p=Profile();s=Apex(0,0,1.45,3,0)
        r=simulate(p,s,[math.sin(math.radians(14.092118477551246)),0,0],detailed=True)
        self.assertTrue(r['ok'])
        self.assertAlmostEqual(r['state']['z'],1.45,places=6)
        self.assertAlmostEqual(r['state']['vx'],3.,places=6)
        self.assertAlmostEqual(r['stance_s'],.23951193260868153,places=6)
        self.assertLess(r['metrics']['work_energy_relative_error'],1e-6)

    def test_actuator_work_explains_energy_change(self):
        p=Profile();s=Apex(0,0,p.apex,3,.2)
        for u in [-.1,.1]:
            r=simulate(p,s,[.24,.08,u],detailed=True)
            self.assertTrue(r['ok']);t=r['state']
            e0=p.mass_kg*(p.gravity*s.z+.5*(s.vx**2+s.vy**2))
            e1=p.mass_kg*(p.gravity*t['z']+.5*(t['vx']**2+t['vy']**2))
            self.assertAlmostEqual(e1-e0,r['actuator_work_j'],delta=.02)
            self.assertGreater(r['actuator_work_j']*u,0.)

    def test_lateral_mirror_symmetry(self):
        p=Profile();s=Apex(0,.01,p.apex,3,.2)
        left=simulate(p,s,[.24,.08,.01])
        right=simulate(p,replace(s,y=-s.y,vy=-s.vy,side=-1),[.24,-.08,.01])
        self.assertTrue(left['ok'] and right['ok'])
        for key in ['x','z','vx']:self.assertAlmostEqual(left['state'][key],right['state'][key],places=7)
        for key in ['y','vy']:self.assertAlmostEqual(left['state'][key],-right['state'][key],places=7)

    def test_rejected_contact_does_not_advance_state(self):
        r=Runner(replace(Profile(),friction=.01));before=asdict(r.state);guess=r.guess.copy()
        f=r.step()
        self.assertFalse(f['ok']);self.assertIn('friction_limit',f['violations'])
        self.assertEqual(asdict(r.state),before);self.assertEqual(r.time,0.);self.assertEqual(r.feet,{})
        np.testing.assert_array_equal(r.guess,guess)

    def test_feedback_recovers_mixed_disturbance(self):
        r=Runner(Profile());r.state=replace(r.state,z=r.state.z+.01,vx=3.1,vy=.3)
        for _ in range(12):
            f=r.step();self.assertTrue(f['ok'],f)
        self.assertLess(abs(r.state.z-r.profile.apex),.002)
        self.assertLess(abs(r.state.vx-3),.01)
        self.assertLess(abs(r.state.y),.01)

if __name__=='__main__':unittest.main()
