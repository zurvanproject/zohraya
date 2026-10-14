"""Guarded transfer regression using an externally supplied pre-veto state."""
import json
import os
from pathlib import Path
import sys
import unittest
from copy import deepcopy

sys.path.insert(0,os.environ.get('NASURAYA_NATIVE_ROOT',str(Path(__file__).resolve().parents[2]/'runtimes/tadash_body')))
from unified_body_v2 import UnifiedBody
from posture_step import GaitEnvironment, Inputs
from coordinated_support import CoordinatedSupport
from extension_state import StarMotion, attach, checkpoint, restore
from run_bounded_route import route_targets


class StopOnlyStar(StarMotion):
    """PR #17 prediction scope; native limits and selection remain unchanged."""
    def _needs_support_prediction(self,e):
        q=self.state.swing
        return e.command=='stand' or self.state.phase=='settle' or (q is not None and q['kind']=='walk' and q['progress']>.85)


class TransferPolicyTests(unittest.TestCase):
    def test_feasible_nominal_transfer_is_not_changed(self):
        a=CoordinatedSupport();b=deepcopy(a);b.__class__=StopOnlyStar
        a.state.phase=b.state.phase='shift'
        e=GaitEnvironment(body=Inputs(dt_s=.1),command='walk')
        fa=a.step(e);fb=b.step(e)
        self.assertTrue(fa['balance']['model_valid'])
        self.assertEqual(fa,fb)
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_routes_have_identical_home_radius_and_reverse_order(self):
        feet={'L':[.196,0.,0.],'R':[-.196,0.,0.]}
        forward=route_targets(feet,'forward');reverse=route_targets(feet,'reverse')
        for side in ('L','R'):
            self.assertEqual(reverse[side][:-1],list(reversed(forward[side][:-1])))
            self.assertEqual(forward[side][-1],feet[side])
        with self.assertRaises(ValueError):route_targets(feet,'unknown')


@unittest.skipUnless(os.environ.get('NASURAYA_TRANSFER_FIXTURE'),'external pre-veto fixture required')
class RecordedTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=json.loads(Path(os.environ['NASURAYA_TRANSFER_FIXTURE']).read_text())

    def body(self,legacy=False):
        b=UnifiedBody.restore(self.source['body']);native=b.checkpoint()
        attach(b,self.source['controller'])
        self.assertEqual(b.checkpoint(),native)
        if legacy:b.owner.physical.__class__=StopOnlyStar
        return b

    def advance(self,b):
        return b.cycle(**deepcopy(self.source['cycle']))

    def test_veto_cause_and_confirmed_landing_with_unchanged_native_selector(self):
        a=self.body(True);ra=self.advance(a)
        old_walk=next(c for c in ra['owner']['candidates'] if c['action']=='walk')
        self.assertFalse(old_walk['model_valid'])
        self.assertEqual(ra['owner']['selected_action'],'slow_breath')
        self.assertEqual(a.owner.physical.star_started,{'L':1,'R':1})
        b=self.body();rb=self.advance(b)
        new_walk=next(c for c in rb['owner']['candidates'] if c['action']=='walk')
        self.assertTrue(new_walk['model_valid'])
        self.assertEqual(rb['owner']['selected_action'],'walk')
        self.assertTrue(rb['owner']['physical_model_valid'])
        self.assertEqual(b.owner.physical.star_started,{'L':1,'R':2})
        self.assertEqual(b.owner.physical.state.walk_steps,3)
        self.assertGreaterEqual(b.owner.physical.last['contact']['joint_support_fraction'],.999)

    def test_cold_restore_and_prediction_charging(self):
        a=self.body();b=restore(json.loads(json.dumps(checkpoint(a))))
        start_time=a.owner.physical.state.time_s;fuel=a.owner.owner.body.state.fuel_J
        ra=self.advance(a);rb=self.advance(b)
        self.assertEqual(ra,rb)
        self.assertEqual(checkpoint(a),checkpoint(b))
        self.assertAlmostEqual(a.owner.physical.state.time_s-start_time,1.)
        self.assertEqual(ra['owner_ticks'],10)
        self.assertAlmostEqual(fuel-a.owner.owner.body.state.fuel_J,sum(f['fuel_used_J'] for f in ra['trace']),places=6)
        self.assertLess(ra['whole_body_audit']['energy_error_J'],5e-5)
        self.assertLess(ra['whole_body_audit']['water_error_L'],1e-8)

    def test_declared_high_sleep_copy_retains_native_walk_veto(self):
        b=self.body()
        before=b.owner.body()
        b.owner.aux['sleep_pressure']=.95
        b.owner._record(before,b.owner.body(),'external_input',
            'declared synthetic high-sleep intervention on an isolated regression copy',0.)
        result=self.advance(b)
        self.assertNotEqual(result['owner']['selected_action'],'walk')
        self.assertNotIn('walk',[c['action'] for c in result['owner']['candidates']])
        self.assertEqual(b.owner.physical.star_started,{'L':1,'R':1})


if __name__=='__main__':unittest.main()
