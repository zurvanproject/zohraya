"""One bounded hypothetical native rollout. Never a measured experience.

Only the current checkpoint and authorized request are available here. A future
unobserved disturbance cannot be ruled out by this deterministic kernel.
"""
from datetime import datetime, timedelta
import math
import re

from .self_maintenance import MaintenanceBlocked

SCHEMA = 'nasuraya-native-preflight/1'


def preview(body, action):
    """Restore an isolated clone; do not update the caller, budget or learner."""
    if action not in ('walk', 'observe'):
        raise ValueError('only walk and observe are authorized')
    checkpoint = body.checkpoint()
    trial = type(body).restore(checkpoint)
    at = (datetime.fromisoformat(trial.owner.wall_utc) + timedelta(seconds=.1)).isoformat()
    event = 'preflight-' + checkpoint['sha256'][:24] + '-' + action
    receipt = trial.cycle(event_id=event, at_utc=at, duration_s=.1,
                         requested=action, external={})
    frame = trial.owner.physical.last
    motor = frame['motor']
    deficient = {}
    for channel, required in motor['postural_requests_N'].items():
        actual = motor['postural_force_N'][channel]
        if required > 1e-9 and actual / required < .999:
            deficient[channel] = {'required_N': required, 'predicted_N': actual,
                                  'hazard_cap': motor['hazard_fraction_cap'][channel]}
    result = {'schema': SCHEMA, 'kind': 'hypothetical_native_rollout',
              'before_sha': checkpoint['sha256'], 'requested_action': action,
              'duration_s': .1, 'predicted_action': receipt['owner']['selected_action'],
              'physical_model_valid': receipt['owner']['physical_model_valid'],
              'failed_reason': frame['posture']['failed_reason'],
              'joint_support_fraction': frame['contact']['joint_support_fraction'],
              'postural_allocation_fraction': motor['priority_fractions']['postural'],
              'deficient_channels': deficient,
              'forecast_sha': trial.checkpoint()['sha256'],
              'future_unobserved_inputs_covered': False,
              'eligible_for_learning': False}
    validate(result, checkpoint['sha256'], action)
    if body.checkpoint() != checkpoint:
        raise MaintenanceBlocked('native preflight altered source body')
    return result


def validate(result, before_sha, action):
    if (action not in ('walk', 'observe') or not isinstance(before_sha, str)
            or not re.fullmatch('[0-9a-f]{64}', before_sha)
            or not isinstance(result, dict) or result.get('schema') != SCHEMA
            or result.get('kind') != 'hypothetical_native_rollout'
            or result.get('before_sha') != before_sha
            or result.get('requested_action') != action
            or result.get('duration_s') != .1
            or type(result.get('physical_model_valid')) is not bool
            or result.get('eligible_for_learning') is not False
            or result.get('future_unobserved_inputs_covered') is not False):
        raise MaintenanceBlocked('invalid native preflight provenance')
    if not isinstance(result.get('forecast_sha'), str) or not re.fullmatch('[0-9a-f]{64}', result['forecast_sha']):
        raise MaintenanceBlocked('invalid native preflight checkpoint')
    for key in ('joint_support_fraction', 'postural_allocation_fraction'):
        value = result.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1.000001:
            raise MaintenanceBlocked('invalid native preflight support')
    return result
