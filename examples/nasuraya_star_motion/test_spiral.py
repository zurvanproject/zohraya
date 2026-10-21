"""Synthetic geometry, unchanged native guards and continuation contracts."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import math
import unittest

from evaluate_spiral import HERE, spiral_targets, validate_reach
from synthetic_fixture import prepare_defaults, synthetic_body
from extension_state import attach, checkpoint, restore
from posture_step import GaitEnvironment, Inputs


class SpiralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()
        cls.p = json.loads((HERE / 'spiral_protocol.json').read_text())
        cls.origin = synthetic_body().checkpoint()
        cls.feet = {'L':[.196,0.,0.], 'R':[-.196,0.,0.]}

    def body(self):
        from unified_body_v2 import UnifiedBody
        b = UnifiedBody.restore(deepcopy(self.origin))
        return attach(b,dict(star_enabled=True, star_started=dict(L=0,R=0),
            star_targets=spiral_targets(self.feet,'forward',self.p),cursor_semantics='confirmed'))

    def test_spiral_radius_and_angle_progress_together(self):
        plan = spiral_targets(self.feet,'forward',self.p)
        for side in ('L','R'):
            radii, angles = [], []
            for x,y,z in plan[side][:-1]:
                self.assertEqual(z,0.)
                dx,dy=x-self.feet[side][0],y-self.feet[side][1]
                radii.append(math.hypot(dx,dy));angles.append(math.atan2(dy,dx))
            self.assertAlmostEqual(radii[0],.01);self.assertAlmostEqual(radii[-1],.05)
            self.assertTrue(all(b>a for a,b in zip(radii,radii[1:])))
            increments=[(b-a)%(2*math.pi) for a,b in zip(angles,angles[1:])]
            self.assertAlmostEqual(sum(increments),2*math.pi)
            self.assertTrue(all(abs(x-math.pi/3)<1e-12 for x in increments))
            self.assertEqual(plan[side][-1],self.feet[side])

    def test_reverse_is_exact_foot_waypoint_reversal_before_home(self):
        a=spiral_targets(self.feet,'forward',self.p);b=spiral_targets(self.feet,'reverse',self.p)
        for s in self.feet:self.assertEqual(b[s][:-1],a[s][:-1][::-1])

    def test_reach_preflight_and_oversized_rejection(self):
        b=self.body();plan=spiral_targets(self.feet,'forward',self.p)
        validate_reach(self.feet,plan,b.owner.physical.design['max_step_length_m'])
        plan['L'][0][1]=1.
        with self.assertRaises(ValueError):validate_reach(self.feet,plan,b.owner.physical.design['max_step_length_m'])
        with self.assertRaises(ValueError):spiral_targets(self.feet,'other',self.p)

    def test_no_stock_change_on_attach_and_next_cycle_restore_equality(self):
        a=self.body();self.assertEqual(a.checkpoint(),self.origin)
        b=restore(json.loads(json.dumps(checkpoint(a))))
        kw=dict(event_id='synthetic-spiral-resume',
            at_utc=(datetime.fromisoformat(a.owner.wall_utc)+timedelta(seconds=1)).isoformat(),
            duration_s=1.,requested='walk',expected_revision=a.revision,external={})
        t=a.owner.physical.state.time_s;fuel=a.owner.owner.body.state.fuel_J
        ra=a.cycle(**kw);rb=b.cycle(**kw)
        self.assertEqual(ra,rb);self.assertEqual(checkpoint(a),checkpoint(b))
        self.assertAlmostEqual(a.owner.physical.state.time_s-t,1.)
        self.assertAlmostEqual(fuel-a.owner.owner.body.state.fuel_J,sum(f['fuel_used_J'] for f in ra['trace']),places=6)

    def test_spiral_still_obeys_friction_failure(self):
        q=self.body().owner.physical
        f=q.step(GaitEnvironment(body=Inputs(dt_s=.1),command='stand',
            friction={'L':0.,'R':0.},external_impulse_N_s=[8.,4.]))
        self.assertFalse(f['balance']['model_valid'])
        self.assertEqual(q.state.failed_reason,'friction_limit_exceeded')
        self.assertEqual(q.star_started,dict(L=0,R=0))

    def test_safety_latch_is_not_cleared(self):
        q=self.body().owner.physical
        f=q.step(GaitEnvironment(body=Inputs(dt_s=.1,stimuli={'calf_L':{'damage':.9}}),command='stand'))
        self.assertFalse(f['balance']['model_valid'])
        self.assertTrue(q.body.state.latched['ankle_L'])


if __name__=='__main__':unittest.main()
