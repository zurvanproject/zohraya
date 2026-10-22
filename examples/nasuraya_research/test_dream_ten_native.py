"""Integration checks use executed native frames, never mock improvement rows."""
from copy import deepcopy
import unittest

from .dream_ten import Step, dream
from .dream_ten_native import (attach_policy, rollout, stride_reference, measure_step,
                               FixedCautionSupport, metrics)
from examples.nasuraya_self_model.evaluate import fixture, request
from examples.nasuraya_star_motion.coordinated_support import attach
from synthetic_fixture import prepare_defaults
from unified_body_v2 import UnifiedBody


class NativeDreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()
        cls.source = fixture(.1).checkpoint()
        cls.reference = stride_reference(UnifiedBody.restore(cls.source))
        cls.trial = rollout(cls.source, 1., cls.reference, requests=1)

    def test_scale_one_is_existing_governor_and_actual_stock_debits(self):
        body = UnifiedBody.restore(self.source)
        attach(body)
        before_fuel = body.owner.owner.body.state.fuel_J
        before_reserve = body.owner.owner.body.state.reserve_J
        r = body.cycle(**request(body, 'trial:0', .1))
        # Explicit default friction is physically identical to omitted default.
        after = body.owner.owner.body.state
        row = self.trial['rows'][0]
        self.assertAlmostEqual(row['fuel_used_J'], before_fuel-after.fuel_J, places=7)
        self.assertAlmostEqual(row['reserve_used_J'], before_reserve-after.reserve_J, places=7)
        self.assertEqual(row['feet_m'], body.owner.physical.state.feet_m)
        self.assertEqual(row['com_m'], body.owner.physical.state.com_m)
        self.assertEqual(row['step']['valid'], r['owner']['physical_model_valid'])
        self.assertEqual(row['step']['fuel_j'], row['fuel_used_J']+row['reserve_used_J'])

    def test_policy_changes_real_com_and_not_source_or_limits(self):
        source = deepcopy(self.source)
        body = UnifiedBody.restore(source)
        design = deepcopy(body.owner.physical.design)
        attach_policy(body, .25)
        self.assertEqual(body.checkpoint(), source)
        self.assertEqual(body.owner.physical.design, design)
        other = rollout(source, .25, self.reference, requests=1)
        self.assertEqual(source, self.source)
        self.assertNotEqual(other['rows'][0]['com_m'], self.trial['rows'][0]['com_m'])
        self.assertEqual(other['reference'], self.trial['reference'])

    def test_zero_friction_failure_is_retained(self):
        trial = rollout(self.source, .25, self.reference, requests=1, friction=0.)
        row = trial['rows'][0]
        # The native owner may veto walk and execute a valid stand instead.
        self.assertNotEqual(row['selected_action'], 'walk')
        self.assertEqual(metrics([trial])['valid_walk_requests'], 0)
        from posture_step import GaitEnvironment
        body = UnifiedBody.restore(self.source)
        attach_policy(body, .25)
        frame = body.owner.physical.step(GaitEnvironment(command='walk', friction=dict(L=0., R=0.)))
        self.assertFalse(frame['balance']['model_valid'])
        self.assertEqual(frame['posture']['failed_reason'], 'friction_limit_exceeded')

    def test_missing_measurements_fail_and_no_motion_is_distinct_from_valid(self):
        self.assertEqual(metrics([self.trial])['confirmed_walk_touchdowns'], 0)
        body = UnifiedBody.restore(self.source)
        feet = deepcopy(body.owner.physical.state.feet_m)
        receipt = body.cycle(**request(body, 'missing', .1))
        del receipt['trace'][0]['reserve_used_J']
        with self.assertRaises(KeyError):
            measure_step(body, receipt, self.reference, 1., feet)

    def test_explicit_emergency_scale_is_forwarded_unchanged(self):
        from unittest.mock import patch
        body = UnifiedBody.restore(self.source)
        attach_policy(body, .5)
        p = body.owner.physical
        with patch('examples.nasuraya_star_motion.coordinated_support.CoordinatedSupport._integrate_once') as method:
            p._integrate_once('environment', 0.)
            method.assert_called_once_with('environment', 0.)


class SeparationTests(unittest.TestCase):
    def test_test_results_do_not_choose_another_candidate(self):
        training = [Step(1, .04, 2, True)]*10
        calls = []
        def train(scale, split):
            calls.append((split, scale))
            return [Step(1, .01 if scale==.5 else .04, 2, True)]*10
        def test(scale, split):
            calls.append((split, scale))
            return [Step(1, .9 if scale==.5 else .04, 2, True)]*10
        result = dream(training, train, test)
        self.assertEqual(result['learned_scale'], .5)
        self.assertFalse(result['accepted'])
        self.assertEqual(calls[-2:], [('test', 1.), ('test', .5)])
        self.assertEqual(len([c for c in calls if c[0]=='test']), 2)

    def test_mismatch_and_validity_types_rejected(self):
        a = [Step(1, .04, 2, True)]*10
        with self.assertRaises(ValueError):
            dream(a, lambda *_: a[:1], lambda *_: a)
        with self.assertRaises(ValueError):
            Step(1, .04, 2, 'yes')

    def test_energy_and_support_regression_rejected(self):
        a = [Step(1, .04, 2, True)]*10
        def train(scale, split):
            return [Step(1, .01 if scale==.5 else .04, 2, True)]*10
        for energy, support in [(3, 1), (2, .8)]:
            def test(scale, split):
                return [Step(support, .01, energy, True)]*10 if scale==.5 else a
            self.assertFalse(dream(a, train, test)['accepted'])


if __name__ == '__main__':
    unittest.main()
