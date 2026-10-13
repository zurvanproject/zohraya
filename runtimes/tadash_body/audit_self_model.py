"""Inspectable capability/uncertainty read-out of the saved computational body."""
from copy import deepcopy
from unified_body_v2 import TTL_S

def assess(body, *, at_simulated_s=None):
    t=body.owner.owner.body.state.time_s
    now=t if at_simulated_s is None else at_simulated_s
    if now<t:raise ValueError('future saved body relative to evaluation clock')
    state=body.owner.body()
    m=state['minimum_state']; age=now-t
    packet_fresh=age<=TTL_S
    sensors=body.modules['senses']['samples']
    valid=[k for k,v in sensors.items() if 0<=now-v['sampled_at_s']<=TTL_S]
    expired=[k for k in sensors if k not in valid]
    unknown=['empirical_calibration','arterial_gases','independent_3d_organ_geometry',
             'physical_sensor_attachment','external_world_without_supplied_observation']
    if not packet_fresh:unknown.append('current_body_state')
    unknown += ['sensory_channel:'+k for k in ('vision','hearing','smell','taste','touch') if k not in valid]
    reasons=[]
    if not packet_fresh:reasons.append('request_current_body_sample')
    if m['energy']<.25:reasons.append('low_energy')
    if m['fatigue']>.52:reasons.append('fatigue')
    if m['pain']>.40:reasons.append('pain')
    if m['sleep_pressure']>.85:reasons.append('sleep_pressure')
    predictions=body.owner.aux['prediction_history']
    errors=[x['mean_scaled_absolute_error'] for x in predictions[-16:]]
    return dict(schema='nasuraya-audited-self-model/1.0',kind='readout_of_saved_simulation',
        body_revision=body.revision,body_time_s=t,evaluation_time_s=now,age_s=age,
        body_state_fresh=packet_fresh,saved_minimum_state=deepcopy(m),
        available_sensory_channels=valid,expired_sensory_channels=expired,
        upper_controller_walk_guard_allows=not bool(reasons),walking_restrictions=reasons,
        request_new_evidence=not packet_fresh or bool(expired),unknown=unknown,
        recent_prediction_errors=errors,
        uncertainty=body.owner.aux['uncertainty'],uncertainty_is='engineering_index_not_calibrated_probability',
        unified_parameter_learning_demonstrated=False,
        empirical_validation=False,subjective_experience_probability=None)
