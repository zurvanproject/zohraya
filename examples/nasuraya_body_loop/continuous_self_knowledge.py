"""Local action forecasts with explicit observational support.

Only normalized pre-action observations and earlier receipt-backed outcomes are
used. This module never imports or invokes the native controller, a model API,
or a clock. Its probabilities are empirical estimates, not confidence bounds.
"""
from collections.abc import Mapping
from copy import deepcopy
import math

from .self_knowledge import (BUCKETS, _bucket, _digest, _duration, _native_source,
                             _validate_distribution)


SCHEMA = 'nasuraya-continuous-action-forecast/1'
SCORE_SCHEMA = 'nasuraya-continuous-action-score/1'
FEATURES = ('energy', 'fatigue', 'pain', 'sleep_pressure')
DEFAULT_CONFIG = dict(radius=.12, neighbors=9, prior_strength=2.,
                      min_samples=3, min_agreement=.75)


def validate_config(config=None):
    value = deepcopy(DEFAULT_CONFIG if config is None else config)
    if not isinstance(value, Mapping) or set(value) != set(DEFAULT_CONFIG):
        raise ValueError('complete continuous forecast configuration required')
    for name in ('radius', 'prior_strength', 'min_agreement'):
        x = value[name]
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ValueError('finite forecast parameters required')
    if not 0 < value['radius'] <= 1 or not 0 < value['prior_strength'] <= 100:
        raise ValueError('positive bounded radius and prior strength required')
    if not .5 < value['min_agreement'] <= 1:
        raise ValueError('majority agreement threshold required')
    for name in ('neighbors', 'min_samples'):
        if type(value[name]) is not int or not 1 <= value[name] <= 1000:
            raise ValueError('positive bounded integer sample limits required')
    if value['min_samples'] > value['neighbors']:
        raise ValueError('min_samples cannot exceed neighbors')
    return dict(value)


def features(value):
    if not isinstance(value, Mapping) or set(value) != set(FEATURES):
        raise ValueError('four pre-action body features required')
    result = dict(value)
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or not 0 <= x <= 1 for x in result.values()):
        raise ValueError('finite normalized pre-action features required')
    return result


def feedback_state(value=None):
    value = dict(walk=None, observe=None) if value is None else value
    if (not isinstance(value, Mapping) or set(value) != {'walk', 'observe'}
            or any(x is not None and type(x) is not bool for x in value.values())):
        raise ValueError('explicit walk/observe feedback booleans or null required')
    return dict(value)


def native_feedback(loop, snapshot, duration_s):
    """Read the native ledger's currently applicable feedback, not its decision.

    This performs no decide/execute call. Signature/expiry handling belongs to
    the existing ledger so the observer does not invent another memory policy.
    """
    from reflection_cycle import action_signature
    request = loop.make_request('forecast-observation', snapshot, duration_s)
    signatures = {a['id']: action_signature(a) for a in request['actions']}
    recalled = loop.engine.recall(request['context'], request['topic'],
        signatures=list(signatures.values()), at_utc=request['at_utc'])
    states, sources = {}, {}
    for action, signature in signatures.items():
        prior = recalled.get(signature)
        states[action] = prior['success'] if prior else None
        sources[action] = prior['decision_id'] if prior else None
    return dict(state=feedback_state(states), source_ids=sources)


def observed_history(state):
    """Join the existing ledger, including old *pre-action* reservations.

    No second memory is written. Missing observations remain excluded rather
    than being inferred from the later result. The caller's checked experience
    envelope is the trust boundary; source strings are not signatures.
    """
    rows = []
    for episode in state['episodes']:
        row = deepcopy(episode)
        intent = state['intents'].get(episode['id'])
        if intent and intent.get('result') is not None:
            result = intent['result']
            prediction = result.get('prediction', {})
            receipt = result.get('native_receipt', {})
            if (receipt.get('status') == 'complete'
                    and prediction.get('source') == episode.get('source')
                    and receipt.get('actual_action') == episode.get('actual_action')
                    and intent.get('duration_s') == episode.get('duration_s')
                    and intent['plan']['preferred'] == episode.get('preferred')):
                before = features({k: intent['snapshot']['minimum_state'][k] for k in FEATURES})
                if before != prediction.get('before'):
                    raise ValueError('saved pre-action observation differs from prediction')
                row['before'] = before
                row['before_checkpoint_sha256'] = intent['snapshot']['checkpoint_sha256']
                reserved = intent['plan'].get('continuous_action_forecast')
                if reserved is not None:
                    row['feedback'] = feedback_state(reserved['feedback'])
        rows.append(row)
    return rows


