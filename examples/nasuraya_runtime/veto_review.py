"""Opt-in, bounded review of historical walk vetoes in local simulations only.

No expiry and no deletion: a successful probe does not grant ongoing clearance.
Thresholds are authored engineering hypotheses, not calibrated physiology.
"""
from copy import deepcopy
import math

from examples.tadash_interoception.state import digest

SCHEMA = 'nasuraya.veto-review/1'
POLICY = 'context-review-v1'
FIELDS = ('energy', 'fatigue', 'pain', 'sleep_pressure')
SAFE = {'energy': .60, 'fatigue': .35, 'pain': .25, 'sleep_pressure': .65}
HARD = {'energy': .25, 'fatigue': .52, 'pain': .40, 'sleep_pressure': .85}
DELTA = {'energy': .15, 'fatigue': .10, 'pain': .10, 'sleep_pressure': .15}
MAX_AGE_S = 2.0
MAX_GAP_S = 5.0
MAX_PROBE_S = .2
REQUIRED_SAMPLES = 3
MAX_PROBES = 1
OBS_KEYS = {'source', 'model', 'action', 'sample_id', 'sampled_at_s', 'now_s',
            'values', 'secondary_sleep_pressure', 'guard_reasons'}


def _number(value, low=0., high=1.):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_observation(obs):
    if type(obs) is not dict or set(obs) != OBS_KEYS:
        raise ValueError('closed veto observation required')
    if not _hash(obs['source']) or not _hash(obs['sample_id']):
        raise ValueError('invalid observation identity')
    if type(obs['model']) is not str or type(obs['action']) is not str:
        raise ValueError('invalid observation scope')
    if not all(_number(obs[k], 0, 1e12) for k in ('sampled_at_s', 'now_s')):
        raise ValueError('invalid observation clock')
    if type(obs['values']) is not dict or set(obs['values']) != set(FIELDS):
        raise ValueError('closed risk vector required')
    if any(v is not None and not _number(v) for v in obs['values'].values()):
        raise ValueError('invalid risk measurement')
    if obs['secondary_sleep_pressure'] is not None and not _number(obs['secondary_sleep_pressure']):
        raise ValueError('invalid secondary measurement')
    if type(obs['guard_reasons']) is not list or any(type(r) is not str for r in obs['guard_reasons']):
        raise ValueError('invalid native guard readout')


def hard_reasons(values):
    return [k for k in FIELDS if values[k] is not None and
            (values[k] < HARD[k] if k == 'energy' else values[k] > HARD[k])]


