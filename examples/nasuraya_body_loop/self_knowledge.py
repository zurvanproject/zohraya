"""Pre-outcome action estimates from receipt-backed software experience.

This is an empirical categorical forecaster, not a consciousness measure.
The pooled comparison sees the same prior outcomes and conditions on the same
preference and duration; only the local estimate additionally uses context.
No native simulator, model API, clock, or persistent store is accessed here.
"""
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import math


SCHEMA = 'nasuraya-action-forecast/1'
SCORE_SCHEMA = 'nasuraya-action-forecast-score/1'
BUCKETS = ('walk', 'observe', 'protect', 'other')
MIN_SAMPLES = 3


def _digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _native_source(value):
    return (isinstance(value, str) and value.startswith('native-decision://')
            and len(value) > len('native-decision://'))


def _duration(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not .1 <= value <= 1.
            or abs(value * 10 - round(value * 10)) > 1e-8):
        raise ValueError('duration_s must be .1..1 in .1-second increments')
    return value


def _bucket(action):
    if not isinstance(action, str) or not action.strip():
        raise ValueError('nonempty actual action required')
    return action if action in BUCKETS[:3] else 'other'


def _distribution(rows):
    counts = dict.fromkeys(BUCKETS, 1)  # One explicit Laplace pseudocount each.
    for row in rows:
        counts[_bucket(row['actual_action'])] += 1
    return {key: counts[key] / (len(rows) + len(BUCKETS)) for key in BUCKETS}


def forecast_action(episodes, *, context, preferred, duration_s, enabled=True):
    """Freeze an estimate using only earlier observed software outcomes.

    Archived observations remain evidence. Legacy observations without a
    duration are counted as excluded, never assigned the current duration.
    ``insufficient_evidence`` is a sample-count guard, not a calibrated bound.
    """
    _duration(duration_s)
    if not isinstance(context, str) or preferred not in ('walk', 'observe'):
        raise ValueError('physical context and walk/observe preference required')
    if type(enabled) is not bool:
        raise ValueError('explicit boolean enabled flag required')
    result = dict(schema=SCHEMA, enabled=enabled, context=context,
                  preferred=preferred, duration_s=duration_s,
                  distribution=None, pooled_distribution=None,
                  samples=0, pooled_samples=0, source_ids=[], pooled_source_ids=[],
                  legacy_excluded=0, status='disabled', predicted_action=None,
                  model_digest=None,
                  scope='empirical software-action estimate; not calibrated confidence or subjective awareness')
    if not enabled:
        return result
    pooled = []
    legacy_excluded = 0
    for episode in episodes:
        if (not isinstance(episode, Mapping)
                or episode.get('kind') != 'observed_software_outcome'
                or not _native_source(episode.get('source'))):
            continue
        if 'duration_s' not in episode:
            legacy_excluded += 1
            continue
        # Corrupt receipts must not silently become counts in a model.
        _duration(episode['duration_s'])
        _bucket(episode.get('actual_action'))
        if not isinstance(episode.get('id'), str) or not episode['id']:
            raise ValueError('observed episode ID required')
        if (episode.get('preferred') == preferred
                and episode['duration_s'] == duration_s):
            pooled.append(episode)
    local = [episode for episode in pooled if episode.get('context') == context]
    distribution = _distribution(local)
    result.update(distribution=distribution, pooled_distribution=_distribution(pooled),
                  samples=len(local), pooled_samples=len(pooled),
                  source_ids=[row['id'] for row in local],
                  pooled_source_ids=[row['id'] for row in pooled],
                  legacy_excluded=legacy_excluded,
                  status=('insufficient_evidence' if len(local) < MIN_SAMPLES else 'empirical_estimate'),
                  predicted_action=(None if len(local) < MIN_SAMPLES else
                                    max(BUCKETS, key=lambda key: distribution[key])))
    evidence = [{key: row.get(key) for key in
                 ('id', 'source', 'context', 'preferred', 'duration_s', 'actual_action')}
                for row in pooled]
    result['model_digest'] = _digest(dict(context=context, preferred=preferred,
        duration_s=duration_s, laplace_alpha=1, buckets=BUCKETS, evidence=evidence))
    return result


