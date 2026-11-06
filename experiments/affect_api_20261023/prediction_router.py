"""Offline, evidence-gated experimental forecasts; never dispatches a request.

Actions always come from nearest_episode. Numeric API forecasts may be reused
from an exact-request cache only after two independent validation batches pass.
Passing this gate is NOT spending authority. No credentials, ledger writes,
network requests, body commands, or automatic promotion occur here.
"""
from collections import defaultdict
from datetime import datetime
import copy
import math
import re

from . import paired_comparison as p, self_model_step as m, session as s

SCHEMA = 'nasuraya-numeric-validation/1'
POLICY = dict(
    version='numeric-router/1', batches=['validation', 'replication'],
    minimum_independent_groups_per_batch=20,
    minimum_relative_gain=.10, minimum_absolute_gain=.0001,
    maximum_sign_test_p=.0125,  # Bonferroni: two baselines x two batches.
    metric_regression_tolerance=1e-12,
    action_method='nearest_episode', numeric_default='nearest_episode',
    grouping='shared initial-condition/generator lineage is ONE group; equal group weights',
    history='frozen calibration only; no validation or replication outcomes',
)
METHODS = ('persistence', 'nearest_episode', 'api')
ACTIONS = ('walk', 'observe', 'protect')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, *, positive=False):
    _require(type(value) in (float, int) and math.isfinite(value), 'finite non-boolean number required')
    _require(value > 0 if positive else 0 <= value <= 1, 'number outside domain')


def _metrics(values):
    _require(isinstance(values, dict) and set(values) == set(m.METRICS), 'four metric fields required')
    for value in values.values():
        _number(value)


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), 'nonempty identifier required')


def _timestamp(value):
    _text(value)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _require(result.tzinfo is not None, 'timezone-aware timestamp required')
    return result


def _hash(value):
    _require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'SHA256 required')


def _observation(observation):
    _require(set(observation) == {'id', 'fixture', 'duration_s', 'observed', 'proposed_host_preference'},
             'observation fields mismatch')
    _text(observation['id'])
    _text(observation['fixture'])
    _number(observation['duration_s'], positive=True)
    _metrics(observation['observed'])
    _require(observation['proposed_host_preference'] == 'walk', 'unsupported host preference')


def _episode(episode):
    _require(set(episode) == {'id', 'fixture', 'duration_s', 'observed', 'actual_metrics', 'actual_action'},
             'episode fields mismatch')
    _text(episode['id'])
    _text(episode['fixture'])
    _number(episode['duration_s'], positive=True)
    _metrics(episode['observed'])
    _metrics(episode['actual_metrics'])
    _require(episode['actual_action'] in ACTIONS, 'invalid observed action')


def _prediction(prediction, observation_id):
    _require(set(prediction) == {'id', 'predicted_metrics', 'predicted_action'}, 'prediction fields mismatch')
    _require(prediction['id'] == observation_id and prediction['predicted_action'] in ACTIONS,
             'prediction id/action mismatch')
    _metrics(prediction['predicted_metrics'])


def _baselines(observation, history):
    for episode in history:
        if episode['fixture'] == observation['fixture']:
            _require(math.isfinite(observation['duration_s'] / episode['duration_s']),
                     'duration ratio outside numeric range')
    result = p.baselines(observation, history)
    for prediction in result.values():
        _prediction(prediction, observation['id'])
    return result


def _content_id(observation):
    # Changing only an ID must not make a copied sample independent.
    return s.digest({k: v for k, v in observation.items() if k != 'id'})


def _mean(values):
    return math.fsum(values) / len(values)


