"""Matched-input controls, isolation and provenance for the pure affect audit."""
from copy import deepcopy
import unittest

from reflection_cycle import digest
from .affect_audit import audit_affect, POLICY_KEYS
from .experience import _policy_plan, initial_state, FLAGS


class AffectAuditTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state({}, dict.fromkeys(FLAGS, True))
        self.state['affect'] = dict(valence=.05, arousal=.95)
        self.snapshot = dict(revision=4, checkpoint_sha256='a'*64,
            simulated_wall_utc='2026-10-29T00:00:00+00:00',
            minimum_state=dict(energy=.8, fatigue=.2, pain=.1, sleep_pressure=.2))

    def audit(self, policy=_policy_plan):
        return audit_affect(self.state, self.snapshot, .1, policy)

    def test_factual_provenance_and_controlled_score_effects(self):
        before = deepcopy((self.state, self.snapshot))
        audit = self.audit(); variants = audit['variants']
        expected = _policy_plan(self.state, self.snapshot, .1)
        for key in ('scores', 'preferred', 'prediction'):
            self.assertEqual(variants['factual'][key], expected[key])
            self.assertEqual(variants['sham'][key], expected[key])
        self.assertEqual(variants['factual']['preferred'], 'observe')
        self.assertEqual(variants['affect_off']['preferred'], 'walk')
        self.assertGreater(variants['valence_high']['scores']['walk'], variants['valence_low']['scores']['walk'])
        self.assertLess(variants['arousal_high']['scores']['walk'], variants['arousal_low']['scores']['walk'])
        self.assertGreater(variants['arousal_high']['scores']['observe'], variants['arousal_low']['scores']['observe'])
        observation = audit['observation']
        self.assertEqual(observation['checkpoint_sha256'], self.snapshot['checkpoint_sha256'])
        self.assertEqual(observation['revision'], 4)
        self.assertEqual(observation['snapshot_sha256'], digest(self.snapshot))
        self.assertEqual(observation['state_sha256'], digest({k:self.state[k] for k in POLICY_KEYS}))
        self.assertEqual((self.state, self.snapshot), before)
        self.assertFalse(audit['subjective_feeling_claim'])
        self.assertEqual(audit['native_cycles'], 0)
        self.assertTrue(all(audit['checks'].values()))

    def test_disabled_affect_is_a_negative_control(self):
        self.state['flags']['affect'] = False
        audit = self.audit(); variants = audit['variants']
        self.assertFalse(audit['observation']['affect_enabled'])
        self.assertEqual(audit['observation']['affect_effective'], dict(valence=.5, arousal=0.))
        for row in variants.values():
            self.assertEqual(row['scores'], variants['factual']['scores'])
            self.assertFalse(row['changed_preference'])
        for name in ('valence_low', 'valence_high', 'arousal_low', 'arousal_high'):
            self.assertFalse(variants[name]['flags']['affect'])

    def test_changed_preference_can_select_another_metric_predictor(self):
        observe_key = _policy_plan(self.state, self.snapshot, .1)['prediction']['key']
        neutral = deepcopy(self.state); neutral['flags']['affect'] = False
        walk_key = _policy_plan(neutral, self.snapshot, .1)['prediction']['key']
        metric_names = tuple(self.snapshot['minimum_state'])
        self.state['predictors'] = {
            observe_key: dict(count=2, mean_delta=dict.fromkeys(metric_names, .05)),
            walk_key: dict(count=3, mean_delta=dict.fromkeys(metric_names, -.05)),
        }
        variants = self.audit()['variants']
        self.assertEqual(variants['factual']['prediction'], variants['sham']['prediction'])
        self.assertEqual(variants['factual']['prediction']['before'], variants['affect_off']['prediction']['before'])
        self.assertNotEqual(variants['factual']['prediction']['expected'], variants['affect_off']['prediction']['expected'])

    def test_only_affect_inputs_vary_and_unused_metadata_is_irrelevant(self):
        calls = []
        def inspect(state, snapshot, duration):
            calls.append(deepcopy((state, snapshot, duration)))
            return _policy_plan(state, snapshot, duration)
        first = self.audit(inspect)
        self.assertEqual(len(calls), 8)
        for state, snapshot, duration in calls:
            self.assertNotIn('intents', state)
            self.assertNotIn('hypotheses', state)
            self.assertEqual(snapshot, self.snapshot)
            self.assertEqual(duration, .1)
            for key in ('episodes', 'predictors', 'error_ema'):
                self.assertEqual(state[key], self.state[key])
            for key in set(FLAGS)-{'affect'}:
                self.assertEqual(state['flags'][key], self.state['flags'][key])
        self.state['hypotheses'].append({'text':'an irrelevant identity narrative'})
        self.state['intents']['old'] = {'large_unused_record': ['unused']*100}
        self.assertEqual(self.audit(), first)

    def test_mutating_callback_rejected_without_affecting_inputs(self):
        for target in ('state', 'snapshot'):
            with self.subTest(target=target):
                before = deepcopy((self.state, self.snapshot))
                def mutate(state, snapshot, duration):
                    result = _policy_plan(state, snapshot, duration)
                    if target == 'state': state['episodes'].append({'invented': True})
                    else: snapshot['minimum_state']['pain'] = 1.
                    return result
                with self.assertRaisesRegex(ValueError, 'must not mutate'):
                    self.audit(mutate)
                self.assertEqual((self.state, self.snapshot), before)

    def test_invalid_affect_rejected_even_when_disabled(self):
        for enabled in (True, False):
            for channel in ('valence', 'arousal'):
                for value in (float('nan'), float('inf'), -.01, 1.01, True, '0.5'):
                    with self.subTest(enabled=enabled, channel=channel, value=value):
                        self.state['flags']['affect'] = enabled
                        self.state['affect'] = dict(valence=.5, arousal=.5)
                        self.state['affect'][channel] = value
                        with self.assertRaisesRegex(ValueError, 'normalized affect'):
                            self.audit()

    def test_sham_dependency_is_rejected(self):
        def identity_dependent(state, snapshot, duration):
            result = _policy_plan(state, snapshot, duration)
            if 'audit_label' in state: result['scores']['walk'] += .01
            return result
        with self.assertRaisesRegex(ValueError, 'sham metadata'):
            self.audit(identity_dependent)


if __name__ == '__main__':
    unittest.main()
