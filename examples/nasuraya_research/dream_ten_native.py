"""Actual ten-request native-body rollouts for Dream Ten (standard library).

The endpoint reference is fixed before trials: the initial next swinging foot's
first native .12 m stride target. Error is remaining 3D endpoint distance, NOT
cross-track error or evidence of completing a star route. Every row is one
actual UnifiedBody.cycle(.1); forecast clones never supply measurements.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import gzip
import platform
import json
import math
from pathlib import Path

# Imports install the retained native runtime's module search path.
from examples.nasuraya_self_model.evaluate import fixture, request
from examples.nasuraya_star_motion.coordinated_support import CoordinatedSupport
from .dream_ten import Step, dream
from posture_step import GaitEnvironment
from synthetic_fixture import prepare_defaults
from unified_body_v2 import UnifiedBody

SCALES = (.25, .5, .75, 1.)
PROTOCOL = dict(schema='dream-ten-native/1', requests=10, duration_s=.1,
    training=[dict(id='train-a', pressure=.10, prelude_s=.1, friction=.60),
              dict(id='train-b', pressure=.30, prelude_s=.2, friction=.50)],
    held_out=[dict(id='test-a', pressure=.20, prelude_s=.3, friction=.55),
              dict(id='test-b', pressure=.40, prelude_s=.4, friction=.65)],
    scales=list(SCALES), error_metric='initial next-foot native stride endpoint distance, 3D metres',
    energy_metric='fuel_used_J + reserve_used_J; whole body metabolism included',
    candidate_selection='train error, then energy, then larger scale; held-out never retunes',
    gates='20% error reduction; <=5% extra energy; all valid; no support/balance/movement regression')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class FixedCautionSupport(CoordinatedSupport):
    """Only change preferred CMP acceleration; inherit every emergency gate."""
    def _integrate_once(self, environment, scale=None):
        if scale is None and self.policy_scale != 1.:
            scale = self.policy_scale
        return super()._integrate_once(environment, scale)


def attach_policy(body, scale):
    if scale not in SCALES:
        raise ValueError('bounded policy scale required')
    before = body.checkpoint()
    body.owner.physical.__class__ = FixedCautionSupport
    body.owner.physical.policy_scale = scale
    if body.checkpoint() != before:
        raise RuntimeError('policy attachment changed native stocks/pose')


def stride_reference(body):
    p = body.owner.physical
    side = p.state.next_swing
    stance = 'L' if side == 'R' else 'R'
    target = [p.state.feet_m[side][0],
              p.state.feet_m[stance][1] + GaitEnvironment().step_length_m, 0.]
    return dict(side=side, target_m=target,
                definition='native _prepare first walk target, frozen before policy trials')


def measure_step(body, receipt, reference, balance_before, feet_before):
    """Read one committed .1 s tick; missing fields/frames fail, never impute."""
    frame = body.owner.physical.last
    trace = receipt['trace']
    if receipt['owner_ticks'] != 1 or len(trace) != 1 or receipt['owner']['simulated_seconds'] != .1:
        raise ValueError('one actual native .1-second tick required')
    p = body.owner.physical
    if not math.isclose(frame['posture']['time_s'], trace[0]['time_s'], abs_tol=1e-9):
        raise ValueError('physical frame and actual receipt clocks differ')
    fuel, reserve = trace[0]['fuel_used_J'], trace[0]['reserve_used_J']
    for key, value in [('fuel_used_J', fuel), ('reserve_used_J', reserve)]:
        if not math.isclose(frame['ledger'][key], value, abs_tol=1e-8):
            raise ValueError('actual frame/receipt energy mismatch')
    support = frame['contact']['joint_support_fraction']
    # Only floating point excess <=1e-9 is normalized; retain the raw value.
    if not math.isfinite(support) or not 0 <= support <= 1+1e-9:
        raise ValueError('native support outside unit contract')
    valid = (receipt['owner']['physical_model_valid'] and frame['balance']['model_valid']
             and frame['contact']['feasible'] and support >= .999
             and not frame['contact']['friction_saturated'])
    position = list(p.state.feet_m[reference['side']])
    step = Step(min(1., support), math.dist(position, reference['target_m']), fuel+reserve, bool(valid))
    displacement = max(math.dist(p.state.feet_m[s], feet_before[s]) for s in ('L', 'R'))
    events = frame['posture']['events_this_frame']
    return dict(step=asdict(step), selected_action=receipt['owner']['selected_action'],
        balance_before=balance_before, balance_after=body.owner.body()['minimum_state']['balance'],
        capture_margin_m=frame['balance']['capture_margin_m'], raw_support_fraction=support,
        contact_feasible=frame['contact']['feasible'], friction_saturated=frame['contact']['friction_saturated'],
        fuel_used_J=fuel, reserve_used_J=reserve, mechanical_work_J=trace[0]['mechanical_work_J'],
        endpoint_position_m=position, feet_m=deepcopy(p.state.feet_m), com_m=list(p.state.com_m),
        foot_displacement_m=displacement, phase=p.state.phase, failure_reason=p.state.failed_reason,
        walk_touchdowns=sum(e['name']=='touchdown' and e.get('kind')=='walk' for e in events),
        owner_ticks=receipt['owner_ticks'], time_s=trace[0]['time_s'],
        native_checkpoint_sha256=body.checkpoint()['sha256'], receipt_sha256=digest(receipt),
        whole_body_audit=receipt['whole_body_audit'],
        native_accounting=receipt['owner']['resource_and_gas_audit']['independent_accounting_audits'])


def rollout(source, scale, reference, *, friction=.6, label='trial', requests=10):
    if type(requests) is not int or not 1 <= requests <= 10:
        raise ValueError('bounded 1..10 requests required')
    original = digest(source)
    body = UnifiedBody.restore(deepcopy(source))
    attach_policy(body, scale)
    rows = []
    for index in range(requests):
        before = body.owner.body()['minimum_state']['balance']
        feet = deepcopy(body.owner.physical.state.feet_m)
        req = request(body, f'{label}:{index}', .1)
        req['external']['native'] = dict(friction=dict(L=friction, R=friction))
        receipt = body.cycle(**req)
        rows.append(measure_step(body, receipt, reference, before, feet))
        # Preserve invalid frame and stop; unequal horizons fail the experiment.
        if not rows[-1]['step']['valid']:
            break
    if digest(source) != original:
        raise RuntimeError('source checkpoint modified')
    return dict(scale=scale, initial_native_sha256=source['sha256'], reference=reference,
                friction=friction, rows=rows, complete=len(rows)==requests,
                source_unchanged=True, simulated_seconds=.1*len(rows))


def metrics(trials):
    rows = [r for t in trials for r in t['rows']]
    return dict(requests=len(rows), mean_endpoint_error_m=sum(r['step']['route_error_m'] for r in rows)/len(rows),
        consumed_energy_J=sum(r['step']['fuel_j'] for r in rows),
        fuel_used_J=sum(r['fuel_used_J'] for r in rows), reserve_used_J=sum(r['reserve_used_J'] for r in rows),
        mean_balance=sum(r['balance_after'] for r in rows)/len(rows),
        minimum_capture_margin_m=min(r['capture_margin_m'] for r in rows),
        minimum_support_fraction=min(r['raw_support_fraction'] for r in rows),
        valid_frames=sum(r['step']['valid'] for r in rows),
        valid_walk_requests=sum(r['step']['valid'] and r['selected_action']=='walk' for r in rows),
        valid_foot_motion_ticks=sum(r['step']['valid'] and r['foot_displacement_m']>1e-12 for r in rows),
        confirmed_walk_touchdowns=sum(r['walk_touchdowns'] for r in rows))


def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = list((root/'runtimes/tadash_body').rglob('*.py'))
    paths += [Path(__file__), Path(__file__).with_name('dream_ten.py'),
              root/'examples/nasuraya_star_motion/coordinated_support.py',
              root/'examples/nasuraya_self_model/evaluate.py', root/'examples/nasuraya_self_model/monitor.py']
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def run(output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (out/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    save('protocol.json', PROTOCOL)  # Freeze before any trial outcomes.
    sources = source_hashes()
    save('source-sha256.json', sources)
    prepare_defaults()
    datasets = {}
    for split, specs in [('train', PROTOCOL['training']), ('test', PROTOCOL['held_out'])]:
        datasets[split] = []
        for spec in specs:
            body = fixture(spec['pressure'])
            req = request(body, 'prelude:'+spec['id'], spec['prelude_s'])
            req['requested'] = 'observe'
            body.cycle(**req)
            native = body.checkpoint()
            datasets[split].append(dict(spec=spec, source=native, reference=stride_reference(body)))
    hashes = {s: [d['source']['sha256'] for d in datasets[s]] for s in datasets}
    if set(hashes['train']) & set(hashes['test']):
        raise ValueError('train/test initial states overlap')
    (out/'initial-states.json.gz').write_bytes(gzip.compress(
        json.dumps(datasets, sort_keys=True, allow_nan=False).encode(), mtime=0))
    cache = {}
    call_order = []
    def execute(scale, split):
        key = (split, scale)
        call_order.append(dict(split=split, scale=scale, cached=key in cache))
        if key not in cache:
            trials = [rollout(d['source'], scale, d['reference'], friction=d['spec']['friction'],
                              label=d['spec']['id']) for d in datasets[split]]
            cache[key] = trials
            # Save even stopped/negative runs before selection can reject them.
            save(f'{split}-{scale:g}.json', trials)
            print(json.dumps(dict(split=split, scale=scale, **metrics(trials))), flush=True)
        return [Step(**r['step']) for t in cache[key] for r in t['rows']]
    training = execute(1., 'train')
    result = dream(training, execute, execute)
    if 'learned_scale' in result:
        base, learned = [metrics(cache[('test', s)]) for s in (1., result['learned_scale'])]
        gates = dict(balance_not_worse=learned['mean_balance'] >= base['mean_balance']-1e-9,
            capture_margin_not_worse=learned['minimum_capture_margin_m'] >= base['minimum_capture_margin_m']-1e-9,
            valid_walk_count_not_worse=learned['valid_walk_requests'] >= base['valid_walk_requests'],
            foot_motion_count_not_worse=learned['valid_foot_motion_ticks'] >= base['valid_foot_motion_ticks'],
            touchdown_count_not_worse=learned['confirmed_walk_touchdowns'] >= base['confirmed_walk_touchdowns'],
            actual_foot_motion_observed=learned['valid_foot_motion_ticks'] > 0)
        result['accepted'] = result['accepted'] and all(gates.values())
        result.update(movement_gates=gates, held_out_baseline=base, held_out_selected=learned,
                      held_out_delta={k: learned[k]-base[k] for k in base})
        if not result['accepted']:
            result['reason'] = 'improvement not confirmed; retain negative result; no activation'
    result.update(python_version=platform.python_version(), schema=PROTOCOL['schema'], protocol_sha256=digest(PROTOCOL), initial_hashes=hashes,
        train_test_initial_states_disjoint=True, call_order=call_order,
        held_out_used_for_selection=False, canonical_state_modified=False,
        source_code_unchanged=source_hashes()==sources, consciousness_measured=False,
        limitation='one-second first-stride endpoint task; not completed gait/route or physical-world validation')
    save('result.json', result)
    if not result['source_code_unchanged']:
        raise RuntimeError('source code changed during trial')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
