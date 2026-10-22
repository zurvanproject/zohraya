"""Isolated parameter-sensitivity trials, not live genome/body integration.

The original PostureLoop rejects alternate fixtures. Each trial instead runs
unchanged Python equations against its own copied, explicitly labelled fixture.
Only tail length and its uniform-rod inertia proxy may differ from the source.
"""
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
from .traits import BODY, CONTACT, ROOT, baseline, body_sources, express, mutate
from examples.nasuraya_body_loop.__main__ import verified_sources

SCHEMA = 'nasuraya.genome.physics-trial/0.1'
RELATIVE_CONTACT = CONTACT.relative_to(BODY)
CASES = [
    dict(id='stand', frames=20, command='stand', impulse=[0., 0.], tail=True, friction=.6),
    dict(id='tail_displacement', frames=40, command='stand', impulse=[0., 0.],
         tail=True, friction=.6, tail_angle=[.1, -.05], tail_speed=[.2, -.1]),
    dict(id='impulse', frames=40, command='stand', impulse=[8., 4.], tail=True, friction=.6),
    dict(id='impulse_tail_off', frames=40, command='stand', impulse=[8., 4.], tail=False, friction=.6),
    dict(id='zero_friction', frames=10, command='stand', impulse=[8., 4.], tail=True, friction=0.),
    dict(id='walk', frames=60, command='walk', impulse=[0., 0.], tail=True, friction=.6),
]
ASSUMPTIONS = [
    'equivalent uniform slender rod about its root: I = m L^2 / 3',
    'tail mass fixed at 10 kg; effective actuator lever and force/torque ceilings fixed',
    'whole-body mass, COM, contact patches, leg links and controller gains fixed',
    'no anatomical mass redistribution, mesh collision or tail-ground contact solved',
    'parameters vary only in private fixture copies; no original equation is changed',
]


