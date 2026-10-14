"""Recorded closure regression; private fixture is supplied outside the repo.

NASURAYA_REVERSE_FIXTURE points at the pre-closure body/controller/cycle JSON.
Policy tests and synthetic negative controls run without the private fixture.
"""
import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.environ.get('NASURAYA_NATIVE_ROOT', str(Path(__file__).resolve().parents[2] / 'runtimes/tadash_body')))
from unified_body_v2 import UnifiedBody
from posture_step import GaitEnvironment, Inputs, PostureLoop
from coordinated_support import CoordinatedSupport
from extension_state import StarMotion, attach, checkpoint, restore


class LandingOnlyStar(StarMotion):
    """Historical prediction gate, keeping the identical native equations."""
    def _needs_support_prediction(self, e):
        q = self.state.swing
        return self.state.phase == 'settle' or (q is not None and q['kind'] == 'walk' and q['progress'] > .85)


class PredictionScopeTests(unittest.TestCase):
    def test_stand_keeps_prediction_in_double_support_and_lower(self):
        p = CoordinatedSupport()
        for phase in ('double_support', 'lower', 'settle'):
            p.state.phase = phase
            self.assertTrue(p._needs_support_prediction(GaitEnvironment(command='stand')))
        p.state.phase = 'double_support'
        self.assertFalse(p._needs_support_prediction(GaitEnvironment(command='walk')))

    def test_zero_friction_still_fails(self):
        p = CoordinatedSupport()
        f = p.step(GaitEnvironment(body=Inputs(dt_s=.1), command='stand', friction={'L':0.,'R':0.}, external_impulse_N_s=[8.,4.]))
        self.assertFalse(f['balance']['model_valid'])
        self.assertEqual(f['posture']['failed_reason'], 'friction_limit_exceeded')

    def test_severe_regional_guard_still_fails(self):
        p = CoordinatedSupport()
        f = p.step(GaitEnvironment(body=Inputs(dt_s=.1, stimuli={'calf_L':{'damage':.9}}), command='stand'))
        self.assertFalse(f['balance']['model_valid'])
        self.assertTrue(p.body.state.latched['ankle_L'])


@unittest.skipUnless(os.environ.get('NASURAYA_REVERSE_FIXTURE'), 'external recorded pre-closure fixture required')
class RecordedClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(Path(os.environ['NASURAYA_REVERSE_FIXTURE']).read_text())

    def body(self, legacy=False):
        b = UnifiedBody.restore(self.source['body'])
        before = b.checkpoint()
        attach(b, self.source['controller'])
        self.assertEqual(b.checkpoint(), before)
        if legacy:
            b.owner.physical.__class__ = LandingOnlyStar
        return b

    def advance(self, b, i=0):
        kw = deepcopy(self.source['cycle'])
        kw['event_id'] = 'closure-regression-' + str(i)
        kw['at_utc'] = (datetime.fromisoformat(kw['at_utc']) + timedelta(seconds=i)).isoformat()
        kw['expected_revision'] = b.revision
        kw['external']['sensors']['vision']['sampled_at_s'] = b.owner.owner.body.state.time_s
        return b.cycle(**kw)

    def test_historical_gate_fails_and_fixed_four_second_closure_passes(self):
        a = self.body(legacy=True)
        self.assertTrue(self.advance(a)['owner']['physical_model_valid'])
        self.assertFalse(self.advance(a,1)['owner']['physical_model_valid'])
        self.assertEqual(a.owner.physical.state.failed_reason, 'insufficient_joint_or_energy_support')
        b = self.body()
        for i in range(4):
            self.assertTrue(self.advance(b,i)['owner']['physical_model_valid'])
        p = b.owner.physical
        self.assertEqual(p.state.phase, 'double_support')
        self.assertIsNone(p.state.swing)
        self.assertEqual(p.star_started, self.source['controller']['star_started'])
        self.assertEqual(p.state.walk_steps, 2)  # safe stop is not route completion
        self.assertGreaterEqual(p.last['contact']['joint_support_fraction'], .999)

    def test_cold_restore_after_settle_preserves_closure(self):
        a = self.body()
        self.advance(a)
        b = restore(json.loads(json.dumps(checkpoint(a))))
        self.assertEqual(self.advance(a,1), self.advance(b,1))
        self.assertEqual(checkpoint(a), checkpoint(b))

    def test_prediction_does_not_duplicate_owner_time_fuel_or_replay(self):
        b = self.body()
        self.advance(b)
        time = b.owner.owner.body.state.time_s
        fuel = b.owner.owner.body.state.fuel_J
        r = self.advance(b,1)
        self.assertEqual(r['owner_ticks'], 10)
        self.assertAlmostEqual(b.owner.owner.body.state.time_s-time,1.)
        self.assertAlmostEqual(fuel-b.owner.owner.body.state.fuel_J,sum(f['fuel_used_J'] for f in r['trace']),places=6)
        self.assertLess(r['whole_body_audit']['energy_error_J'],5e-5)
        saved = checkpoint(b)
        kw = deepcopy(self.source['cycle'])
        kw['event_id']='closure-regression-1'
        kw['at_utc']=(datetime.fromisoformat(kw['at_utc'])+timedelta(seconds=1)).isoformat()
        kw['expected_revision']=b.revision-1
        kw['external']['sensors']['vision']['sampled_at_s']=time
        self.assertEqual(b.cycle(**kw),r)
        self.assertEqual(checkpoint(b),saved)


if __name__ == '__main__':
    unittest.main()