def _eligible(episodes, preferred, duration_s):
    rows, seen_ids, seen_sources, excluded = [], set(), set(), 0
    for episode in episodes:
        if (not isinstance(episode, Mapping)
                or episode.get('kind') != 'observed_software_outcome'
                or not _native_source(episode.get('source'))):
            continue
        identifier, source = episode.get('id'), episode['source']
        if not isinstance(identifier, str) or not identifier:
            raise ValueError('observed episode ID required')
        if identifier in seen_ids or source in seen_sources:
            raise ValueError('duplicate observed episode or receipt source')
        seen_ids.add(identifier); seen_sources.add(source)
        if any(k not in episode for k in ('duration_s', 'before', 'feedback')):
            excluded += 1
            continue
        _duration(episode['duration_s'])
        before = features(episode['before'])
        feedback = feedback_state(episode['feedback'])
        _bucket(episode.get('actual_action'))
        if episode.get('preferred') not in ('walk', 'observe'):
            raise ValueError('observed controller preference required')
        if episode['preferred'] == preferred and episode['duration_s'] == duration_s:
            rows.append(dict(id=identifier, source=source, before=before, feedback=feedback,
                             actual_action=episode['actual_action']))
    return rows, excluded


def forecast_action(episodes, *, before, preferred, duration_s, feedback=None, config=None, enabled=True):
    """Freeze a local estimate or a pooled fallback before observing an outcome.

    L-infinity distance treats each observed feature on its declared 0..1 scale.
    Nearest receipts within a fixed radius vote with equal weight, shrunk toward
    the pooled distribution. With missing/distant/conflicting evidence, a
    probability vector is still scored but no categorical claim is emitted.
    Recent receipts break equal-distance ties; order is part of the model digest.
    """
    before = features(before); feedback = feedback_state(feedback)
    config = validate_config(config); _duration(duration_s)
    if preferred not in ('walk', 'observe') or type(enabled) is not bool:
        raise ValueError('walk/observe preference and boolean enabled required')
    result = dict(schema=SCHEMA, enabled=enabled, before=before, feedback=feedback, preferred=preferred,
        duration_s=duration_s, config=config, distribution=None, pooled_distribution=None,
        source_ids=[], pooled_source_ids=[], samples=0, pooled_samples=0,
        excluded_missing_observation=0, nearest_distance=None, agreement=None,
        status='disabled', predicted_action=None, model_digest=None,
        scope='receipt-grounded local software forecast; support is not calibrated certainty')
    if not enabled:
        return result
    rows, excluded = _eligible(episodes, preferred, duration_s)
    counts = dict.fromkeys(BUCKETS, 1.)
    for row in rows:
        counts[_bucket(row['actual_action'])] += 1
    pooled = {a: counts[a] / (len(rows) + len(BUCKETS)) for a in BUCKETS}
    ranked = sorted((max(abs(before[k] - row['before'][k]) for k in FEATURES),
                     -i, row['id'], row) for i, row in enumerate(rows))
    matching = [item for item in ranked if item[3]['feedback'] == feedback]
    neighbors = [item for item in matching if item[0] <= config['radius']][:config['neighbors']]
    votes = dict.fromkeys(BUCKETS, 0)
    for *_, row in neighbors:
        votes[_bucket(row['actual_action'])] += 1
    n = len(neighbors)
    strength = config['prior_strength']
    distribution = {a: (votes[a] + strength * pooled[a]) / (n + strength) for a in BUCKETS}
    agreement = max(votes.values()) / n if n else None
    if not rows:
        status = 'no_observed_history'
    elif not matching:
        status = 'unseen_feedback_state'
    elif not neighbors:
        status = 'outside_observed_support'
    elif n < config['min_samples']:
        status = 'insufficient_local_evidence'
    elif agreement < config['min_agreement']:
        status = 'conflicting_local_evidence'
    else:
        status = 'supported_local_estimate'
    result.update(distribution=distribution, pooled_distribution=pooled,
        source_ids=[item[3]['id'] for item in neighbors],
        pooled_source_ids=[row['id'] for row in rows], samples=n, pooled_samples=len(rows),
        excluded_missing_observation=excluded,
        nearest_distance=matching[0][0] if matching else None, agreement=agreement,
        status=status, predicted_action=(max(BUCKETS, key=distribution.get)
            if status == 'supported_local_estimate' else None))
    result['model_digest'] = _digest(dict(before=before, feedback=feedback, preferred=preferred,
        duration_s=duration_s, config=config, evidence=rows))
    result['forecast_digest'] = _digest(result)
    return result


