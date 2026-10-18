"""Read-only adapters. None has native execution or policy-update authority."""
from copy import deepcopy
import hashlib
import json
import math

from .integrity import verify_sources


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def monitoring_stats(rows):
    """Use the actual MMB statistic, not its hand-assigned model profiles.

    Here correct means counterfactual native walk admission. KEEP is the
    recorded prospective decision. This is a body-specific adaptation of the
    statistic, not the 524-item language benchmark or a consciousness score.
    """
    verify_sources()
    from .vendor.battery_probe import compute_track_stats
    if not isinstance(rows, list) or not 1 <= len(rows) <= 512:
        raise ValueError('bounded nonempty battery rows')
    for r in rows:
        if (not isinstance(r, dict) or set(r) != {'correct', 'keep_withdraw'} or
                type(r['correct']) is not bool or r['keep_withdraw'] not in ('KEEP', 'WITHDRAW')):
            raise ValueError('explicit boolean outcome and known decision required')
    return dict(compute_track_stats(deepcopy(rows)), samples=len(rows),
                scope='native walk-admission monitoring/control adaptation; not MMB replication')


def project_trajectory(events):
    """Project local execution events with RoboRSI's actual implementation.

    Reject conflicting duplicate event IDs before the upstream projection's
    idempotent filtering. There are no model usage events in our body pilot;
    model costs remain unknown/None, not a fabricated measured zero cost.
    """
    verify_sources()
    from .vendor.roborsi_trajectory import TrajectoryProjection
    if not isinstance(events, list) or not 1 <= len(events) <= 4096:
        raise ValueError('bounded nonempty trajectory')
    projection, seen, previous, run_id = TrajectoryProjection(), {}, 0, None
    allowed = {'run_start', 'run_end', 'agent_start', 'agent_end', 'turn_start',
               'turn_end', 'body_decision', 'body_result'}
    for event in events:
        if (not isinstance(event, dict) or event.get('type') not in allowed or
                type(event.get('seq')) is not int or event['seq'] < 1 or
                not isinstance(event.get('event_id'), str) or not event['event_id'] or
                not isinstance(event.get('run_id'), str) or not event['run_id'] or
                not isinstance(event.get('payload'), dict)):
            raise ValueError('local trajectory contract')
        fingerprint = digest(event)
        identity = event['event_id']
        if identity in seen:
            if seen[identity] != fingerprint:
                raise ValueError('conflicting duplicate trajectory event')
            continue
        if event['seq'] <= previous or run_id not in (None, event['run_id']):
            raise ValueError('trajectory order/run changed')
        previous, run_id = event['seq'], event['run_id']
        seen[identity] = fingerprint
        projection.apply(deepcopy(event))
    return projection.index()


def geometry(body, frame_yaw_rad=0.):
    """Transform actual native foot positions into an explicitly chosen frame.

    Native COM has X/Y only. The frame origin is its projection on the floor,
    not an invented measured COM height or body orientation.
    """
    verify_sources()
    import torch
    from .vendor import mjlab_math as mj
    from .native_snapshot import snapshot
    if type(frame_yaw_rad) not in (int, float) or not math.isfinite(frame_yaw_rad):
        raise ValueError('finite reference-frame yaw')
    before = body.checkpoint()
    obs = snapshot(body)
    state = body.owner.physical.state
    feet = torch.tensor([state.feet_m[s] for s in ('L', 'R')], dtype=torch.float64)
    origin = torch.tensor([*state.com_m, 0.], dtype=torch.float64)
    yaw = torch.tensor([frame_yaw_rad], dtype=torch.float64)
    quat = mj.quat_from_euler_xyz(torch.zeros_like(yaw), torch.zeros_like(yaw), yaw).expand(2, -1)
    local = mj.quat_apply_inverse(quat, feet-origin)
    recovered = mj.quat_apply(quat, local) + origin
    if (not torch.isfinite(local).all() or not torch.allclose(feet, recovered, atol=1e-12, rtol=0)
            or body.checkpoint() != before):
        raise ValueError('coordinate conversion changed native state or failed roundtrip')
    return dict(source_observation_sha256=obs['observation_sha256'],
                feet_world_m=feet.tolist(), feet_frame_m=local.tolist(),
                origin_world_m=origin.tolist(), frame_yaw_rad=frame_yaw_rad,
                max_roundtrip_error_m=float((feet-recovered).abs().max()),
                native_cycles_executed=0, scope='mjlab/Isaac Lab math subset; no physics engine or locomotion training')


FEATURES = ('energy', 'hydration', 'fatigue', 'pain', 'sleep_pressure', 'balance')


def sensory_sample(body):
    """Read six existing internal variables and six foot coordinates.

    Foot coordinates are simulated geometry features, not camera observations.
    No result labels, future states or writable body references reach PredVLA.
    """
    from .native_snapshot import snapshot
    obs = snapshot(body)
    q = [obs['minimum'][k] for k in FEATURES]
    v = [x for side in ('L', 'R') for x in body.owner.physical.state.feet_m[side]]
    if not all(type(x) in (int, float) and math.isfinite(x) for x in q+v):
        raise ValueError('nonfinite sensory feature')
    return dict(q=q, v=v, source=obs['observation_sha256'])