def sign_test_p(differences):
    """Exact one-sided paired sign test on independent group MAE differences."""
    nonzero = [d for d in differences if abs(d) > POLICY['metric_regression_tolerance']]
    wins = sum(d > 0 for d in nonzero)
    n = len(nonzero)
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def evaluate_numeric_evidence(evidence, *, scope_sha256):
    """Fail closed on missing/invalid provenance; recompute errors from forecasts.

    Manifest hashes/timestamps check consistency, not external authenticity.
    An auditor must verify lineage independence and immutable artifact refs.
    Synthetic contract fixtures are not evidence of model performance.
    """
    result = dict(eligible=False, policy_sha256=s.digest(POLICY), reasons=[], batches={})
    if evidence is None:
        result['reasons'] = ['independent_validation_missing']
        return result
    try:
        _hash(scope_sha256)
        _require(evidence['schema'] == SCHEMA, 'independent validation schema required')
        manifest = evidence['manifest']
        _require(evidence['manifest_sha256'] == s.digest(manifest), 'manifest digest mismatch')
        _require(manifest['policy_sha256'] == s.digest(POLICY), 'policy was not preregistered')
        _require(manifest['scope_sha256'] == scope_sha256, 'model/runtime/baseline scope mismatch')
        _text(manifest['preregistration_ref'])
        registered = _timestamp(manifest['registered_at'])
        histories = manifest['calibration']
        _require(isinstance(histories, list), 'calibration list required')
        calibration_groups, calibration_ids, calibration_inputs = set(), set(), set()
        history = []
        for row in histories:
            _text(row['group_id'])
            _text(row['source_ref'])
            _require(_timestamp(row['observed_at']) < registered, 'calibration was not frozen before plan')
            episode = row['episode']
            _episode(episode)
            _require(episode['id'] not in calibration_ids, 'duplicate calibration episode')
            calibration_groups.add(row['group_id'])
            calibration_ids.add(episode['id'])
            calibration_inputs.add(_content_id(dict(
                id=episode['id'], fixture=episode['fixture'], duration_s=episode['duration_s'],
                observed=episode['observed'], proposed_host_preference='walk')))
            history.append(episode)
        expected = manifest['groups']
        _require(set(expected) == set(POLICY['batches']), 'two preregistered batches required')
        all_groups = set(calibration_groups)
        for batch in POLICY['batches']:
            groups = expected[batch]
            _require(isinstance(groups, list) and len(groups) >= POLICY['minimum_independent_groups_per_batch'],
                     'insufficient independent groups')
            for group in groups:
                _text(group)
                _require(group not in all_groups, 'overlapping calibration/heldout groups')
                all_groups.add(group)
        grouped = {batch: defaultdict(list) for batch in POLICY['batches']}
        seen_ids, seen_inputs = set(calibration_ids), set(calibration_inputs)
        for row in evidence['records']:
            batch, group = row['batch'], row['group_id']
            _require(batch in expected and group in expected[batch], 'unregistered group')
            _require(row['history_sha256'] == s.digest(history), 'history contamination or mismatch')
            _text(row['forecast_ref'])
            _text(row['outcome_ref'])
            frozen, observed = _timestamp(row['predicted_at']), _timestamp(row['observed_at'])
            _require(registered < frozen < observed, 'forecasts must precede outcomes after registration')
            observation = row['observation']
            _observation(observation)
            sample_id = observation['id']
            input_id = _content_id(observation)
            _require(sample_id not in seen_ids and input_id not in seen_inputs, 'reused calibration/heldout input')
            seen_ids.add(sample_id)
            seen_inputs.add(input_id)
            _metrics(row['actual_metrics'])
            _require(row['actual_action'] in ACTIONS, 'invalid actual action')
            predictions = row['predictions']
            _require(set(predictions) == set(METHODS), 'three paired predictions required')
            for prediction in predictions.values():
                _prediction(prediction, sample_id)
            local = _baselines(observation, history)
            _require(all(predictions[name] == local[name] for name in METHODS[:2]),
                     'baseline forecasts do not match common inputs')
            errors = {name: {metric: abs(predictions[name]['predicted_metrics'][metric] - row['actual_metrics'][metric])
                             for metric in m.METRICS} for name in METHODS}
            grouped[batch][group].append(errors)
        for batch in POLICY['batches']:
            _require(set(grouped[batch]) == set(expected[batch]), 'missing preregistered groups')
            # Multiple correlated transitions never increase the independent N.
            group_errors = [{name: {metric: _mean([row[name][metric] for row in rows])
                                   for metric in m.METRICS} for name in METHODS}
                            for rows in grouped[batch].values()]
            per_metric = {name: {metric: _mean([g[name][metric] for g in group_errors])
                                for metric in m.METRICS} for name in METHODS}
            mae = {name: _mean(list(per_metric[name].values())) for name in METHODS}
            comparisons = {}
            for baseline in METHODS[:2]:
                absolute_gain = mae[baseline] - mae['api']
                relative_gain = absolute_gain / mae[baseline] if mae[baseline] > 0 else 0.
                probability = sign_test_p([_mean(list(g[baseline].values())) - _mean(list(g['api'].values()))
                                           for g in group_errors])
                passes = (absolute_gain >= POLICY['minimum_absolute_gain'] and
                          relative_gain >= POLICY['minimum_relative_gain'] and
                          probability <= POLICY['maximum_sign_test_p'] and
                          all(per_metric['api'][metric] <= per_metric[baseline][metric] +
                              POLICY['metric_regression_tolerance'] for metric in m.METRICS))
                comparisons[baseline] = dict(absolute_gain=absolute_gain, relative_gain=relative_gain,
                                             sign_test_p=probability, passes=passes)
                if not passes:
                    result['reasons'].append(f'{batch}:{baseline}:numeric_gate_failed')
            result['batches'][batch] = dict(independent_groups=len(group_errors), mae=mae,
                                           per_metric_mae=per_metric, comparisons=comparisons)
        result['eligible'] = not result['reasons']
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        result['eligible'] = False
        result['reasons'] = ['invalid_or_unverifiable_independent_evidence']
    return result