def score_action(forecast, actual_action, source):
    """Score the saved pre-action vector; never refit on the answer."""
    if forecast.get('schema') != SCHEMA or type(forecast.get('enabled')) is not bool:
        raise ValueError('continuous forecast contract required')
    if not forecast['enabled']:
        return None
    if forecast.get('forecast_digest') != _digest({k: v for k, v in forecast.items()
                                                  if k != 'forecast_digest'}):
        raise ValueError('frozen continuous forecast integrity mismatch')
    for key in ('distribution', 'pooled_distribution'):
        _validate_distribution(forecast[key])
    if not _native_source(source):
        raise ValueError('authoritative native-decision source required')
    actual = _bucket(actual_action)
    brier = lambda p: sum((p[a] - (a == actual))**2 for a in BUCKETS)
    result = dict(schema=SCORE_SCHEMA, actual=actual, actual_action=actual_action, source=source,
        forecast=deepcopy(forecast), brier=brier(forecast['distribution']),
        pooled_brier=brier(forecast['pooled_distribution']),
        asserted_correct=(forecast['predicted_action'] == actual
                          if forecast['predicted_action'] is not None else None))
    result['evidence_digest'] = _digest(result)
    return result


def summarize(intents):
    rows = []
    for intent in intents.values():
        result = intent.get('result') or {}
        score = result.get('continuous_action_score')
        if score is None:
            continue
        if result['native_receipt']['status'] != 'complete':
            raise ValueError('continuous score attached to incomplete native receipt')
        if score_action(score['forecast'], score['actual_action'], score['source']) != score:
            raise ValueError('saved continuous score integrity mismatch')
        if score['forecast'] != intent['plan'].get('continuous_action_forecast'):
            raise ValueError('continuous score differs from reserved forecast')
        if score['actual_action'] != result['native_receipt']['actual_action']:
            raise ValueError('continuous score differs from native action')
        if score['source'] != result['prediction']['source']:
            raise ValueError('continuous score differs from native evidence source')
        rows.append(score)
    supported = [s for s in rows if s['asserted_correct'] is not None]
    mean = lambda values: sum(values)/len(values) if values else None
    return dict(schema='nasuraya-continuous-action-summary/1', scored=len(rows),
        supported=len(supported), abstained=len(rows)-len(supported),
        mean_brier=mean([s['brier'] for s in rows]),
        mean_pooled_brier=mean([s['pooled_brier'] for s in rows]),
        supported_accuracy=mean([int(s['asserted_correct']) for s in supported]),
        statuses={status: sum(s['forecast']['status'] == status for s in rows)
                  for status in sorted({s['forecast']['status'] for s in rows})},
        evidence_digest=_digest(rows),
        scope='saved prequential outcomes; abstention and correctness reported separately')