def _validate_distribution(value):
    if not isinstance(value, Mapping) or set(value) != set(BUCKETS):
        raise ValueError('complete four-bucket probability distribution required')
    if any(isinstance(p, bool) or not isinstance(p, (int, float))
           or not math.isfinite(p) or not 0 <= p <= 1 for p in value.values()):
        raise ValueError('finite probabilities in [0, 1] required')
    if not math.isclose(sum(value.values()), 1., rel_tol=0., abs_tol=1e-12):
        raise ValueError('probabilities must sum to one')


def score_action(forecast, actual_action, source):
    """Score a frozen forecast against a later native outcome, without learning.

    The multiclass Brier score is the SUM of four squared errors (range 0..2,
    lower is better). Disabled forecasts have no score and enter neither the
    numerator nor denominator. Enabled cold starts are scored in their own
    explicitly low-support stratum.
    """
    if forecast.get('schema') != SCHEMA or type(forecast.get('enabled')) is not bool:
        raise ValueError('action forecast schema and enabled flag required')
    if not forecast['enabled']:
        return None
    for name in ('distribution', 'pooled_distribution'):
        _validate_distribution(forecast.get(name))
    for name in ('samples', 'pooled_samples'):
        if type(forecast.get(name)) is not int or forecast[name] < 0:
            raise ValueError('nonnegative sample counts required')
    if not _native_source(source):
        raise ValueError('authoritative native-decision source required')
    bucket = _bucket(actual_action)
    def brier(distribution):
        return sum((distribution[key] - float(key == bucket)) ** 2 for key in BUCKETS)
    result = dict(schema=SCORE_SCHEMA, actual=bucket, actual_action=actual_action,
                  brier=brier(forecast['distribution']),
                  pooled_brier=brier(forecast['pooled_distribution']), source=source,
                  status=('insufficient_evidence' if forecast['samples'] < MIN_SAMPLES
                          else 'empirical_estimate'),
                  samples=forecast['samples'], pooled_samples=forecast['pooled_samples'],
                  distribution=deepcopy(forecast['distribution']),
                  pooled_distribution=deepcopy(forecast['pooled_distribution']),
                  source_ids=list(forecast['source_ids']),
                  pooled_source_ids=list(forecast['pooled_source_ids']),
                  model_digest=forecast['model_digest'])
    result['evidence_digest'] = _digest(result)
    return result


def summarize_action_forecasts(intents):
    """Aggregate saved prequential scores; do not re-fit on later episodes.

    Every row was unseen at forecast time, but these temporally ordered scores
    are not an independent or IID holdout. Failure and disabled results are
    excluded; low-support predictions are reported separately.
    """
    groups = {'cold_start': [], 'supported': []}
    evidence = []
    for request_id, intent in sorted(intents.items()):
        result = intent.get('result')
        if not isinstance(result, Mapping):
            continue
        receipt = result.get('native_receipt', {})
        if receipt and receipt.get('status') != 'complete':
            continue
        score = result.get('action_forecast_score')
        if score is None:
            continue
        # Validate the saved outcome, probability vectors and evidence digest.
        if (score.get('schema') != SCORE_SCHEMA
                or score.get('evidence_digest') != _digest({
                    key: value for key, value in score.items() if key != 'evidence_digest'})):
            raise ValueError('saved action score integrity mismatch')
        checked = score_action(dict(schema=SCHEMA, enabled=True, **{
            key: score[key] for key in ('distribution', 'pooled_distribution', 'samples',
                'pooled_samples', 'source_ids', 'pooled_source_ids', 'model_digest')}),
            score['actual_action'], score['source'])
        if checked != score:
            raise ValueError('saved action score differs from its frozen probabilities')
        group = 'cold_start' if score['samples'] < MIN_SAMPLES else 'supported'
        groups[group].append(score)
        evidence.append(dict(request_id=request_id, score=score))
    summary = dict(schema='nasuraya-action-forecast-summary/1',
                   scored=len(evidence), excluded=len(intents) - len(evidence),
                   evidence_digest=_digest(evidence),
                   scope='prequential software outcomes; pooled frequency baseline, not an independent observer or consciousness test')
    for name, rows in groups.items():
        count = len(rows)
        local = sum(row['brier'] for row in rows) / count if count else None
        pooled = sum(row['pooled_brier'] for row in rows) / count if count else None
        summary[name] = dict(count=count, mean_brier=local, mean_pooled_brier=pooled,
                             pooled_minus_local=(pooled - local if count else None))
    return summary
