"""Paired synthetic native-owner route trial, with no changes to the plant.

The spiral is sampled in floor x/y, relative to each original foot. The plant
has no torso yaw. COM is produced by its weight-transfer controller, never
assigned to a waypoint. Native candidate selection remains authoritative.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1] / 'runtimes/tadash_body'
sys.path.insert(0, str(NATIVE))
from synthetic_fixture import prepare_defaults, synthetic_body
from persistent_embodiment_v1 import PersistentEmbodiment
from coordinated_support import CoordinatedSupport
from extension_state import attach, checkpoint, restore
from run_bounded_route import route_targets
from run_balance_checks import PhysicsAudit, GasAudit


def spiral_targets(feet, direction, protocol):
    if direction not in ('forward', 'reverse'):
        raise ValueError('unsupported direction')
    n = protocol['spiral_points']
    if type(n) is not int or not 2 <= n <= 99:
        raise ValueError('spiral point count')
    r0, r1, turns = (protocol[k] for k in ('radius_start_m', 'radius_end_m', 'turns'))
    if not all(math.isfinite(x) for x in (r0, r1, turns)) or not 0 < r0 < r1 <= .05 or not 0 < turns <= 1:
        raise ValueError('bounded spiral geometry')
    offsets = []
    for i in range(n):
        u = i / (n - 1)
        radius = r0 + (r1 - r0) * u
        angle = math.pi / 2 + 2 * math.pi * turns * u
        offsets.append([radius * math.cos(angle), radius * math.sin(angle)])
    if direction == 'reverse':
        offsets.reverse()
    return {s: [[feet[s][0] + x, feet[s][1] + y, 0.] for x, y in offsets]
            + [list(feet[s])] for s in ('L', 'R')}


def validate_reach(feet, plan, limit):
    for side in ('L', 'R'):
        for a, b in zip([feet[side]] + plan[side], plan[side]):
            if math.dist(a, b) > limit:
                raise ValueError('route exceeds native step reach')


def native_hashes():
    return {str(p.relative_to(NATIVE)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(NATIVE.rglob('*')) if p.suffix in ('.py', '.json')}


def run(kind, direction, output, recovery=False):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    p = json.loads((HERE / 'spiral_protocol.json').read_text())
    prepare_defaults()
    source_hashes = native_hashes()
    body = synthetic_body()
    initial_native = body.checkpoint()
    feet = deepcopy(body.owner.physical.state.feet_m)
    plan = spiral_targets(feet, direction, p) if kind == 'spiral' else route_targets(feet, direction)
    validate_reach(feet, plan, body.owner.physical.design['max_step_length_m'])
    attach(body, dict(star_enabled=False, star_started=dict(L=0, R=0),
                      star_targets=plan, cursor_semantics='confirmed'))
    assert body.checkpoint() == initial_native
    (output / 'initial.json').write_text(json.dumps(checkpoint(body)))
    start_time = body.owner.physical.state.time_s
    start_fuel = body.owner.owner.body.state.fuel_J
    clock = datetime.fromisoformat(body.owner.wall_utc)
    rows, touchdowns, frames = [], [], []
    actual = False
    physics, gas = PhysicsAudit(body.owner.physical), GasAudit(body.owner.physical)
    original_simulate, original_step = PersistentEmbodiment._simulate, CoordinatedSupport.step
    stop_reason = None
    pause_done = False
    next_equivalence = False
    wall = time.perf_counter()

    def simulate(owner, *args, **kwargs):
        nonlocal actual
        previous = actual; actual = kwargs.get('actual', False)
        try:
            return original_simulate(owner, *args, **kwargs)
        finally:
            actual = previous

    def step(physical, environment):
        frame = original_step(physical, environment)
        if actual:
            physics.frame(frame, environment); gas.frame(frame)
            touchdowns.extend(deepcopy(e) for e in frame['posture']['events_this_frame']
                              if e['name'] == 'touchdown')
            frames.append(dict(t_s=physical.state.time_s,
                valid=frame['balance']['model_valid'], phase=physical.state.phase,
                com_m=list(physical.state.com_m), feet_m=deepcopy(physical.state.feet_m),
                velocity_m_s=list(physical.state.velocity_m_s),
                capture_margin_m=frame['balance']['capture_margin_m'],
                support=frame['contact']['joint_support_fraction'],
                max_pressure_kpa=max(frame['contact']['pressure_kpa'].values(), default=0.),
                friction_capacity_N=frame['contact']['friction_capacity_N'],
                horizontal_force_N=math.hypot(*frame['contact']['horizontal_force_N']),
                motor_J=frame['ledger']['motor_energy_J']))
        return frame

    def advance(phase, action, equivalence=False):
        nonlocal clock, body, actual
        kw = dict(event_id=f'{kind}-{direction}-{len(rows):03d}', at_utc=clock.isoformat(),
            duration_s=1., requested=action, expected_revision=body.revision,
            external=dict(native=dict(upper_targets=dict(shoulder_L=.35, shoulder_R=.35,
                elbow_L=1.2, elbow_R=1.2, head_pitch=-.1, head_yaw=0.)) if phase != 'closure' else
                dict(upper_targets=dict(shoulder_L=0., shoulder_R=0., elbow_L=0., elbow_R=0., head_pitch=0., head_yaw=0.))))
        twin = restore(json.loads(json.dumps(checkpoint(body)))) if equivalence else None
        r = body.cycle(**kw)
        if twin is not None:
            # Keep the counterfactual restore replay out of actual audit totals.
            PersistentEmbodiment._simulate = original_simulate
            try:
                rr = twin.cycle(**deepcopy(kw))
            finally:
                PersistentEmbodiment._simulate = simulate
            assert rr == r and checkpoint(twin) == checkpoint(body)
        ph = body.owner.physical
        row = dict(index=len(rows), phase=phase, selected=r['owner']['selected_action'],
            valid=r['owner']['physical_model_valid'], cursor=deepcopy(ph.star_started),
            fuel_J=sum(f['fuel_used_J'] for f in r['trace']),
            prediction_error=r['owner']['prediction']['mean_scaled_absolute_error'],
            prediction_signed_errors=r['owner']['prediction']['signed_errors'],
            balance=body.owner.body()['minimum_state']['balance'],
            audit=r['whole_body_audit'], owner_ticks=r['owner_ticks'])
        assert row['owner_ticks'] == 10
        assert row['audit']['energy_error_J'] < 5e-5 and row['audit']['water_error_L'] < 1e-8
        rows.append(row); clock += timedelta(seconds=1)
        if len(rows) % 20 == 0:
            print(json.dumps(dict(case=output.name, seconds=len(rows), cursor=ph.star_started, valid=row['valid'])), flush=True)
        return row

    PersistentEmbodiment._simulate, CoordinatedSupport.step = simulate, step
    try:
        for _ in range(p['prelude_s']):
            if not advance('prelude', 'slow_breath')['valid']:
                stop_reason = 'prelude invalid'; break
        movement = veto = 0
        if stop_reason is None:
            body.owner.physical.star_enabled = True
            while movement < p['movement_max_s']:
                if all(body.owner.physical.star_started[s] == len(plan[s]) for s in ('L', 'R')):
                    break
                if recovery and not pause_done and movement == p['pause_at_movement_s']:
                    body.owner.physical.star_enabled = False
                    (output / 'pre_stop.json').write_text(json.dumps(checkpoint(body)))
                    settled = False
                    for _ in range(p['pause_max_s']):
                        row = advance('pause', 'slow_breath')
                        if not row['valid']:
                            stop_reason = 'pause invalid'; break
                        q = body.owner.physical
                        if q.state.phase == 'double_support' and q.state.swing is None and math.hypot(*q.state.velocity_m_s) <= p['speed_max_m_s']:
                            settled = True; break
                    if stop_reason is not None or not settled:
                        stop_reason = stop_reason or 'pause did not settle within budget'; break
                    saved = checkpoint(body)
                    (output / 'stopped.json').write_text(json.dumps(saved))
                    body = restore(json.loads((output / 'stopped.json').read_text()))
                    assert checkpoint(body) == saved
                    body.owner.physical.star_enabled = True
                    pause_done = next_equivalence = True
                row = advance('route', 'walk', next_equivalence)
                next_equivalence = False; movement += 1
                if not row['valid']:
                    stop_reason = 'route invalid'; break
                veto = veto + 1 if row['selected'] != 'walk' else 0
                if veto >= 3:
                    stop_reason = 'three consecutive native vetoes'; break
            if movement == p['movement_max_s'] and not all(body.owner.physical.star_started[s] == len(plan[s]) for s in ('L', 'R')):
                stop_reason = 'movement budget exhausted'
        body.owner.physical.star_enabled = False
        for _ in range(p['closure_s']):
            if body.owner.physical.state.phase == 'failed': break
            if not advance('closure', 'slow_breath')['valid']:
                stop_reason = stop_reason or 'closure invalid'; break
        ph = body.owner.physical
        final = checkpoint(body)
        assert checkpoint(restore(json.loads(json.dumps(final)))) == final
        confirmed = [e for e in touchdowns if e.get('kind') == 'walk']
        for side in ('L', 'R'):
            got = [e['position_m'] for e in confirmed if e['side'] == side]
            assert got == plan[side][:len(got)], 'touchdown order mismatch'
            assert ph.star_started[side] == len(got)
        fuel = sum(r['fuel_J'] for r in rows)
        assert abs(start_fuel - body.owner.owner.body.state.fuel_J - fuel) < 5e-5
        assert abs(ph.state.time_s - start_time - len(rows)) < 1e-7
        assert native_hashes() == source_hashes, 'native source changed'
        complete = all(ph.star_started[s] == len(plan[s]) for s in ('L', 'R'))
        home_error = max(math.dist(ph.state.feet_m[s], feet[s]) for s in ('L', 'R'))
        valid = all(f['valid'] for f in frames)
        support = min(f['support'] for f in frames)
        accepted = (complete and valid and stop_reason is None and home_error <= p['foot_error_max_m']
            and ph.state.phase == 'double_support' and ph.state.swing is None
            and math.hypot(*ph.state.velocity_m_s) <= p['speed_max_m_s']
            and support >= p['support_min'] and (not recovery or pause_done))
        result = dict(schema='nasuraya-spiral-evaluation/1', kind=kind, direction=direction,
            recovery=recovery, accepted=accepted, complete=complete, stop_reason=stop_reason,
            initial_native_sha256=initial_native['sha256'], plan=plan,
            requested_landings=sum(map(len, plan.values())), confirmed_landings=len(confirmed),
            valid=valid, seconds=len(rows), movement_seconds=movement,
            fuel_J=fuel, fuel_per_landing_J=fuel / len(confirmed) if confirmed else None,
            motor_J=sum(f['motor_J'] for f in frames),
            final_home_error_m=home_error, final_phase=ph.state.phase,
            final_balance=rows[-1]['balance'], minimum_balance=min(r['balance'] for r in rows),
            minimum_support=support, minimum_capture_margin_m=min(f['capture_margin_m'] for f in frames),
            maximum_pressure_kpa=max(f['max_pressure_kpa'] for f in frames),
            final_speed_m_s=math.hypot(*ph.state.velocity_m_s),
            final_com_m=ph.state.com_m, final_feet_m=ph.state.feet_m,
            prediction_error_mean=sum(r['prediction_error'] for r in rows) / len(rows),
            prediction_error_max=max(r['prediction_error'] for r in rows),
            recovery_executed=pause_done, recovery_next_cycle_exact=pause_done,
            cold_restore_exact=True, physics_audit=physics.result(), gas_audit=gas.result(),
            gravity_m_s2=ph.design['gravity_m_s2'], mass_kg=ph.design['mass_kg'],
            native_source_sha256=source_hashes,
            experiment_source_sha256={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in
                ('evaluate_spiral.py','spiral_protocol.json','coordinated_support.py','extension_state.py','run_bounded_route.py')},
            native_limits_changed=False, stock_resets=0, model_api_calls=0,
            official_state_advanced=False, wall_seconds=time.perf_counter()-wall,
            prediction_scope='same-model agreement, not empirical accuracy',
            rows=rows, touchdowns=touchdowns, frames=frames)
        (output / 'checkpoint.json').write_text(json.dumps(final))
        (output / 'result.json').write_text(json.dumps(result, indent=2))
        print('FINAL', json.dumps({k:v for k,v in result.items() if k not in
            ('rows','frames','touchdowns','native_source_sha256','experiment_source_sha256','plan')}), flush=True)
        return result
    finally:
        PersistentEmbodiment._simulate, CoordinatedSupport.step = original_simulate, original_step


if __name__ == '__main__':
    a = argparse.ArgumentParser()
    a.add_argument('--kind', choices=('star','spiral'), required=True)
    a.add_argument('--direction', choices=('forward','reverse'), required=True)
    a.add_argument('--recovery', action='store_true')
    a.add_argument('--output', required=True)
    args = a.parse_args()
    run(args.kind,args.direction,args.output,args.recovery)