def compile_candidate(genotype):
    phenotype = express(genotype)
    _, native = body_sources()
    structural = phenotype['structural_proposal']
    baseline_shape = phenotype['native_baseline']
    reasons = []
    if any(structural[k] != baseline_shape[k] for k in ('foot_length_cm', 'foot_width_cm')):
        reasons.append('foot_dimensions_have_no_validated_mesh_to_contact_mapping')
    if phenotype['compatibility']['copy_deviation']:
        reasons.append('dosage_audit_cannot_authorize_a_physical_parameter_change')
    result = dict(schema=SCHEMA, genotype_sha256=digest(genotype),
                  policy_sha256=phenotype['policy_sha256'], reasons=reasons,
                  purpose='genotype_candidate_with_declared_inertia_closure',
                  status='blocked' if reasons else 'sandbox_only',
                  native_apply_allowed=False, assumptions=ASSUMPTIONS,
                  native_design_sha256=digest(native))
    if reasons:
        return result
    length = structural['tail_length_cm'] / 100.
    mass = native['tail_mass_kg']
    if not math.isclose(native['tail_inertia_kg_m2'], mass * native['tail_length_m']**2 / 3,
                        rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError('baseline does not satisfy the declared rod closure')
    design = deepcopy(native)
    design.update(tail_length_m=length, tail_inertia_kg_m2=mass * length**2 / 3.)
    changes = {key: dict(before=native[key], after=value) for key, value in design.items()
               if value != native[key]}
    if set(changes) - {'tail_length_m', 'tail_inertia_kg_m2'}:
        raise ValueError('sandbox change escaped the allowlist')
    result.update(design=design, changes=changes, sandbox_design_sha256=digest(design))
    return result


def sample(frame):
    p = frame['posture']
    return dict(valid=frame['balance']['model_valid'], phase=p['phase'], failure=p['failed_reason'],
                com=p['com_m'], velocity=p['velocity_m_s'], feet=p['feet_m'],
                tail_angle=p['tail_angle_rad'], tail_speed=p['tail_velocity_rad_s'],
                tail_torque=p['tail_torque_actual_Nm'], tail_energy_J=p['tail_kinetic_energy_J'],
                capture_margin_m=frame['balance']['capture_margin_m'],
                pressure_kpa=frame['contact']['pressure_kpa'],
                support_fraction=frame['contact']['joint_support_fraction'],
                fuel_used_J=frame['ledger']['fuel_used_J'], walk_steps=p['walk_steps'])


def worker(request):
    """Called only in a subprocess with an independent copied native import tree."""
    source = Path(request['source'])
    plan = request['plan']
    validate_plan(plan)
    fixture = json.loads((source / RELATIVE_CONTACT).read_text())
    if fixture != plan['design'] or digest(fixture) != plan['sandbox_design_sha256']:
        raise ValueError('worker fixture does not match its frozen plan')
    sys.path.insert(0, str(source))
    import unified_body_v2  # Retained native import-path bootstrap.
    from posture_step import GaitEnvironment, Inputs, PostureLoop
    cold_rejection = None
    if 'foreign_checkpoint' in request:
        try:
            PostureLoop.restore(request['foreign_checkpoint'])
        except ValueError:
            cold_rejection = True
        else:
            cold_rejection = False
    rows = []
    reference_checkpoint = None
    for case in CASES:
        initial = dict(tail_angle_rad=case.get('tail_angle', [0., 0.]),
                       tail_velocity_rad_s=case.get('tail_speed', [0., 0.]))
        loop = PostureLoop(initial_posture=initial)
        samples, restored, cold_equal, max_error, replay_frames = [], None, True, 0., 0
        for i in range(case['frames']):
            # Resume under this copied fixture, never under the production fixture.
            if i == case['frames'] // 2:
                restored = PostureLoop.restore(json.loads(json.dumps(loop.checkpoint())))
            before_angle = list(loop.state.tail_angle_rad)
            before_speed = list(loop.state.tail_velocity_rad_s)
            env = GaitEnvironment(command=case['command'], body=Inputs(dt_s=.1),
                                  external_impulse_N_s=case['impulse'] if i == 0 else [0., 0.],
                                  friction=dict(L=case['friction'], R=case['friction']),
                                  tail_enabled=case['tail'])
            frame = loop.step(env)
            if restored is not None:
                cold_equal = cold_equal and frame == restored.step(env)
                replay_frames += 1
            row = sample(frame)
            if row['valid']:
                for k in range(2):
                    alpha = row['tail_torque'][k] / fixture['tail_inertia_kg_m2']
                    max_error = max(max_error,
                                    abs(row['tail_speed'][k] - (before_speed[k] + alpha * .1)),
                                    abs(row['tail_angle'][k] - (before_angle[k] + before_speed[k] * .1 + alpha * .005)))
                expected_energy = .5 * fixture['tail_inertia_kg_m2'] * sum(v*v for v in row['tail_speed'])
                max_error = max(max_error, abs(expected_energy - row['tail_energy_J']))
            samples.append(row)
            if not row['valid']:
                break
        if reference_checkpoint is None:
            reference_checkpoint = loop.checkpoint()
        rows.append(dict(case=case['id'], frames=len(samples),
                         simulated_s=.1 * len(samples), valid_throughout=all(r['valid'] for r in samples),
                         failure=samples[-1]['failure'], final_phase=samples[-1]['phase'],
                         walk_touchdowns=samples[-1]['walk_steps'],
                         first=samples[0], final=samples[-1],
                         peak_pressure_kpa=max(v for r in samples for v in r['pressure_kpa'].values()),
                         peak_tail_speed_rad_s=max(abs(v) for r in samples for v in r['tail_speed']),
                         peak_tail_angle_rad=max(abs(v) for r in samples for v in r['tail_angle']),
                         peak_tail_torque_Nm=max(math.hypot(*r['tail_torque']) for r in samples),
                         fuel_used_J=sum(r['fuel_used_J'] for r in samples),
                         minimum_capture_margin_m=min(r['capture_margin_m'] for r in samples),
                         cold_restore_exercised=restored is not None, cold_restore_equal=cold_equal,
                         replay_frames=replay_frames,
                         tail_integration_and_energy_max_error=max_error,
                         physical_trace_sha256=digest(samples)))
    return dict(cases=rows, reference_checkpoint=reference_checkpoint,
                foreign_checkpoint_rejected=cold_rejection)


def validate_plan(plan):
    if plan['status'] != 'sandbox_only':
        raise ValueError('blocked candidate cannot be instantiated')
    _, native = body_sources()
    design = plan['design']
    if set(design) != set(native) or plan['native_apply_allowed'] is not False:
        raise ValueError('invalid sandbox design fields or permission')
    changes = {key: dict(before=native[key], after=value) for key, value in design.items()
               if value != native[key]}
    if (set(changes) - {'tail_length_m', 'tail_inertia_kg_m2'} or
            changes != plan['changes'] or plan['native_design_sha256'] != digest(native) or
            plan['sandbox_design_sha256'] != digest(design)):
        raise ValueError('sandbox plan mismatch or change outside the allowlist')
    for key in ('tail_length_m', 'tail_inertia_kg_m2'):
        value = design[key]
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            raise ValueError('invalid sandbox tail parameter')
    if not .98 * native['tail_length_m'] - 1e-12 <= design['tail_length_m'] <= 1.02 * native['tail_length_m'] + 1e-12:
        raise ValueError('tail length outside the frozen exploration bounds')
    if plan['purpose'] == 'genotype_candidate_with_declared_inertia_closure':
        expected = native['tail_mass_kg'] * design['tail_length_m']**2 / 3.
    elif plan['purpose'] == 'diagnostic_length_descriptor_only; not a coherent geometric candidate':
        expected = native['tail_inertia_kg_m2']
    else:
        raise ValueError('unknown sandbox purpose')
    if not math.isclose(design['tail_inertia_kg_m2'], expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError('sandbox inertia closure mismatch')


def run_copy(plan, manifest, foreign_checkpoint=None):
    validate_plan(plan)
    with tempfile.TemporaryDirectory(prefix='nasuraya-genome-physics-') as directory:
        source = Path(directory)
        for name in manifest:
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BODY / name, dest)
        (source / RELATIVE_CONTACT).write_text(json.dumps(plan['design'], indent=2) + '\n')
        changed_files = [name for name, expected in manifest.items()
                         if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected]
        if set(changed_files) - {str(RELATIVE_CONTACT)}:
            raise ValueError('copied equations differ from verified source')
        request = dict(source=str(source), plan=plan)
        if foreign_checkpoint is not None:
            request['foreign_checkpoint'] = foreign_checkpoint
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        env['PYTHONPATH'] = str(ROOT)
        process = subprocess.run([sys.executable, '-m', 'examples.nasuraya_genome.physics_trial', '--worker'],
                                 input=json.dumps(request), text=True, capture_output=True,
                                 cwd=directory, env=env, timeout=40, check=True)
        result = json.loads(process.stdout)
        # No copied Python/data file is allowed to change during the trial either.
        for name, expected in manifest.items():
            if name != str(RELATIVE_CONTACT) and hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError('sandbox mutated a retained source')
        result.update(equation_files_unchanged=True, fixture_only_changed=True,
                      sandbox_design_sha256=plan['sandbox_design_sha256'])
        return result


def tail_genotype(scale):
    return mutate(baseline(), [dict(chromosome='P09' + h, locus='P09.L010', value=scale)
                               for h in 'AB'], expected_revision=0)


def length_only_ablation(long_plan):
    """Diagnostic counterfactual: a longer descriptor with unchanged inertia.

    This deliberately omits geometric closure and is never an anatomical design.
    It tests which parameter is actually consumed by the retained equations.
    """
    plan = deepcopy(long_plan)
    _, native = body_sources()
    plan['purpose'] = 'diagnostic_length_descriptor_only; not a coherent geometric candidate'
    plan['assumptions'] = ['tail length descriptor varies while inertia stays fixed; diagnostic ablation only']
    plan['design']['tail_inertia_kg_m2'] = native['tail_inertia_kg_m2']
    plan['changes'] = {key: dict(before=native[key], after=value) for key, value in plan['design'].items()
                       if value != native[key]}
    plan['sandbox_design_sha256'] = digest(plan['design'])
    validate_plan(plan)
    return plan


def evaluate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = verified_sources()
    variants = dict(baseline=baseline(), tail_short=tail_genotype(.98), tail_long=tail_genotype(1.02))
    cosmetic = mutate(baseline(), [dict(chromosome='P08A', locus='P08.L010', value=5.)], expected_revision=0)
    foot = mutate(baseline(), [dict(chromosome='P07' + h, locus=lid, value=1.02)
                              for h in 'AB' for lid in ('P07.L010', 'P07.L011')], expected_revision=0)
    plans = {name: compile_candidate(g) for name, g in variants.items()}
    plans['length_only_ablation'] = length_only_ablation(plans['tail_long'])
    frozen = dict(schema=SCHEMA, cases=CASES, dt_s=.1, max_frames_per_case=60,
                  variants=plans, assumptions=ASSUMPTIONS,
                  experiment_sources_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                              for name in ('physics_trial.py', 'traits.py', 'chromosomes.py',
                                                           'genome48.json', 'contract-v0.1.json')},
                  criteria=dict(expected_failure={'zero_friction': 'friction_limit_exceeded'},
                                other_cases_expected_valid=True, numerical_error_ceiling=1e-12,
                                enforce_fixture_tail_and_pressure_limits=True),
                  source_manifest_sha256=digest(manifest), native_apply_allowed=False,
                  acceptance='reproducible bounded sensitivity, not phenotype improvement or production approval')
    (output / 'frozen-plan.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + '\n')
    # Freeze the protocol before observing any trial result.
    baseline_result = run_copy(plans['baseline'], manifest)
    foreign = baseline_result['reference_checkpoint']
    results = {'baseline': baseline_result}
    for name in ('tail_short', 'tail_long', 'length_only_ablation'):
        results[name] = run_copy(plans[name], manifest, foreign_checkpoint=foreign)
    cosmetic_plan = compile_candidate(cosmetic)
    foot_plan = compile_candidate(foot)
    checks = dict(
        all_equations_unchanged=all(r['equation_files_unchanged'] for r in results.values()),
        all_exercised_cold_restores_equal=all(c['cold_restore_equal'] for r in results.values() for c in r['cases']),
        variant_rejects_baseline_checkpoint=all(results[n]['foreign_checkpoint_rejected']
                                               for n in ('tail_short', 'tail_long', 'length_only_ablation')),
        cosmetic_has_identical_native_design=cosmetic_plan['design'] == plans['baseline']['design'],
        foot_change_blocked=foot_plan['status'] == 'blocked',
        tail_off_trajectories_equal=len({next(c['physical_trace_sha256'] for c in r['cases']
                                             if c['case'] == 'impulse_tail_off') for r in results.values()}) == 1,
        zero_friction_failure_preserved=all(next(c for c in r['cases'] if c['case'] == 'zero_friction')['failure']
                                            == 'friction_limit_exceeded' for r in results.values()),
        declared_valid_cases_preserved=all(c['valid_throughout'] for r in results.values()
                                          for c in r['cases'] if c['case'] != 'zero_friction'),
        tail_response_changes=len({next(c['physical_trace_sha256'] for c in results[n]['cases']
                                       if c['case'] == 'tail_displacement')
                                   for n in ('baseline', 'tail_short', 'tail_long')}) == 3,
        descriptor_only_matches_baseline=all(a['physical_trace_sha256'] == b['physical_trace_sha256']
                                             for a, b in zip(results['baseline']['cases'],
                                                             results['length_only_ablation']['cases'])),
        integration_consistent=all(c['tail_integration_and_energy_max_error'] <= 1e-12
                                   for r in results.values() for c in r['cases']),
        fixture_limits_respected=all(
            c['peak_tail_angle_rad'] <= plans[n]['design']['tail_angle_limit_rad'] + 1e-9 and
            c['peak_tail_speed_rad_s'] <= plans[n]['design']['tail_speed_limit_rad_s'] + 1e-9 and
            c['peak_tail_torque_Nm'] <= plans[n]['design']['tail_torque_limit_Nm'] + 1e-9 and
            c['peak_pressure_kpa'] <= plans[n]['design']['pressure_ceiling_kpa'] + 1e-9
            for n, r in results.items() for c in r['cases']),
        source_manifest_unchanged=verified_sources() == manifest,
    )
    if not all(checks.values()):
        raise AssertionError(checks)
    # Internal source-bound native checkpoints stay in this temporary experiment,
    # not in public evidence or any live state directory.
    for r in results.values():
        del r['reference_checkpoint']
    result = dict(schema=SCHEMA, frozen_plan_sha256=digest(frozen), checks=checks, results=results,
                  unsupported_foot_plan=foot_plan, cases_per_variant=len(CASES),
                  native_run_count=len(results) * len(CASES),
                  simulated_s=sum(c['simulated_s'] for r in results.values() for c in r['cases']),
                  cold_replay_simulated_s=.1 * sum(c['replay_frames'] for r in results.values() for c in r['cases']),
                  cold_restore_branches=sum(c['cold_restore_exercised'] for r in results.values() for c in r['cases']),
                  original_live_state_loaded=False, API_calls=0, native_apply_allowed=False,
                  physical_model_scope='fixed COM reduced flywheel sensitivity; no anatomical validation',
                  demonstrated_physical_improvement=False)
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
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
        print(json.dumps(dict(checks=result['checks'], native_run_count=result['native_run_count'],
                              simulated_s=result['simulated_s'])))
    else:
        parser.error('--output required')
