"""Behavioral and evidence-integrity contracts for the optional local estimator."""
from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import continuous_self_knowledge as model
from .self_knowledge import _digest


def observation(sleep=.7, **changes):
    result = dict(energy=.8, fatigue=.2, pain=.1, sleep_pressure=sleep)
    result.update(changes)
    return result


def episode(i, sleep=.7, action='observe', **changes):
    row = dict(id=str(i), kind='observed_software_outcome', source=f'native-decision://{i}/digest',
        before=observation(sleep), feedback=dict(walk=None, observe=None),
        actual_action=action, preferred='walk', duration_s=.1)
    row.update(changes)
    return row


def forecast(rows, sleep=.7, **kwargs):
    return model.forecast_action(rows, before=observation(sleep), preferred='walk',
                                 duration_s=.1, **kwargs)


class ContinuousForecastTests(unittest.TestCase):
    def test_prior_failure_and_unknown_feedback_are_distinct(self):
        rows = [episode(i, action='protect') for i in range(4)]
        rows += [episode(i+4, feedback=dict(walk=False, observe=None)) for i in range(4)]
        self.assertEqual(forecast(rows)['predicted_action'], 'protect')
        self.assertEqual(forecast(rows, feedback=dict(walk=False, observe=None))['predicted_action'], 'observe')
        unknown = forecast(rows, feedback=dict(walk=True, observe=True))
        self.assertEqual(unknown['status'], 'unseen_feedback_state')
        self.assertIsNone(unknown['predicted_action'])

    def test_different_actions_inside_one_old_context(self):
        rows = [episode(i, .68+i*.005) for i in range(4)]
        rows += [episode(i+4, .9+i*.005, 'protect') for i in range(4)]
        self.assertEqual(forecast(rows, .69)['predicted_action'], 'observe')
        self.assertEqual(forecast(rows, .91)['predicted_action'], 'protect')

    def test_distant_data_uses_pooled_vector_without_asserting_knowledge(self):
        rows = [episode(i, .2, 'walk') for i in range(8)]
        result = forecast(rows, .9)
        self.assertEqual(result['status'], 'outside_observed_support')
        self.assertEqual(result['distribution'], result['pooled_distribution'])
        self.assertEqual(result['distribution']['walk'], 9/12)
        self.assertIsNone(result['predicted_action'])
        self.assertAlmostEqual(result['nearest_distance'], .7)

    def test_empty_history_is_uniform_without_zero_error_claim(self):
        result = forecast([])
        self.assertEqual(set(result['distribution'].values()), {.25})
        self.assertEqual(result['status'], 'no_observed_history')
        self.assertIsNone(result['predicted_action'])
        summary = model.summarize({})
        self.assertIsNone(summary['mean_brier'])
        self.assertIsNone(summary['supported_accuracy'])

    def test_few_neighbors_do_not_emit_a_label(self):
        result = forecast([episode(1), episode(2)])
        self.assertEqual(result['status'], 'insufficient_local_evidence')
        self.assertIsNone(result['predicted_action'])

    def test_local_conflict_abstains_even_with_many_receipts(self):
        rows = [episode(i, action='protect' if i%2 else 'observe') for i in range(8)]
        result = forecast(rows)
        self.assertEqual(result['status'], 'conflicting_local_evidence')
        self.assertEqual(result['agreement'], .5)
        self.assertIsNone(result['predicted_action'])

    def test_all_four_features_contribute_to_support(self):
        rows = [episode(i) for i in range(4)]
        for key in model.FEATURES:
            before = observation(); before[key] = 1. if before[key] < .5 else 0.
            result = model.forecast_action(rows, before=before, preferred='walk', duration_s=.1)
            self.assertEqual(result['status'], 'outside_observed_support')

    def test_preference_and_duration_do_not_leak(self):
        rows = [episode(i, action='protect', preferred='observe') for i in range(5)]
        rows += [episode(i+5, action='protect', duration_s=.3) for i in range(5)]
        self.assertEqual(forecast(rows)['pooled_samples'], 0)

    def test_old_or_authored_observations_are_not_invented(self):
        old = episode(1); old.pop('before')
        authored = episode(2, kind='authored_hypothesis')
        external = episode(3, source='user://message')
        result = forecast([old, authored, external])
        self.assertEqual(result['pooled_samples'], 0)
        self.assertEqual(result['excluded_missing_observation'], 1)

    def test_duplicate_ids_and_receipts_cannot_inflate_support(self):
        for row in (episode(1), episode(2, source='native-decision://1/digest')):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                forecast([episode(1), row])

    def test_malformed_values_are_rejected(self):
        for bad in (True, math.nan, math.inf, -.1, 1.1, '0.5'):
            before = observation(); before['pain'] = bad
            with self.assertRaises(ValueError):
                model.forecast_action([], before=before, preferred='walk', duration_s=.1)
        for config in ({}, dict(model.DEFAULT_CONFIG, neighbors=True),
                       dict(model.DEFAULT_CONFIG, min_samples=20),
                       dict(model.DEFAULT_CONFIG, radius=0),
                       dict(model.DEFAULT_CONFIG, min_agreement=.5)):
            with self.assertRaises(ValueError): forecast([], config=config)

    def test_frozen_forecast_is_immutable_and_hand_scored(self):
        rows = [episode(i) for i in range(3)]
        saved = deepcopy(rows); f = forecast(rows); frozen = deepcopy(f)
        score = model.score_action(f, 'protect', 'native-decision://later/digest')
        expected = sum((f['distribution'][a] - (a == 'protect'))**2 for a in model.BUCKETS)
        self.assertEqual(score['brier'], expected)
        self.assertEqual(rows, saved); self.assertEqual(f, frozen)
        rows.append(episode(4, action='protect'))
        self.assertEqual(score['forecast'], frozen)

    def test_tampered_forecast_and_untrusted_outcome_rejected(self):
        f = forecast([episode(i) for i in range(3)])
        corrupt = deepcopy(f); corrupt['distribution']['protect'] += .1
        with self.assertRaisesRegex(ValueError, 'integrity'):
            model.score_action(corrupt, 'protect', 'native-decision://later/digest')
        with self.assertRaisesRegex(ValueError, 'authoritative'):
            model.score_action(f, 'protect', 'authored://guess')

    def test_disabled_and_other_outcomes_remain_distinct(self):
        f = forecast([], enabled=False)
        self.assertIsNone(model.score_action(f, 'walk', 'native-decision://x'))
        score = model.score_action(forecast([]), 'slow_breath', 'native-decision://x')
        self.assertEqual(score['actual'], 'other')
        self.assertEqual(score['actual_action'], 'slow_breath')

    def test_recent_equal_distance_receipts_are_selected_deterministically(self):
        rows = [episode(i, action='walk') for i in range(6)]
        rows += [episode(i+6, action='protect') for i in range(6)]
        config = dict(model.DEFAULT_CONFIG, neighbors=3)
        result = forecast(rows, config=config)
        self.assertEqual(result['source_ids'], ['11','10','9'])
        self.assertEqual(result['predicted_action'], 'protect')