class VetoReview:
    """Replayable evidence ledger; checkpoint validation recomputes decisions."""
    def __init__(self, source):
        if not _hash(source):
            raise ValueError('source pin required')
        self.source = source
        self.history = []
        self.origins = []
        self.safe_count = 0
        self.probes_used = 0
        self.last_observation = None
        self.seen_samples = set()
        self.sample_high_water = -1.
        self.clock_high_water = -1.

    def evaluate(self, observation, *, eligible, duration):
        validate_observation(observation)
        if type(eligible) is not bool or not _number(duration, .1, 1.6):
            raise ValueError('bounded execution context required')
        o, values = observation, observation['values']
        def result(status, reason, streak=0):
            return dict(status=status, reason=reason, safe_count=streak,
                        probes_used=self.probes_used, original_veto_count=len(self.origins),
                        evidence_sha256=digest(o), permits_probe=status == 'LIMITED_RETRY')
        # No request can change the action/model/source binding by narration.
        if o['source'] != self.source or o['model'] != 'tadash_legacy_195kg' or o['action'] != 'walk':
            return result('ABSTAIN', 'scope_or_source_changed')
        age = o['now_s'] - o['sampled_at_s']
        if not 0 <= age <= MAX_AGE_S or any(v is None for v in values.values()):
            return result('ABSTAIN', 'stale_future_or_missing_observation')
        last = self.last_observation
        if (o['sample_id'] in self.seen_samples or o['sampled_at_s'] <= self.sample_high_water
                or o['now_s'] < self.clock_high_water):
            return result('ABSTAIN', 'observation_not_new')
        secondary = o['secondary_sleep_pressure']
        if secondary is not None and abs(secondary - values['sleep_pressure']) > .10 + 1e-12:
            return result('ABSTAIN', 'contradictory_observations')
        if not self.origins:
            return result('NO_PRIOR_VETO', 'original_controller_and_native_guard_apply')
        if hard_reasons(values) or o['guard_reasons']:
            return result('KEEP_VETO', 'current_native_restriction')
        if self.probes_used >= MAX_PROBES:
            return result('KEEP_VETO', 'session_probe_budget_exhausted')
        origin = self.origins[-1]['observation']['values']
        reasons = hard_reasons(origin)
        if not reasons:
            return result('ABSTAIN', 'original_veto_cause_not_explained')
        if any(values[k] < SAFE[k] if k == 'energy' else values[k] > SAFE[k] for k in FIELDS):
            return result('REVIEW_AGAIN', 'below_hard_limit_but_outside_recovery_margin')
        if any((values[k] - origin[k] if k == 'energy' else origin[k] - values[k]) + 1e-12 < DELTA[k]
               for k in reasons):
            return result('REVIEW_AGAIN', 'insufficient_change_from_original_context')
        count = min(REQUIRED_SAMPLES, self.safe_count + 1)
        if last and o['sampled_at_s'] - last['sampled_at_s'] > MAX_GAP_S:
            count = 1
        if count < REQUIRED_SAMPLES:
            return result('REVIEW_AGAIN', 'need_consecutive_new_safe_observations', count)
        if not eligible:
            return result('REVIEW_AGAIN', 'existing_goal_workload_or_route_does_not_allow_walk', count)
        if duration > MAX_PROBE_S + 1e-9:
            return result('REVIEW_AGAIN', 'probe_window_too_long', count)
        return result('LIMITED_RETRY', 'changed_context_confirmed_native_guard_still_required', count)

    def complete(self, observation, *, eligible, duration, requested, executed):
        if len(self.history) >= 100:
            raise ValueError('bounded review ledger exhausted')
        if requested not in ('walk', 'observe') or executed not in ('walk', 'observe', 'protect'):
            raise ValueError('unsupported local action')
        decision = self.evaluate(observation, eligible=eligible, duration=duration)
        if requested == 'walk' and decision['status'] not in ('NO_PRIOR_VETO', 'LIMITED_RETRY'):
            raise ValueError('walk violates experimental review')
        row = dict(observation=deepcopy(observation), eligible=eligible, duration=duration,
                   requested=requested, executed=executed, decision=decision)
        if decision['permits_probe']:
            if requested != 'walk':
                raise ValueError('probe reservation must be consumed in this transition')
            self.probes_used += 1
        self.safe_count = decision['safe_count']
        self.last_observation = deepcopy(observation)
        self.seen_samples.add(observation['sample_id'])
        self.clock_high_water = max(self.clock_high_water, observation['now_s'])
        if observation['sampled_at_s'] <= observation['now_s']:
            self.sample_high_water = max(self.sample_high_water, observation['sampled_at_s'])
        if requested == 'walk' and executed != 'walk':
            self.origins.append(deepcopy(row))
            self.safe_count = 0
        self.history.append(row)
        return decision

    def checkpoint(self):
        value = dict(schema=SCHEMA, policy=POLICY, source=self.source, history=deepcopy(self.history))
        return dict(value=value, sha256=digest(value))

    @classmethod
    def restore(cls, checkpoint, *, source):
        if type(checkpoint) is not dict or set(checkpoint) != {'value', 'sha256'}:
            raise ValueError('invalid review checkpoint')
        value = checkpoint['value']
        if digest(value) != checkpoint['sha256'] or type(value) is not dict or set(value) != {'schema', 'policy', 'source', 'history'}:
            raise ValueError('review checkpoint integrity mismatch')
        if value['schema'] != SCHEMA or value['policy'] != POLICY or value['source'] != source:
            raise ValueError('review checkpoint policy or source mismatch')
        if type(value['history']) is not list or len(value['history']) > 100:
            raise ValueError('invalid review history')
        result = cls(source)
        for row in value['history']:
            if type(row) is not dict or set(row) != {'observation', 'eligible', 'duration', 'requested', 'executed', 'decision'}:
                raise ValueError('invalid review event')
            actual = result.complete(**{k: v for k, v in row.items() if k != 'decision'})
            if actual != row['decision']:
                raise ValueError('review replay disagrees with retained decision')
        return result

    def summary(self):
        return dict(original_veto_count=len(self.origins), probes_used=self.probes_used,
                    safe_count=self.safe_count, events=len(self.history),
                    original_veto_retained=bool(self.origins), automatic_expiry=False)
