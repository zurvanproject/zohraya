"""Independent native support-contract probes; invoke as a script from repo root.

No native_preflight, adaptive learner, or predictor is imported. Runtime sources
are hash-checked and copied to a temporary tree; fixtures never use user state.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'runtimes/tadash_body'
PROTOCOL = Path(__file__).with_name('support_contract_protocol_v04.json')
NATIVE_REL = Path('base_v09/tadash_renal_v09/retained_v08/body_v06')


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def excerpt(frame):
    m = frame['motor']
    out = {k: deepcopy(frame[k]) for k in ('motor', 'ledger', 'state')}
    if 'posture' in frame:
        out.update({k: deepcopy(frame[k]) for k in ('contact', 'posture', 'balance', 'task')})
        # Independent weakest-link arithmetic; also retain every joint ratio.
        normal = frame['contact'].get('required_normal_N', frame['contact']['normal_N'])
        loads = {side: sum(v for k, v in normal.items() if k.startswith(side + '_')) for side in ('L', 'R')}
        ratios = {c: m['postural_force_N'][c] / req
                  for c, req in m['postural_requests_N'].items()
                  if c.startswith(('hip_', 'knee_', 'ankle_')) and req > 1e-9
                  and loads[c[-1]] > 195.0 * 9.81 * .005}
        gain = min(ratios.values(), default=0.0)
        assert abs(gain - frame['contact']['joint_support_fraction']) < 1e-10
        out['independent_support'] = {'requested_load_by_foot_N': loads, 'ratios': ratios, 'gain': gain}
        if frame['balance']['model_valid']:
            assert abs(sum(normal.values()) - 195.0 * 9.81) < 1e-6
            for axis in (0, 1):
                moment = sum(normal[p['id']] * p['xy'][axis] for p in frame['contact']['patches'])
                assert abs(moment - 195.0 * 9.81 * frame['contact']['cop_m'][axis]) < 1e-6
            assert max(frame['contact']['pressure_kpa'].values(), default=0.) <= 300.0 + 1e-7
    out['full_frame_sha256'] = sha(frame)
    return out


def force_oracle(body, before, inputs, frame):
    """Recalculate force ceilings and two energy tiers outside BodyLoop.step.

    Limited to declared energy probes: no wound, heat, perfusion or tendon input.
    Actual raw-hazard and latch outputs are observed separately, not predicted.
    """
    m = frame['motor']
    tiers = {'postural': {}, 'optional': {}}
    for c, sec in body.sections.items():
        cap = min(sec['muscle_force_N'] * (1 - .5 * before['fatigue'][c]) * sec['muscle_moment_arm_m'],
                  sec['tendon_allowable_force_N'] * sec['muscle_moment_arm_m'],
                  sec['bone_allowable_moment_Nm'], sec['joint_allowable_moment_Nm']) / sec['external_load_arm_m']
        assert abs(cap - m['capacity_N'][c]) < 1e-8
        guarded = cap * m['hazard_fraction_cap'][c]
        tiers['postural'][c] = min(inputs.postural_force_requests_N.get(c, 0.), guarded)
        tiers['optional'][c] = min(inputs.force_requests_N.get(c, 0.), max(0., guarded - tiers['postural'][c]))
        if m['critical_stop'] or m['systemic_stop']:
            tiers['postural'][c] = tiers['optional'][c] = 0.
    oxygen_W = body.table['1.0']['flow_L_min'] * .20 * .65 * 20000 / 60
    available = min(oxygen_W, inputs.aerobic_limit_W, before['fuel_J'] / inputs.dt_s)
    vital = min(177. + body.table['1.0']['pump_extra_metabolic_W'], available)
    budget = max(0., available - vital) + min(before['reserve_J'] / inputs.dt_s, 1800.)
    delivered = {}
    fractions = {}
    for tier, candidates in tiers.items():
        power = sum(v * (inputs.speeds_m_s.get(c, .25) / .30 + .06) for c, v in candidates.items())
        fraction = min(1., budget / power) if power else 1.
        fractions[tier] = fraction
        delivered[tier] = {c: v * fraction for c, v in candidates.items()}
        budget -= power * fraction
        for c, v in delivered[tier].items():
            assert abs(v - m[tier + '_force_N'][c]) < 1e-7
        assert abs(fraction - m['priority_fractions'][tier]) < 1e-12
    return {'candidate_force_N': tiers, 'reconstructed_fractions': fractions,
            'max_force_error_N': max(abs(delivered[t][c] - m[t + '_force_N'][c]) for t in tiers for c in body.sections)}


def check_contract(results):
    """Outcome requirements, including explicit failures, fixed before release."""
    rows = {r['case']: r for r in results['posture_cases']}
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append({'name':name, 'passed':True})
    for command in ('stand', 'walk', 'single_R'):
        check('low-pain-support-' + command, all(rows[f'pain-{h}-{command}']['frames'][0]['balance']['model_valid']
                                             for h in (0., .3, .5, .6)))
        check('subthreshold-deficit-' + command, all(not rows[f'pain-{h}-{command}']['frames'][0]['balance']['model_valid']
                                                  for h in (.64, .649)))
        for h in (.65, .651, .8):
            f = rows[f'pain-{h}-{command}']['frames'][0]
            check(f'latched-loaded-leg-{h}-{command}', all(f['state']['latched'][j+'_L'] and
                  f['motor']['postural_force_N'][j+'_L'] == 0. for j in ('hip','knee','ankle')) and
                  f['contact']['joint_support_fraction'] == 0. and not f['balance']['model_valid'])
    for stance in ('L', 'R'):
        opposite = 'R' if stance == 'L' else 'L'
        held = rows[f'reached-single-{stance}-pain-{opposite}']['frames']
        check('healthy-stance-preserved-' + stance, len(held) == 20 and all(f['balance']['model_valid'] for f in held))
        check('painful-leg-lowering-stalled-' + stance, all(f['posture']['swing']['progress'] == 0. and
                  f['posture']['swing']['kind'] == 'lower' for f in held))
        check('pain-in-loaded-stance-fails-' + stance,
              not rows[f'reached-single-{stance}-pain-{stance}']['frames'][0]['balance']['model_valid'])
    for pain in (0., .8):
        removed = rows[f'contact-left_all_off-pain-{pain}']['frames']
        check('contact-removal-not-recovery-' + str(pain), len(removed) == 2 and
              removed[0]['balance']['model_valid'] and not removed[-1]['balance']['model_valid'])
    for r in results['integrated_cases']:
        f = r['frame']; m = f['motor']
        check('integrated-support-failure-' + r['requested'], not r['receipt']['owner']['physical_model_valid'] and
              m['priority_fractions']['postural'] == 1. and f['contact']['joint_support_fraction'] == 0. and
              all(m['postural_force_N'][j+'_R'] > 0. for j in ('hip','knee','ankle')))
    normal = next(r for r in results['energy_cases'] if r['pain'] == 0. and r['aerobic_limit_W'] == 450.)
    check('energy-limits-without-latch', 0. < normal['frame']['motor']['priority_fractions']['postural'] < 1. and
          not any(normal['frame']['state']['latched'].values()))
    stopped = next(r for r in results['energy_cases'] if r['pain'] == 0. and r['aerobic_limit_W'] == 200.)
    check('critical-stop-empty-tier-fraction-not-support', stopped['frame']['motor']['critical_stop'] and
          stopped['frame']['motor']['priority_fractions']['postural'] == 1. and
          sum(stopped['frame']['motor']['postural_force_N'].values()) == 0.)
    check('guard-ablation-is-only-causal-control', rows['unsafe-guard-ablation-causal-control']['frames'][0]['balance']['model_valid'])
    check('healthy-foot-pressure-not-capture-feasibility', results['contact_geometry_control']['right_only_contact']['feasible'] and
          results['contact_geometry_control']['capture_margin_m'] < -.18)
    return checks


def execute(protocol):
    from body_loop_v06 import BodyLoop, Inputs, CHANNELS
    from posture_step import PostureLoop, GaitEnvironment
    from resource_audit_v06 import ConservationAudit
    rows = []
    def step_case(name, loop, envs):
        audit = ConservationAudit(asdict(loop.body.state))
        frames = []
        for env in envs:
            f = loop.step(env)
            audit.frame(f)
            frames.append(excerpt(f))
            if not f['balance']['model_valid']:
                break
        row = {'case': name, 'frames': frames, 'resource_audit': audit.result()}
        rows.append(row)
        return row
    dt = protocol['dt_s']
    for pain in protocol['pain_levels']:
        for command in protocol['commands']:
            step_case(f'pain-{pain}-{command}', PostureLoop(), [GaitEnvironment(command=command,
                body=Inputs(dt_s=dt, stimuli={'forefoot_L': {'mechanical': pain}}))])
    patches = ['ball', 'toe_1', 'toe_2', 'toe_3']
    for case in protocol['contact_cases']:
        inactive = {} if case == 'all' else {'L': ['toe_2'] if case == 'left_toe_2_off' else patches}
        for pain in (0., .8):
            step_case(f'contact-{case}-pain-{pain}', PostureLoop(), [GaitEnvironment(
                inactive_patches=inactive, body=Inputs(dt_s=dt, stimuli={'forefoot_L': {'mechanical': pain}}))
                for _ in range(round(protocol['contact_horizon_s'] / dt))])
    # Each state is first physically reached without pain; no teleport/reset.
    for stance in ('L', 'R'):
        origin = PostureLoop()
        for _ in range(120):
            f = origin.step(GaitEnvironment(command='single_' + stance, body=Inputs(dt_s=dt)))
            assert f['balance']['model_valid']
        assert origin.state.phase == 'single_support'
        checkpoint = origin.checkpoint()
        for pain_side in ('L', 'R'):
            loop = PostureLoop.restore(checkpoint)
            row = step_case(f'reached-single-{stance}-pain-{pain_side}', loop,
                [GaitEnvironment(command='single_' + stance, body=Inputs(dt_s=dt,
                    stimuli={'forefoot_' + pain_side: {'mechanical': .8}}))
                 for _ in range(round(protocol['single_support_horizon_s'] / dt))])
            row['reached_initial_checkpoint_sha256'] = checkpoint['sha256']
            row['initial_posture'] = deepcopy(checkpoint['payload']['posture'])
    # Hold the actual support demand fixed to isolate allocation from geometry.
    reference = PostureLoop().step(GaitEnvironment(body=Inputs(dt_s=dt)))
    demand = reference['motor']['postural_requests_N']
    energy = []
    for pain in protocol['energy_pain_levels']:
        for limit in protocol['energy_limits_W']:
            body = BodyLoop(initial={'reserve_J': 0.})
            before = asdict(body.state)
            i = Inputs(dt_s=dt, postural_force_requests_N=demand,
                       force_requests_N={'elbow': 500.}, speeds_m_s={c: .1 for c in CHANNELS},
                       aerobic_limit_W=limit, stimuli={'forefoot_L': {'mechanical': pain}})
            audit = ConservationAudit(before)
            f = body.step(i); audit.frame(f)
            energy.append({'pain': pain, 'aerobic_limit_W': limit, 'frame': excerpt(f),
                           'oracle': force_oracle(body, before, i, f), 'resource_audit': audit.result()})
    # Latch release is tested separately from failed posture, over actual ticks.
    body = BodyLoop(); history = []
    for hazard, reps in zip(protocol['hysteresis_hazards'], protocol['hysteresis_repetitions']):
        for _ in range(reps):
            f = body.step(Inputs(dt_s=dt, postural_force_requests_N={'knee_L':100.},
                        speeds_m_s={c:0. for c in CHANNELS}, stimuli={'forefoot_L': {'mechanical':hazard}}))
            history.append({'t_s': f['t_s'], 'hazard': hazard, 'latched': f['state']['latched']['knee_L'],
                'clear_s':f['state']['clear_s']['knee_L'], 'ramp': f['state']['return_fraction']['knee_L'],
                'force_N':f['motor']['postural_force_N']['knee_L']})
    assert all(x['latched'] for x in history[:37])
    assert not history[-1]['latched'] and history[-1]['ramp'] == 1.
    # Diagnostic continuation of terminated synthetic equations, not recovery.
    terminated = PostureLoop()
    failed = terminated.step(GaitEnvironment(body=Inputs(dt_s=dt,
                                stimuli={'forefoot_L': {'mechanical': .8}})))
    assert not failed['balance']['model_valid']
    followup_audit = ConservationAudit(asdict(terminated.body.state))
    followup = []
    for _ in range(round(protocol['failed_followup_horizon_s'] / dt)):
        f = terminated.step(GaitEnvironment(body=Inputs(dt_s=dt)))
        followup_audit.frame(f)
        followup.append(excerpt(f))
        assert not f['balance']['model_valid'] and f['posture']['phase'] == 'failed'
    assert not f['state']['latched']['ankle_L'] and f['state']['return_fraction']['ankle_L'] == 1.
    # Contrasting limited ablation is a causal probe only; never a proposed mode.
    from pain_resilience_v04 import ResilientBody
    from breath_motion_v06 import BreathMotionLoop
    ablation = PostureLoop(coupling=BreathMotionLoop(body=ResilientBody(regional_guard=False)))
    step_case('unsafe-guard-ablation-causal-control', ablation, [GaitEnvironment(
        body=Inputs(dt_s=dt, stimuli={'forefoot_L': {'mechanical': .8}}))])
    # Pressure feasibility vs geometry: true right-only support at the centre.
    loop = PostureLoop()
    right = loop.contact.solve(loop.state.feet_m, ['R'], [0.,0.], loop.weight)
    from contacts import point_margin
    contact_control = {'required_weight_N': loop.weight, 'right_only_contact': right,
        'capture_margin_m': point_margin(right['polygon'], [0.,0.]),
        'desired_cop_error_m': math.dist(right['cop_m'], [0.,0.]),
        'meaning': 'pressure-feasible load witness; outside centred capture geometry; no executed transfer'}
    # Native integrated actions reproduce the cited case without preview().
    from synthetic_fixture import prepare_defaults, synthetic_origin
    from unified_body_v2 import PersistentEmbodiment, UnifiedBody
    prepare_defaults()
    owner = PersistentEmbodiment.restore(synthetic_origin())
    before = owner.body()
    owner.aux['sleep_pressure'] = .2; owner.aux['muscle_tone'] = .3
    owner._record(before, owner.body(), 'external_input', 'declared synthetic contract sleep/tone fixture', 0.)
    origin = UnifiedBody.migrate(owner.checkpoint())
    integrated = []
    for action in ('observe', 'walk'):
        body = UnifiedBody.restore(origin.checkpoint())
        body.owner._external({'pain':[{'id':'audit-pain', 'location':'forefoot_L','intensity':.8,
            'quality':'pressure','cause':'declared synthetic contract probe','duration_s':10.}]})
        at = (datetime.fromisoformat(body.owner.wall_utc) + timedelta(seconds=dt)).isoformat()
        receipt = body.cycle(event_id='audit-' + action, at_utc=at, duration_s=dt, requested=action, external={})
        integrated.append({'requested':action, 'receipt':receipt, 'frame':excerpt(body.owner.physical.last)})
    assert not any('native_preflight' in name for name in sys.modules)
    return {'posture_cases':rows, 'energy_cases':energy, 'hysteresis':history,
            'contact_geometry_control':contact_control, 'integrated_cases':integrated,
            'terminated_followup': {'frames':followup, 'resource_audit':followup_audit.result(),
                'scope':'diagnostic steps after declared termination; no simulated fall or recovered posture'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL.read_text())
    manifest = json.loads((RUNTIME / 'PUBLIC_FILES_SHA256.json').read_text())
    for path, expected in manifest.items():
        assert hashlib.sha256((RUNTIME / path).read_bytes()).hexdigest() == expected, path
    (args.output_dir / 'frozen_protocol.json').write_text(PROTOCOL.read_text())
    sources = {path: hashlib.sha256((RUNTIME / path).read_bytes()).hexdigest() for path in manifest}
    with tempfile.TemporaryDirectory(prefix='nasuraya-contract-v04-') as tmp:
        runtime = Path(tmp) / 'tadash_body'
        shutil.copytree(RUNTIME, runtime, ignore=shutil.ignore_patterns('__pycache__'))
        sys.path[:0] = [str(runtime), str(runtime / NATIVE_REL)]
        results = execute(protocol)
    for path, expected in sources.items():
        assert hashlib.sha256((RUNTIME / path).read_bytes()).hexdigest() == expected, path
    posture = results['posture_cases']
    summary = {'posture_scenarios':len(posture), 'posture_frames':sum(len(r['frames']) for r in posture),
        'posture_scenarios_final_valid':sum(r['frames'][-1]['balance']['model_valid'] for r in posture),
        'energy_scenarios':len(results['energy_cases']), 'hysteresis_ticks':len(results['hysteresis']),
        'integrated_scenarios':len(results['integrated_cases']), 'checked_native_files':len(manifest),
        'terminated_followup_ticks':len(results['terminated_followup']['frames']),
        'preflight_calls':0, 'learning_updates':0, 'api_calls':0, 'native_equations_changed':False,
        'biological_validation':False, 'mechanical_recovery_established':False}
    report = {'schema':'nasuraya-native-support-contract-audit/4',
        'executed_at_utc':datetime.now(timezone.utc).isoformat(), 'protocol_sha256':sha(protocol),
        'protocol':protocol, 'source_sha256':sources, 'summary':summary, 'results':results,
        'contract_checks':check_contract(results)}
    (args.output_dir / 'audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
