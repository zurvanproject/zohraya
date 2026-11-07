"""Independent hand-calculated contract fixtures, not model-performance evidence."""
import copy
import json
import socket
import unittest
from datetime import datetime, timezone
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from . import prediction_router as r, paired_comparison as p, self_model_step as m, session as s
from .test_paired_comparison import response

SCOPE = 'a' * 64


def values(value):
    return dict.fromkeys(m.METRICS, value)


def observation(case_id='fresh', value=.5):
    return dict(id=case_id, fixture='normal', duration_s=1., observed=values(value),
                proposed_host_preference='walk')


def history():
    return [dict(id='calibration', fixture='normal', duration_s=1., observed=values(.25),
                 actual_metrics=values(.375), actual_action='observe')]


def sealed(evidence):
    evidence['manifest_sha256'] = s.digest(evidence['manifest'])
    return evidence


def independent_fixture():
    """Binary-exact oracle: persistence error .25, recall .125, API zero."""
    manifest = dict(scope_sha256=SCOPE, policy_sha256=s.digest(r.POLICY),
                    preregistration_ref='test-fixture://plan-only-not-real-evidence',
                    registered_at='2026-10-26T00:00:00Z',
                    calibration=[dict(group_id='training-lineage', source_ref='test-fixture://calibration',
                                      observed_at='2026-10-25T00:00:00Z', episode=history()[0])],
                    groups={batch: [f'{batch}-{i}' for i in range(20)] for batch in r.POLICY['batches']})
    records = []
    for batch_number, batch in enumerate(r.POLICY['batches']):
        for i, group in enumerate(manifest['groups'][batch]):
            value = .5 + (batch_number * 20 + i) / 1024
            o = observation(group, value)
            predictions = {
                'persistence': dict(id=group, predicted_metrics=values(value), predicted_action='walk'),
                'nearest_episode': dict(id=group, predicted_metrics=values(value + .125), predicted_action='observe'),
                'api': dict(id=group, predicted_metrics=values(value + .25), predicted_action='protect')}
            records.append(dict(batch=batch, group_id=group, observation=o, predictions=predictions,
                                history_sha256=s.digest(history()), actual_metrics=values(value + .25),
                                actual_action='observe', forecast_ref=f'test-fixture://{group}/forecast',
                                outcome_ref=f'test-fixture://{group}/outcome',
                                predicted_at='2026-10-26T01:00:00Z', observed_at='2026-10-26T02:00:00Z'))
    return sealed(dict(schema=r.SCHEMA, manifest=manifest, records=records))


def cached_inputs():
    observations = [dict(case, observed=values(.5), proposed_host_preference='walk') for case in p.CASES]
    request = p.payload(observations, history())
    cache = dict(scope_sha256=SCOPE, status='completed', request=request,
                 request_sha256=s.digest(request), provider_response=response())
    return observations, cache


