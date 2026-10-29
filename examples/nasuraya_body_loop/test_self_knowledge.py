"""Independent scoring and evidence-boundary tests; no native simulation."""
from copy import deepcopy
import math
import unittest

from .self_knowledge import (BUCKETS, forecast_action, score_action,
                             summarize_action_forecasts)


def episode(identifier, action='walk', context='awake', preferred='walk', duration_s=.1):
    return dict(id=identifier, actual_action=action, context=context,
                preferred=preferred, duration_s=duration_s,
                kind='observed_software_outcome', source='native-decision://' + identifier + '/hash')


def forecast(episodes, **kwargs):
    return forecast_action(episodes, context=kwargs.pop('context', 'awake'),
                           preferred=kwargs.pop('preferred', 'walk'),
                           duration_s=kwargs.pop('duration_s', .1), **kwargs)


class SelfKnowledgeTests(unittest.TestCase):
    def test_hand_computed_multiclass_brier_and_support(self):
        cold = forecast([])
        self.assertEqual(cold['distribution'], dict.fromkeys(BUCKETS, .25))
        self.assertEqual(cold['status'], 'insufficient_evidence')
        self.assertIsNone(cold['predicted_action'])
        self.assertAlmostEqual(score_action(cold, 'walk', 'native-decision://later/h')['brier'], .75)
        f = forecast([episode('a'), episode('b'), episode('c', 'protect')])
        self.assertEqual(f['status'], 'empirical_estimate')
        self.assertEqual(f['predicted_action'], 'walk')
        self.assertEqual(f['distribution'], dict(walk=3/7, observe=1/7, protect=2/7, other=1/7))
        self.assertAlmostEqual(score_action(f, 'walk', 'native-decision://d/h')['brier'], 22/49)

    def test_unknown_native_outcomes_are_kept_in_other(self):
        f = forecast([episode('a', 'slow_breath')])
        self.assertEqual(f['distribution']['other'], .4)
        score = score_action(f, 'rapid_breath', 'native-decision://b/h')
        self.assertEqual(score['actual'], 'other')
        self.assertEqual(score['actual_action'], 'rapid_breath')
        self.assertAlmostEqual(score['brier'], .48)

    def test_legacy_and_unauthenticated_or_authored_rows_are_excluded(self):
        legacy = episode('old'); del legacy['duration_s']
        authored = episode('hypothesis'); authored['kind'] = 'authored_hypothesis'
        unverified = episode('guess'); unverified['source'] = 'guess://x'
        f = forecast([legacy, authored, unverified, episode('real')])
        self.assertEqual(f['legacy_excluded'], 1)
        self.assertEqual(f['samples'], 1)
        self.assertEqual(f['source_ids'], ['real'])

    def test_pooled_baseline_conditions_on_preference_and_duration(self):
        rows = [episode('local'), episode('other-context', 'protect', context='sleep'),
                episode('other-preference', 'observe', preferred='observe'),
                episode('other-duration', 'protect', duration_s=.2)]
        f = forecast(rows)
        self.assertEqual(f['samples'], 1)
        self.assertEqual(f['pooled_samples'], 2)
        self.assertEqual(f['pooled_source_ids'], ['local', 'other-context'])
        self.assertEqual(f['distribution'], dict(walk=.4, observe=.2, protect=.2, other=.2))
        self.assertEqual(f['pooled_distribution'], dict(walk=2/6, observe=1/6, protect=2/6, other=1/6))

    def test_forecast_and_score_do_not_mutate_or_follow_future_outcomes(self):
        rows = [episode('past')]; original = deepcopy(rows)
        frozen = forecast(rows); before = deepcopy(frozen)
        rows.append(episode('future', 'protect'))
        scored = score_action(frozen, 'protect', 'native-decision://future/hash')
        self.assertEqual(frozen, before)
        self.assertEqual(rows[:1], original)
        self.assertNotIn('future', scored['source_ids'])
        self.assertNotEqual(forecast(rows)['model_digest'], frozen['model_digest'])
        scored['distribution']['walk'] = 0
        scored['source_ids'].append('injected')
        self.assertEqual(frozen, before)

    def test_disabled_neither_forecasts_nor_scores(self):
        f = forecast([episode('past')], enabled=False)
        self.assertIsNone(f['distribution'])
        self.assertIsNone(f['pooled_distribution'])
        self.assertEqual(f['samples'], 0)
        self.assertEqual(f['status'], 'disabled')
        self.assertIsNone(score_action(f, None, None))

    def test_strict_probability_validation(self):
        for bad in (math.nan, math.inf, -0.1, 1.1, True, '0.25'):
            f = forecast([]); f['distribution']['walk'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                score_action(f, 'walk', 'native-decision://later/h')
        f = forecast([]); f['distribution']['walk'] = .4
        with self.assertRaises(ValueError): score_action(f, 'walk', 'native-decision://later/h')
        f = forecast([]); del f['pooled_distribution']['other']
        with self.assertRaises(ValueError): score_action(f, 'walk', 'native-decision://later/h')
        with self.assertRaises(ValueError): score_action(forecast([]), 'walk', 'authored://guess')

    def test_summary_keeps_cold_supported_and_failures_separate(self):
        cold = score_action(forecast([]), 'walk', 'native-decision://cold/h')
        ready = score_action(forecast([episode(str(i)) for i in range(3)]),
                             'walk', 'native-decision://ready/h')
        intents = {
            'cold': {'result': {'action_forecast_score': cold}},
            'ready': {'result': {'action_forecast_score': ready}},
            'pending': {'result': None},
            'disabled': {'result': {'action_forecast_score': None}},
            'failed': {'result': {'native_receipt': {'status': 'executor_failed'},
                                  'action_forecast_score': cold}}}
        before = deepcopy(intents)
        summary = summarize_action_forecasts(intents)
        self.assertEqual((summary['scored'], summary['excluded']), (2, 3))
        self.assertEqual(summary['cold_start']['count'], 1)
        self.assertAlmostEqual(summary['cold_start']['mean_brier'], .75)
        self.assertEqual(summary['supported']['count'], 1)
        self.assertAlmostEqual(summary['supported']['mean_brier'], 12/49)
        self.assertEqual(intents, before)
        self.assertEqual(summarize_action_forecasts(dict(reversed(list(intents.items())))), summary)
        intents['cold']['result']['action_forecast_score']['brier'] = 0
        with self.assertRaises(ValueError): summarize_action_forecasts(intents)

    def test_empty_summary_has_no_fabricated_zero_scores(self):
        summary = summarize_action_forecasts({})
        self.assertEqual(summary['scored'], 0)
        self.assertIsNone(summary['supported']['mean_brier'])
        self.assertIsNone(summary['cold_start']['pooled_minus_local'])


if __name__ == '__main__':
    unittest.main()