def route_predictions(observations, history, *, scope_sha256, evidence=None, cached_call=None):
    """Return forecasts, never execute them; a cache miss cannot send a request.

    cached_call must be bound to the model/runtime scope AND the exact payload.
    Availability of a key/model is intentionally not an input to this function.
    """
    _hash(scope_sha256)
    _require(isinstance(observations, list) and bool(observations), 'observations required')
    _require(isinstance(history, list), 'history list required')
    for observation in observations:
        _observation(observation)
    _require(len({o['id'] for o in observations}) == len(observations), 'duplicate observation id')
    for episode in history:
        _episode(episode)
    gate = evaluate_numeric_evidence(evidence, scope_sha256=scope_sha256)
    predictions = []
    for observation in observations:
        prediction = copy.deepcopy(_baselines(observation, history)['nearest_episode'])
        available = any(e['fixture'] == observation['fixture'] for e in history)
        prediction.update(action_source='nearest_episode' if available else 'persistence_fallback',
                          numeric_source='nearest_episode' if available else 'persistence_fallback')
        predictions.append(prediction)
    result = dict(predictions=predictions, numeric_gate=gate, new_api_calls=0,
                  incremental_estimated_micro_usd=0, live_execution_supported=False,
                  reason='independent_numeric_gain_not_established')
    if not gate['eligible']:
        return result
    result['reason'] = 'eligible_but_no_matching_cache_no_live_dispatch'
    if cached_call is None:
        return result
    try:
        request = p.payload(observations, history)
        _require(cached_call['scope_sha256'] == scope_sha256, 'cached model/runtime scope mismatch')
        _require(cached_call['status'] == 'completed', 'unresolved cached request')
        _require(cached_call['request'] == request and cached_call['request_sha256'] == s.digest(request),
                 'cached request mismatch')
        api = {row['id']: row for row in p.parse(cached_call['provider_response'])}
        _require(set(api) == {o['id'] for o in observations}, 'cached prediction ids mismatch')
        for prediction in predictions:
            prediction['predicted_metrics'] = copy.deepcopy(api[prediction['id']]['predicted_metrics'])
            prediction['numeric_source'] = 'api_cached'
        result['reason'] = 'validated_numeric_cache_reused_actions_remain_memory_based'
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        result['reason'] = 'invalid_cache_no_live_dispatch'
    return result
