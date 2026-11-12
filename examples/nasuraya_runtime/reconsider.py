"""Bounded reconsideration from the owned native checkpoint, never a timer."""
from copy import deepcopy
import math

from examples.dios_nous.unified.body import normalize_native

FIELDS = ('energy', 'fatigue', 'pain', 'sleep_pressure')


def observation(native):
    normalized = normalize_native(native['export'], now_s=native['clock'])
    checkpoint = native['checkpoint']
    if (normalized['status'] != 'fresh' or native['export']['native_checkpoint_sha256'] != checkpoint['sha256']
            or native['export']['revision'] != checkpoint['payload']['revision']):
        raise ValueError('fresh observation bound to owned checkpoint required')
    values = {k: native['export']['minimum_state'][k] for k in FIELDS}
    if any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in values.values()):
        raise ValueError('complete finite native retry indices required')
    return {'values': values, 'revision': native['export']['revision'],
            'clock': native['clock'], 'checkpoint_sha': checkpoint['sha256']}


def block(native):
    sample = observation(native)
    v = sample['values']
    causes = [name for name, condition in (('energy', v['energy'] < .25),
        ('fatigue', v['fatigue'] > .52), ('pain', v['pain'] > .40),
        ('sleep_pressure', v['sleep_pressure'] > .85)) if condition]
    return {'blocked_at': sample, 'known_blockers': causes, 'safe_streak': 0,
            'last_safe': None}


def assess(previous, native, *, enabled):
    """Return an updated checkpoint plus a preflight requirement, not clearance.

    The actual native owner still has to forecast and then execute any retry.
    Success of a different action, time alone and repeated snapshots do not count.
    """
    result = deepcopy(previous)
    receipt = {'eligible_for_native_preflight': False, 'reason': 'policy_disabled',
               'observations_required': 2, 'forecast_is_observed_success': False}
    if not enabled: return result, receipt
    if result is None or not result['known_blockers']:
        return result, dict(receipt, reason='unknown_veto_cause_requires_review')
    sample = observation(native)
    last = result['last_safe'] or result['blocked_at']
    if (sample['revision'] <= last['revision'] or sample['clock'] <= last['clock']
            or sample['checkpoint_sha'] == last['checkpoint_sha']):
        return result, dict(receipt, reason='no_new_owned_observation')
    v = sample['values']
    safe = v['energy'] >= .35 and v['fatigue'] <= .42 and v['pain'] <= .30 and v['sleep_pressure'] <= .75
    result['safe_streak'] = min(2, result['safe_streak'] + 1) if safe else 0
    result['last_safe'] = sample
    ready = result['safe_streak'] >= 2
    return result, dict(receipt, eligible_for_native_preflight=ready,
        reason='two_safe_owned_observations' if ready else 'awaiting_recovery_evidence',
        current=sample, known_blockers=result['known_blockers'], safe_streak=result['safe_streak'])