class ContinuousIntegrationTests(unittest.TestCase):
    def setUp(self):
        from .host import BodyLoop
        from .experience import ExperienceController
        self.BodyLoop = BodyLoop; self.Controller = ExperienceController
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'body.sqlite'

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_receipt_learning_restart_and_replay(self):
        with self.BodyLoop.start(self.path, fixture='sleep', max_actions=3) as loop:
            c = self.Controller.enable(loop, continuous_forecast=True)
            first = c.step('one')
            self.assertEqual(first['plan']['continuous_action_forecast']['pooled_samples'], 0)
            self.assertEqual(first['continuous_action_score']['actual'], 'protect')
            state = c.status()['state']
            before = deepcopy(state)
            history = model.observed_history(state)
            self.assertEqual(state, before)
            self.assertEqual(history[0]['before'], first['prediction']['before'])
            self.assertNotEqual(history[0]['before'], first['prediction']['actual'])
        with self.BodyLoop(self.path) as loop:
            c = self.Controller(loop)
            self.assertEqual(c.status()['state'], state)
            second = c.step('two'); saved = c.status()
            self.assertEqual(second['native_receipt']['actual_action'], 'observe')
            replay = c.step('one')
            self.assertEqual(replay['this_call_native_cycles'], 0)
            self.assertEqual(replay['continuous_action_score'], first['continuous_action_score'])
            self.assertEqual(c.status(), saved)
            self.assertEqual(saved['continuous_self_knowledge']['scored'], 2)

    def test_native_commit_crash_scores_once_on_recovery(self):
        with self.BodyLoop.start(self.path, max_actions=1) as loop:
            c = self.Controller.enable(loop, continuous_forecast=True)
            with patch.object(c, '_finish', side_effect=RuntimeError('injected crash')):
                with self.assertRaises(RuntimeError): c.step('one')
            frozen = c._load()['intents']['one']['plan']['continuous_action_forecast']
        with self.BodyLoop(self.path) as loop:
            c = self.Controller(loop); result = c.step('one')
            self.assertEqual(result['continuous_action_score']['forecast'], frozen)
            self.assertEqual(result['this_call_native_cycles'], 0)
            self.assertEqual(len(c.status()['state']['episodes']), 1)
            self.assertEqual(c.status()['continuous_self_knowledge']['scored'], 1)

    def test_monitor_preserves_native_behavior_and_budget(self):
        results = []
        for enabled in (False, True):
            path = Path(self.temp.name)/f'monitor-{enabled}.sqlite'
            with self.BodyLoop.start(path, fixture='sleep', max_actions=2) as loop:
                c = self.Controller.enable(loop, continuous_forecast=enabled)
                rows = [c.step('one'), c.step('two')]
                results.append([(r['native_receipt'],r['prediction'],r['affect_after']) for r in rows])
                self.assertEqual(loop.status()['actions_remaining'], 0)
        self.assertEqual(results[0], results[1])

    def test_disabled_prediction_has_no_continuous_learning_score(self):
        with self.BodyLoop.start(self.path, max_actions=1) as loop:
            c = self.Controller.enable(loop, continuous_forecast=True, prediction=False)
            result = c.step('one')
            self.assertEqual(result['plan']['continuous_action_forecast']['status'], 'disabled')
            self.assertIsNone(result['continuous_action_score'])
            self.assertEqual(c.status()['continuous_self_knowledge']['scored'], 0)

    def test_legacy_reservation_never_gets_posthoc_forecast(self):
        with self.BodyLoop.start(self.path, max_actions=1) as loop:
            c = self.Controller.enable(loop)
            with patch.object(c, '_finish', side_effect=RuntimeError('injected crash')):
                with self.assertRaises(RuntimeError): c.step('one')
            state = c._load(); state['continuous_forecast_config'] = dict(model.DEFAULT_CONFIG)
            c._save(state)
            recovered = c.step('one')
            self.assertNotIn('continuous_action_score', recovered)
            self.assertEqual(c.status()['continuous_self_knowledge']['scored'], 0)

    def test_corrupt_pre_action_evidence_is_rejected(self):
        with self.BodyLoop.start(self.path, max_actions=2) as loop:
            c = self.Controller.enable(loop, continuous_forecast=True); c.step('one')
            state = c._load()
            state['intents']['one']['snapshot']['minimum_state']['pain'] = .99
            with self.assertRaisesRegex(ValueError, 'pre-action'):
                model.observed_history(state)

    def test_score_summary_detects_tampering(self):
        with self.BodyLoop.start(self.path, max_actions=1) as loop:
            c = self.Controller.enable(loop, continuous_forecast=True); c.step('one')
            intents = c._load()['intents']
            intents['one']['result']['continuous_action_score']['brier'] = 0.
            with self.assertRaisesRegex(ValueError, 'integrity'):
                model.summarize(intents)


if __name__ == '__main__':
    unittest.main()