class Tests(unittest.TestCase):
    def setUp(self):
        # An accidental sender/socket is a hard test failure, even with env keys set.
        self.api = patch.object(s, 'request_json', side_effect=AssertionError('network forbidden')).start()
        patch.object(socket, 'socket', side_effect=AssertionError('socket forbidden')).start()
        patch.dict('os.environ', {'OPENAI_API_KEY': 'test-never-send'}).start()
        self.addCleanup(patch.stopall)

    def test_default_ignores_model_availability_preserves_memory_action(self):
        inputs, cache = cached_inputs()
        before = copy.deepcopy((inputs, cache))
        result = r.route_predictions(inputs, history(), scope_sha256=SCOPE, cached_call=cache)
        self.assertEqual(result['predictions'][0]['predicted_action'], 'observe')
        self.assertEqual(result['predictions'][0]['numeric_source'], 'nearest_episode')
        self.assertEqual(result['new_api_calls'], 0)
        self.assertFalse(result['numeric_gate']['eligible'])
        self.assertEqual((inputs, cache), before)
        self.api.assert_not_called()

    def test_no_memory_falls_back_explicitly_without_spend(self):
        prediction = r.route_predictions([observation()], [], scope_sha256=SCOPE)['predictions'][0]
        self.assertEqual(prediction['predicted_metrics'], values(.5))
        self.assertEqual(prediction['predicted_action'], 'walk')
        self.assertEqual(prediction['action_source'], 'persistence_fallback')

    def test_oracle_gate_uses_equal_group_mae_and_exact_sign_test(self):
        result = r.evaluate_numeric_evidence(independent_fixture(), scope_sha256=SCOPE)
        self.assertTrue(result['eligible'], result)
        for batch in result['batches'].values():
            self.assertEqual(batch['independent_groups'], 20)
            self.assertEqual(batch['mae'], dict(persistence=.25, nearest_episode=.125, api=0.))
            self.assertEqual(batch['comparisons']['nearest_episode']['sign_test_p'], 1 / 2**20)
        self.assertEqual(r.sign_test_p([0.] * 40), 1.)
        self.assertEqual(r.sign_test_p([1., -1.]), .75)

    def test_admitted_cache_replaces_only_numbers(self):
        inputs, cache = cached_inputs()
        result = r.route_predictions(inputs, history(), scope_sha256=SCOPE,
                                     evidence=independent_fixture(), cached_call=cache)
        self.assertEqual(result['predictions'][0]['numeric_source'], 'api_cached')
        self.assertEqual(result['predictions'][0]['predicted_action'], 'observe')
        self.assertEqual(result['predictions'][0]['predicted_metrics'], values(.5))
        self.assertFalse(result['live_execution_supported'])
        self.api.assert_not_called()

    def test_eligible_missing_cache_cannot_dispatch(self):
        result = r.route_predictions([observation()], history(), scope_sha256=SCOPE,
                                     evidence=independent_fixture())
        self.assertTrue(result['numeric_gate']['eligible'])
        self.assertEqual(result['predictions'][0]['numeric_source'], 'nearest_episode')
        self.api.assert_not_called()

    def test_stale_unknown_mismatched_or_malformed_cache_cannot_dispatch(self):
        for mutation in ('scope', 'pending', 'hash', 'payload', 'nan', 'model'):
            with self.subTest(mutation=mutation):
                inputs, cache = cached_inputs()
                if mutation == 'scope': cache['scope_sha256'] = 'b' * 64
                if mutation == 'pending': cache['status'] = 'pending'
                if mutation == 'hash': cache['request_sha256'] = 'b' * 64
                if mutation == 'payload': cache['request']['input'] = '{}'
                if mutation == 'model': cache['provider_response']['model'] = 'unapproved-model'
                if mutation == 'nan':
                    data = json.loads(cache['provider_response']['output'][0]['content'][0]['text'])
                    data['predictions'][-1]['predicted_metrics']['energy'] = float('nan')
                    cache['provider_response']['output'][0]['content'][0]['text'] = json.dumps(data)
                result = r.route_predictions(inputs, history(), scope_sha256=SCOPE,
                                             evidence=independent_fixture(), cached_call=cache)
                self.assertEqual(result['reason'], 'invalid_cache_no_live_dispatch')
                self.assertTrue(all(x['numeric_source'] != 'api_cached' for x in result['predictions']))
        self.api.assert_not_called()

    def test_regression_in_replication_cannot_hide_in_aggregate(self):
        data = independent_fixture()
        for row in data['records'][20:]:
            row['predictions']['api']['predicted_metrics'] = values(0.)
        result = r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)
        self.assertFalse(result['eligible'])
        self.assertIn('replication:nearest_episode:numeric_gate_failed', result['reasons'])

    def test_single_metric_regression_rejected_despite_better_average(self):
        data = independent_fixture()
        for row in data['records']:
            row['predictions']['api']['predicted_metrics']['pain'] = row['actual_metrics']['pain'] - .2
        result = r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)
        self.assertLess(result['batches']['validation']['mae']['api'], .125)
        self.assertFalse(result['eligible'])

    def test_absolute_and_relative_gain_thresholds(self):
        data = independent_fixture()
        for row in data['records']:
            row['predictions']['api']['predicted_metrics'] = {
                k: v + .00001 for k, v in row['predictions']['nearest_episode']['predicted_metrics'].items()}
        self.assertFalse(r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)['eligible'])

    def test_large_relative_gain_below_absolute_floor_is_rejected(self):
        data = independent_fixture()
        for row in data['records']:
            row['actual_metrics'] = {k: v + .00005 for k, v in row['predictions']['nearest_episode']['predicted_metrics'].items()}
            row['predictions']['api']['predicted_metrics'] = copy.deepcopy(row['actual_metrics'])
        result = r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)
        comparison = result['batches']['validation']['comparisons']['nearest_episode']
        self.assertEqual(comparison['relative_gain'], 1.)
        self.assertFalse(result['eligible'])

    def test_zero_error_baseline_and_weak_group_consistency_block_promotion(self):
        for mode in ('perfect_baseline', 'few_wins'):
            data = independent_fixture()
            for i, row in enumerate(data['records']):
                if mode == 'perfect_baseline':
                    row['actual_metrics'] = copy.deepcopy(row['observation']['observed'])
                    row['predictions']['api']['predicted_metrics'] = copy.deepcopy(row['actual_metrics'])
                elif i % 20 >= 12:
                    row['predictions']['api']['predicted_metrics'] = {
                        k: v - .13 for k, v in row['actual_metrics'].items()}
            with self.subTest(mode=mode):
                self.assertFalse(r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)['eligible'])

    def test_correlated_transitions_keep_group_weight_and_sample_count(self):
        data = independent_fixture()
        extra = copy.deepcopy(data['records'][0])
        extra['observation']['id'] = 'extra-transition-same-lineage'
        extra['observation']['duration_s'] = .5
        for name, delta, action in (('persistence', 0., 'walk'), ('nearest_episode', .0625, 'observe'), ('api', .25, 'protect')):
            extra['predictions'][name] = dict(id=extra['observation']['id'], predicted_metrics=values(.5 + delta), predicted_action=action)
        data['records'].append(extra)
        result = r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)
        batch = result['batches']['validation']
        self.assertEqual(batch['independent_groups'], 20)
        self.assertEqual(batch['mae']['nearest_episode'], ((.125 + .1875) / 2 + 19 * .125) / 20)

    def test_no_pseudoreplication_or_renamed_duplicate_samples(self):
        for mutation in ('few_groups', 'overlap', 'copied_input', 'training_input', 'missing_group'):
            data = independent_fixture()
            if mutation == 'few_groups': data['manifest']['groups']['validation'] = ['one-lineage']
            if mutation == 'overlap': data['manifest']['groups']['replication'][0] = 'validation-0'
            if mutation == 'copied_input': data['records'][1]['observation']['observed'] = data['records'][0]['observation']['observed']
            if mutation == 'training_input': data['records'][0]['observation']['observed'] = values(.25)
            if mutation == 'missing_group': data['records'].pop()
            with self.subTest(mutation=mutation):
                self.assertFalse(r.evaluate_numeric_evidence(sealed(data), scope_sha256=SCOPE)['eligible'])

    def test_provenance_and_leakage_fail_closed(self):
        for mutation in ('plan_hash', 'scope', 'policy', 'after_outcome', 'history', 'baseline', 'nan', 'bool', 'source'):
            data = independent_fixture()
            if mutation == 'scope': data['manifest']['scope_sha256'] = 'b' * 64
            if mutation == 'policy': data['manifest']['policy_sha256'] = 'b' * 64
            if mutation == 'after_outcome': data['records'][0]['predicted_at'] = '2026-10-27T00:00:00Z'
            if mutation == 'history': data['records'][0]['history_sha256'] = 'b' * 64
            if mutation == 'baseline': data['records'][0]['predictions']['nearest_episode']['predicted_metrics'] = values(.99)
            if mutation == 'nan': data['records'][0]['actual_metrics']['pain'] = float('nan')
            if mutation == 'bool': data['records'][0]['actual_metrics']['pain'] = True
            if mutation == 'source': data['records'][0]['forecast_ref'] = ''
            sealed(data)
            if mutation == 'plan_hash': data['manifest_sha256'] = 'b' * 64
            with self.subTest(mutation=mutation):
                self.assertFalse(r.evaluate_numeric_evidence(data, scope_sha256=SCOPE)['eligible'])

    def test_bad_inputs_raise_without_api_fallback(self):
        for value in (True, float('inf'), float('nan'), -1, 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                r.route_predictions([observation(value=value)], history(), scope_sha256=SCOPE)
        for duration in (0, -1, True, float('inf'), 5e-324):
            h = history()
            h[0]['duration_s'] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                r.route_predictions([observation()], h, scope_sha256=SCOPE)
        self.api.assert_not_called()

    def test_seen_archive_is_not_independent_validation(self):
        archive = json.loads((s.ROOT / 'results/paired-comparison.json').read_text())
        self.assertFalse(r.evaluate_numeric_evidence(archive, scope_sha256=SCOPE)['eligible'])

    def test_replay_recomputes_known_metrics_and_preserves_exhausted_authorization(self):
        from .evaluate_prediction_router import evaluate
        result = evaluate(as_of=datetime(2026, 10, 26, tzinfo=timezone.utc))
        self.assertEqual(result['router_replay']['action_correct'], 12)
        self.assertAlmostEqual(result['router_replay']['metric_mae'], .0005988940669068192)
        self.assertEqual(result['router_replay']['new_api_calls'], 0)
        self.assertFalse(result['numeric_gate']['eligible'])
        self.assertEqual(result['authorization']['remaining_calls'], 0)
        self.assertEqual(result['authorization']['total_reserved_micro_usd'], 520000)
        self.assertEqual(result['costs']['historical_incremental_estimated_micro_usd'], 3530)
        self.api.assert_not_called()

    def test_original_completed_ledger_cannot_be_replayed_for_paid_calls(self):
        class WithinWindow(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 29, tzinfo=timezone.utc)
        state = json.loads((s.ROOT / 'results/paired-comparison.json').read_text())
        with patch.dict('os.environ', dict(GITHUB_REPOSITORY=s.REPO, GITHUB_REF='refs/heads/' + s.BRANCH,
                                         GITHUB_EVENT_NAME='push', GH_SESSION_TOKEN='test-only')), \
             patch.object(p, 'datetime', WithinWindow), patch.object(p, 'Ledger') as ledger, \
             patch.object(p, 'run') as run, redirect_stdout(io.StringIO()):
            ledger.return_value.load.return_value = state
            p.main()
            run.assert_not_called()
        self.api.assert_not_called()

    def test_original_expiry_and_branch_are_preserved(self):
        class AtExpiry(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 30, tzinfo=timezone.utc)
        env = dict(GITHUB_REPOSITORY=s.REPO, GITHUB_REF='refs/heads/' + s.BRANCH, GITHUB_EVENT_NAME='push')
        with patch.dict('os.environ', env), patch.object(p, 'datetime', AtExpiry), self.assertRaises(ValueError):
            p.main()
        env['GITHUB_REF'] = 'refs/heads/main'
        with patch.dict('os.environ', env), self.assertRaises(ValueError):
            p.main()
        self.api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
