"""Pure matched-observation sensitivity audit of an engineered affect policy.

The callback must be a pure base policy, not a body executor or this audit's
wrapper. Interventions describe controller numbers, never experienced emotion.
Only current policy inputs are copied; accumulated intents are not re-embedded.
"""
from copy import deepcopy
import math

from reflection_cycle import digest
from .host import validate_duration


POLICY_KEYS = ('flags', 'affect', 'error_ema', 'predictors', 'episodes')
SCHEMA = 'nasuraya-affect-audit/1'


def _affect(value):
    result = {key: value[key] for key in ('valence', 'arousal')}
    for number in result.values():
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not 0 <= number <= 1):
            raise ValueError('finite normalized affect inputs required')
    return result


def _effective(state):
    return deepcopy(state['affect']) if state['flags']['affect'] else dict(valence=.5, arousal=0.)


def audit_affect(state, snapshot, duration_s, policy_fn):
    """Compare eight pure plans on one immutable pre-action observation.

Low/high channel variants retain the factual affect flag. With affect disabled
they are negative controls; the enabled neutral variant is explicitly separate.
Results show policy sensitivity, not executed counterfactual body outcomes.
"""
    validate_duration(duration_s)
    stored = _affect(state['affect'])
    if type(state['flags']['affect']) is not bool:
        raise ValueError('explicit boolean affect flag required')
    if (not isinstance(snapshot.get('checkpoint_sha256'), str)
            or not snapshot['checkpoint_sha256']
            or type(snapshot.get('revision')) is not int or snapshot['revision'] < 0):
        raise ValueError('checkpoint digest and nonnegative body revision required')
    original_state_digest, original_snapshot_digest = digest(state), digest(snapshot)
    working = deepcopy({key: state[key] for key in POLICY_KEYS})
    working['affect'] = stored
    policy_state_digest = digest(working)
    observed = deepcopy(snapshot)
    variants = {}
    specifications = (
        ('factual', None, {}),
        ('affect_off', False, dict(valence=.5, arousal=0.)),
        ('neutral', True, dict(valence=.5, arousal=0.)),
        ('valence_low', None, dict(valence=0.)),
        ('valence_high', None, dict(valence=1.)),
        ('arousal_low', None, dict(arousal=0.)),
        ('arousal_high', None, dict(arousal=1.)),
        ('sham', None, {}),
    )
    for name, enabled, change in specifications:
        # Unchanged nested inputs are shared only inside our private copy and
        # checked after each callback. A mutating callback cannot alter callers.
        candidate = dict(working, flags=dict(working['flags']), affect=dict(stored))
        candidate['affect'].update(change)
        if enabled is not None:
            candidate['flags']['affect'] = enabled
        if name == 'sham':
            candidate['audit_label'] = 'unused identity-only sham'
        before = digest(candidate)
        result = policy_fn(candidate, observed, duration_s)
        if digest(candidate) != before or digest(observed) != original_snapshot_digest:
            raise ValueError('audit policy callback must not mutate its inputs')
        scores = deepcopy(result['scores'])
        if (not scores or result['preferred'] not in scores
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in scores.values())):
            raise ValueError('finite policy scores and a scored preference required')
        variants[name] = dict(
            flags=deepcopy(candidate['flags']), affect_stored=deepcopy(candidate['affect']),
            affect_effective=_effective(candidate), scores=scores,
            preferred=result['preferred'], prediction=deepcopy(result['prediction']))
    if digest(state) != original_state_digest or digest(snapshot) != original_snapshot_digest:
        raise ValueError('audit changed caller inputs')
    fields = ('scores', 'preferred', 'prediction')
    same = lambda a, b: all(variants[a][key] == variants[b][key] for key in fields)
    if not same('factual', 'sham'):
        raise ValueError('unused sham metadata changed the policy')
    if not same('affect_off', 'neutral'):
        raise ValueError('disabled affect differs from enabled neutral affect')
    factual = variants['factual']
    for variant in variants.values():
        if set(variant['scores']) != set(factual['scores']):
            raise ValueError('affect intervention changed the policy action set')
        variant['score_delta'] = {key: value-factual['scores'][key]
                                  for key, value in variant['scores'].items()}
        variant['changed_preference'] = variant['preferred'] != factual['preferred']
    return dict(
        schema=SCHEMA, scope='matched_snapshot_policy_sensitivity_only',
        subjective_feeling_claim=False, native_cycles=0,
        observation=dict(checkpoint_sha256=snapshot['checkpoint_sha256'],
            revision=snapshot['revision'], snapshot_sha256=original_snapshot_digest,
            state_sha256=policy_state_digest, duration_s=duration_s,
            source='persisted_controller_state_before_action',
            affect_stored=stored, affect_effective=_effective(working),
            affect_enabled=working['flags']['affect']),
        variants=variants,
        checks=dict(state_unchanged=True, snapshot_unchanged=True,
                    sham_matches_factual=True, disabled_matches_neutral=True))
