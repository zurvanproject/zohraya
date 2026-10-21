"""Frozen conditional foot-contact experiment on isolated fixture copies."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .chromosomes import digest
from .foot_contact import compile_foot, validate_plan, write_svg
from .physics_trial import RELATIVE_CONTACT, sample
from .traits import BODY, ROOT, baseline, body_sources, mutate
from examples.nasuraya_body_loop.__main__ import verified_sources

CASES = [
    dict(id='stand', command='stand', frames=20, impulse=[0., 0.], friction=.6),
    dict(id='walk', command='walk', frames=60, impulse=[0., 0.], friction=.6),
    dict(id='impulse', command='stand', frames=40, impulse=[8., 4.], friction=.6),
    dict(id='zero_friction', command='stand', frames=10, impulse=[8., 4.], friction=0.),
]
SCHEMA = 'nasuraya.foot-contact-trial/0.1'


def worker(request):
    plan = request['plan']
    validate_plan(plan)
    source = Path(request['source'])
    if json.loads((source / RELATIVE_CONTACT).read_text()) != plan['design']:
        raise ValueError('copied fixture differs from frozen contact hypothesis')
    sys.path.insert(0, str(source))
    import unified_body_v2
    from posture_step import GaitEnvironment, Inputs, PostureLoop
    from contacts import ContactModel
    design = plan['design']
    feet = dict(L=[design['foot_half_spacing_m'], 0., 0.], R=[-design['foot_half_spacing_m'], 0., 0.])
    _, native = body_sources()
    weight = design['mass_kg'] * design['gravity_m_s2']
    native_capacity = sum(p['area_m2'] for p in native['patches']) * native['pressure_ceiling_kpa'] * 1000
    static = []
    for name, normal, y in (('nominal_single_support', weight, 0.),
                            ('forward_edge_request', weight, .09),
                            ('over_capacity_negative_control', native_capacity*1.1, 0.)):
        target = [feet['L'][0], y]
        r = ContactModel(design).solve(feet, ['L'], target, normal)
        error, moment_error = None, None
        if r['feasible']:
            error = abs(sum(r['normal_N'].values()) - normal)
            moment_error = max(abs(sum(p['xy'][k]*r['normal_N'][p['id']] for p in r['patches'])
                                   - normal*r['cop_m'][k]) for k in (0, 1))
        static.append(dict(case=name, feasible=r['feasible'], requested_normal_N=normal,
                           requested_cop_m=target, achieved_cop_m=r['cop_m'],
                           target_error_m=math.dist(target, r['cop_m']) if r['feasible'] else None,
                           achieved_normal_N=r['total_normal_N'], force_error_N=error,
                           moment_error_Nm=moment_error, pressures_kpa=r['pressure_kpa'],
                           area_each_foot_cm2=sum(p['area_m2'] for p in design['patches'])*1e4))
    dynamic = []
    for case in CASES:
        loop = PostureLoop()
        restored, replay, equal, rows = None, 0, True, []
        for i in range(case['frames']):
            if i == case['frames'] // 2:
                restored = PostureLoop.restore(json.loads(json.dumps(loop.checkpoint())))
            env = GaitEnvironment(command=case['command'], body=Inputs(dt_s=.1),
                                  friction=dict(L=case['friction'], R=case['friction']),
                                  external_impulse_N_s=case['impulse'] if i == 0 else [0., 0.])
            frame = loop.step(env)
            if restored is not None:
                other = restored.step(env)
                equal = equal and frame == other
                replay += 1
            rows.append(sample(frame))
            if not rows[-1]['valid']:
                break
        dynamic.append(dict(case=case['id'], frames=len(rows), replay_frames=replay,
                            valid_throughout=all(r['valid'] for r in rows), failure=rows[-1]['failure'],
                            final_phase=rows[-1]['phase'], walk_touchdowns=rows[-1]['walk_steps'],
                            peak_pressure_kpa=max(v for r in rows for v in r['pressure_kpa'].values()),
                            minimum_capture_margin_m=min(r['capture_margin_m'] for r in rows),
                            fuel_used_J=sum(r['fuel_used_J'] for r in rows),
                            minimum_support_fraction=min(r['support_fraction'] for r in rows),
                            cold_restore_exercised=restored is not None, cold_restore_equal=equal,
                            physical_trace_sha256=digest(rows)))
    return dict(static=static, dynamic=dynamic)


def run_copy(plan, manifest):
    validate_plan(plan)
    with tempfile.TemporaryDirectory(prefix='nasuraya-foot-hypothesis-') as directory:
        source = Path(directory)
        for name in manifest:
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BODY / name, dest)
        (source / RELATIVE_CONTACT).write_text(json.dumps(plan['design'], indent=2) + '\n')
        for name, expected in manifest.items():
            if name != str(RELATIVE_CONTACT) and hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError('copied source mutation')
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        env['PYTHONPATH'] = str(ROOT)
        process = subprocess.run([sys.executable, '-m', 'examples.nasuraya_genome.foot_trial', '--worker'],
                                 input=json.dumps(dict(plan=plan, source=str(source))), text=True,
                                 capture_output=True, cwd=directory, env=env, timeout=40, check=True)
        result = json.loads(process.stdout)
        for name, expected in manifest.items():
            if name != str(RELATIVE_CONTACT) and hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError('worker mutated a retained source')
        result['original_equations_retained_in_copy'] = True
        return result


def scaled_genotype():
    return mutate(baseline(), [dict(chromosome='P07' + h, locus=lid, value=1.02)
                               for h in 'AB' for lid in ('P07.L010', 'P07.L011')], expected_revision=0)


def evaluate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = verified_sources()
    g = scaled_genotype()
    plans = dict(baseline=compile_foot(baseline()), affine=compile_foot(g),
                 area_only=compile_foot(g, 'area_only'), centres_only=compile_foot(g, 'centres_only'),
                 descriptor_only=compile_foot(g, 'descriptor_only'))
    frozen = dict(schema=SCHEMA, cases=CASES, dt_s=.1,
                  plans={name: {k: v for k, v in plan.items() if k != 'mesh'} for name, plan in plans.items()},
                  source_manifest_sha256=digest(manifest),
                  experiment_sources_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                              for name in ('foot_contact.py', 'foot_trial.py', 'physics_trial.py', 'traits.py')},
                  assumptions=['authored nonoverlapping ellipse pad shapes matching old patch areas',
                               'affine scaling about a fixed foot anchor; areas use exact determinant',
                               'native support polygon still uses patch centres, not mesh edges',
                               'mass, leg skeleton, forces, pressure ceiling and friction law fixed'],
                  criteria=dict(area_error_relative_max=.000101, centroid_error_m=1e-12,
                                force_error_N=1e-7, moment_error_Nm=1e-7,
                                negative_friction_failure='friction_limit_exceeded',
                                over_capacity_expected_feasible=False),
                  native_apply_allowed=False,
                  claim='conditional geometric/solver consistency; no anatomical or clinical validation')
    (output / 'frozen-plan.json').write_text(json.dumps(frozen, indent=2) + '\n')
    for name in ('baseline', 'affine'):
        (output / (name + '-mesh.json')).write_text(json.dumps(plans[name]['mesh'], separators=(',', ':')) + '\n')
    write_svg(plans['baseline'], plans['affine'], output / 'contact-comparison.svg')
    results = {name: run_copy(plan, manifest) for name, plan in plans.items()}
    def dynamic(name, case):
        return next(c for c in results[name]['dynamic'] if c['case'] == case)
    static_rows = [s for r in results.values() for s in r['static']]
    dynamic_rows = [d for r in results.values() for d in r['dynamic']]
    checks = dict(
        all_mesh_checks_passed=all(p['geometry']['geometric_checks_passed'] for p in plans.values()),
        all_equations_unchanged=all(r['original_equations_retained_in_copy'] for r in results.values()),
        forces_and_moments_balanced=all(s['force_error_N'] < 1e-7 and s['moment_error_Nm'] < 1e-7
                                      for s in static_rows if s['feasible']),
        descriptor_only_matches_baseline=all(dynamic('baseline', case['id'])['physical_trace_sha256'] ==
                                             dynamic('descriptor_only', case['id'])['physical_trace_sha256']
                                             for case in CASES),
        friction_failure_preserved=all(dynamic(name, 'zero_friction')['failure'] == 'friction_limit_exceeded'
                                      for name in results),
        over_capacity_failure_preserved=all(not s['feasible'] for s in static_rows
                                            if s['case'] == 'over_capacity_negative_control'),
        pressure_ceiling_respected=all(v <= plans['baseline']['design']['pressure_ceiling_kpa'] + 1e-8
                                       for s in static_rows for v in s['pressures_kpa'].values()) and
                                    all(d['peak_pressure_kpa'] <= 300 + 1e-8 for d in dynamic_rows),
        all_exercised_cold_restores_equal=all(d['cold_restore_equal'] for d in dynamic_rows),
        source_manifest_unchanged=verified_sources() == manifest,
    )
    if not all(checks.values()):
        raise AssertionError(checks)
    result = dict(schema=SCHEMA, frozen_plan_sha256=digest(frozen), checks=checks, results=results,
                  dynamic_run_count=len(dynamic_rows), static_query_count=len(static_rows),
                  primary_simulated_s=.1*sum(d['frames'] for d in dynamic_rows),
                  cold_replay_simulated_s=.1*sum(d['replay_frames'] for d in dynamic_rows),
                  candidate_reduced_model_passed=all(d['valid_throughout'] for d in results['affine']['dynamic']
                                                   if d['case'] != 'zero_friction'),
                  native_apply_allowed=False, true_anatomical_contact_validated=False,
                  source_live_state_loaded=False, API_calls=0,
                  interpretation='larger affine pads are a declared hypothesis, not inferred from appearance alone')
    (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.load(sys.stdin))))
    elif args.output:
        result = evaluate(args.output)
        print(json.dumps({k: result[k] for k in ('checks', 'dynamic_run_count', 'static_query_count',
                                                'primary_simulated_s', 'cold_replay_simulated_s',
                                                'candidate_reduced_model_passed')}))
    else:
        parser.error('--output required')
