"""Source-bound design recommendations from measured sandbox receipts.

The policy is authored and frozen, not fitted to candidate outcomes. Evidence
can affect a recommendation but never modifies the owner body or its genotype.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from .chromosomes import digest
from .foot_contact import compile_foot
from .foot_trial import CASES
from .traits import baseline, body_sources, checkpoint, mutate, restore
from examples.nasuraya_body_loop.__main__ import verified_sources

HERE = Path(__file__).parent
SCHEMA = 'nasuraya.design-experience/0.1'


def policy():
    p = json.loads((HERE / 'design-policy-v0.1.json').read_text())
    if (p['schema'] != 'nasuraya.design-selection-policy/0.1' or
            set(p['weights']) != {'pressure', 'capture_margin', 'fuel'} or
            any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in p['weights'].values()) or
            not math.isclose(sum(p['weights'].values()), 1.) or p['native_apply_allowed'] is not False):
        raise ValueError('invalid decision policy')
    return p


def candidates():
    result = {'baseline': baseline()}
    for name, scale in (('foot_plus_1_percent', 1.01), ('foot_plus_2_percent', 1.02)):
        edits = [dict(chromosome='P07' + h, locus=lid, value=scale)
                 for h in 'AB' for lid in ('P07.L010', 'P07.L011')]
        result[name] = mutate(baseline(), edits, expected_revision=0)
    result['cosmetic_only'] = mutate(baseline(), [dict(chromosome='P08A', locus='P08.L010', value=5.)],
                                     expected_revision=0)
    return result


def sources():
    names = ('design_decision.py', 'design_memory.py', 'run_design_cycle.py',
             'design-policy-v0.1.json', 'foot_contact.py', 'foot_trial.py',
             'physics_trial.py', 'traits.py', 'chromosomes.py', 'contract-v0.1.json', 'genome48.json')
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in names}


def context():
    """Exact software condition, not a claim about the current live body's state."""
    return dict(mission=policy()['mission'], source_manifest_sha256=digest(verified_sources()),
                engine_sources=sources(), cases=deepcopy(CASES), dt_s=.1,
                initial_state='fresh synthetic PostureLoop for each case', mapping='authored affine pad hypothesis',
                scope='this exact fixed-mass, fixed-controller software context only')


def contract():
    return dict(schema=SCHEMA, policy=policy(), context=context(),
                candidates={name: checkpoint(g) for name, g in candidates().items()},
                learning_layer='external design experience; never inherited into alleles')


def intent(contract, name):
    if name not in contract['candidates']:
        raise ValueError('unknown candidate')
    genotype = restore(contract['candidates'][name])
    plan = compile_foot(genotype)
    return dict(candidate=name, genotype_sha256=digest(genotype), context_sha256=digest(contract['context']),
                design_sha256=plan['design_sha256'], mesh_sha256=plan['mesh_sha256'],
                cases_sha256=digest(CASES), native_apply_allowed=False)


def finite(value, *, minimum=0.):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value < minimum:
        raise ValueError('invalid finite metric')
    return value


def metrics(receipt):
    """Derive decisions from retained native outputs, never accept a supplied score."""
    if receipt.get('original_equations_retained_in_copy') is not True:
        raise ValueError('missing native source check')
    dynamic = receipt['dynamic']
    static = receipt['static']
    if ([r['case'] for r in dynamic] != [c['id'] for c in CASES] or
            [s['case'] for s in static] != ['nominal_single_support', 'forward_edge_request',
                                         'over_capacity_negative_control']):
        raise ValueError('incomplete or reordered experiment evidence')
    for row, case in zip(dynamic, CASES):
        for key in ('valid_throughout', 'cold_restore_exercised', 'cold_restore_equal'):
            if type(row[key]) is not bool:
                raise ValueError('invalid outcome flag')
        if (type(row['frames']) is not int or not 1 <= row['frames'] <= case['frames'] or
                type(row['walk_touchdowns']) is not int or row['walk_touchdowns'] < 0):
            raise ValueError('invalid progress or elapsed frames')
        for key in ('fuel_used_J', 'peak_pressure_kpa', 'minimum_support_fraction'):
            finite(row[key])
        finite(row['minimum_capture_margin_m'], minimum=-1e6)
        if (row['valid_throughout'] and (row['failure'] is not None or row['frames'] != case['frames'])):
            raise ValueError('success has a failure or incomplete horizon')
        trace = row['physical_trace_sha256']
        if type(trace) is not str or len(trace) != 64 or any(c not in '0123456789abcdef' for c in trace):
            raise ValueError('invalid trace digest')
    nominal, edge, overload = static
    for row in static:
        if type(row['feasible']) is not bool:
            raise ValueError('invalid static feasibility')
        finite(row['requested_normal_N'])
        finite(row['achieved_normal_N'])
        for value in row['pressures_kpa'].values():
            finite(value)
        if row['feasible']:
            finite(row['force_error_N'])
            finite(row['moment_error_Nm'])
    walk = next(d for d in dynamic if d['case'] == 'walk')
    return dict(pressure_kpa=max(nominal['pressures_kpa'].values()) if nominal['feasible'] else None,
                capture_margin_m=walk['minimum_capture_margin_m'], fuel_J=walk['fuel_used_J'],
                walk_touchdowns=walk['walk_touchdowns'], walk_frames=walk['frames'],
                all_ordinary_cases_valid=all(d['valid_throughout'] for d in dynamic if d['case'] != 'zero_friction'),
                all_ordinary_horizons_complete=all(d['frames'] == c['frames'] for d, c in zip(dynamic, CASES)
                                                  if d['case'] != 'zero_friction'),
                peak_dynamic_pressure_kpa=max(d['peak_pressure_kpa'] for d in dynamic),
                peak_static_pressure_kpa=max((v for s in static for v in s['pressures_kpa'].values()), default=0.),
                minimum_support_fraction=min(d['minimum_support_fraction'] for d in dynamic
                                             if d['case'] != 'zero_friction'),
                cold_restores_equal=all(d['cold_restore_equal'] and d['cold_restore_exercised']
                                        for d in dynamic if d['case'] != 'zero_friction'),
                zero_friction_failure_retained=dynamic[-1]['failure'] == 'friction_limit_exceeded',
                overload_failure_retained=not overload['feasible'],
                static_nominal_feasible=nominal['feasible'],
                static_conservation_valid=all(s['force_error_N'] <= 1e-7 and s['moment_error_Nm'] <= 1e-7
                                              for s in static if s['feasible']))


def committed_source(variant):
    if variant not in ('baseline', 'affine'):
        raise ValueError('unsupported prior experiment variant')
    directory = HERE / 'evidence/foot-contact-v0.1'
    frozen = json.loads((directory / 'frozen-plan.json').read_text())
    result = json.loads((directory / 'results.json').read_text())
    if (digest(frozen) != result['frozen_plan_sha256'] or frozen['cases'] != CASES or
            frozen['source_manifest_sha256'] != digest(verified_sources()) or not all(result['checks'].values())):
        raise ValueError('prior experiment has a different context or invalid checks')
    for name, sha in frozen['experiment_sources_sha256'].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != sha:
            raise ValueError('prior experiment engine has changed')
    source = dict(kind='reused_committed_fixture_receipt', variant=variant,
                  frozen_plan_sha256=digest(frozen),
                  result_file_sha256=hashlib.sha256((directory / 'results.json').read_bytes()).hexdigest(),
                  physical_trial_id='foot-contact-v0.1.' + variant)
    return source, result['results'][variant], frozen['plans'][variant]['design_sha256']


def fresh_source(c, trial_id):
    if type(trial_id) is not str or not trial_id or len(trial_id) > 70:
        raise ValueError('invalid fresh trial identity')
    return dict(kind='fresh_sandbox_execution', physical_trial_id=trial_id,
                engine_context_sha256=digest(c['context']))


def evidence(contract, name, receipt, source):
    if source['kind'] == 'reused_committed_fixture_receipt':
        expected, prior, design = committed_source(source['variant'])
        if source != expected or receipt != prior or design != intent(contract, name)['design_sha256']:
            raise ValueError('prior receipt is not from the identical physical fixture')
    elif source['kind'] == 'fresh_sandbox_execution':
        if source != fresh_source(contract, source['physical_trial_id']):
            raise ValueError('fresh trial context mismatch')
    else:
        raise ValueError('unknown observation provenance')
    plan = compile_foot(restore(contract['candidates'][name]))
    design = plan['design']
    for row in receipt['static']:
        if not math.isclose(row['area_each_foot_cm2'], sum(p['area_m2'] for p in design['patches'])*1e4,
                            rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError('static receipt has a different contact area')
        if row['feasible']:
            pressures = row['pressures_kpa']
            if set(pressures) != {'L_' + p['id'] for p in design['patches']}:
                raise ValueError('static pressure witness is incomplete')
            forces = [pressures['L_' + p['id']]*1000*p['area_m2'] for p in design['patches']]
            total = sum(forces)
            if total <= 0 or abs(total-row['requested_normal_N']) > 1e-7 or abs(total-row['achieved_normal_N']) > 1e-7:
                raise ValueError('static pressure witness does not conserve vertical force')
            actual_cop = [sum((p['xy'][k] + (design['foot_half_spacing_m'] if k == 0 else 0.))*f
                              for p, f in zip(design['patches'], forces))/total for k in (0, 1)]
            if math.dist(actual_cop, row['achieved_cop_m']) > 1e-10:
                raise ValueError('static pressure witness does not conserve moment')
    return dict(intent=intent(contract, name), receipt=deepcopy(receipt), metrics=metrics(receipt),
                source=deepcopy(source),
                evidence_kind='source-bound local software observation under trusted host',
                samples=1, physical_world_validated=False, native_apply_allowed=False)


def verify_evidence(c, name, saved):
    if saved != evidence(c, name, saved['receipt'], saved['source']):
        raise ValueError('evidence, metrics, source or phenotype mismatch')


def rejection_reasons(m, p, pressure_ceiling):
    reasons = []
    for key in ('all_ordinary_cases_valid', 'all_ordinary_horizons_complete', 'cold_restores_equal',
                'zero_friction_failure_retained', 'overload_failure_retained', 'static_nominal_feasible',
                'static_conservation_valid'):
        if not m[key]:
            reasons.append(key)
    if m['minimum_support_fraction'] < p['minimum_support_fraction']:
        reasons.append('insufficient_support')
    if m['capture_margin_m'] <= 0:
        reasons.append('nonpositive_capture_margin')
    if max(m['peak_dynamic_pressure_kpa'], m['peak_static_pressure_kpa']) > pressure_ceiling + 1e-8:
        reasons.append('pressure_ceiling_exceeded')
    return reasons


def choose(c, observations, *, pending=(), requested_context=None, use_memory=True):
    """A recommendation only: eligibility before utility, with explicit abstention."""
    if type(use_memory) is not bool:
        raise ValueError('explicit memory flag required')
    if set(observations) - set(c['candidates']):
        raise ValueError('unknown observed candidate')
    for name, obs in observations.items():
        verify_evidence(c, name, obs)
    result = dict(schema=SCHEMA, chosen=None, native_apply_allowed=False,
                  context_sha256=digest(c['context']), memory_used=use_memory,
                  observations_considered=[], candidates={},
                  confidence='one deterministic software observation per design; no statistical confidence')
    if pending:
        return dict(result, reason='unresolved_trial_requires_reconciliation', pending=list(pending))
    if requested_context is not None and requested_context != c['context']:
        return dict(result, chosen='baseline', reason='unseen_context_retain_baseline', memory_used=False)
    if not use_memory or 'baseline' not in observations:
        return dict(result, chosen='baseline', reason='retain_baseline_pending_comparison')
    p = c['policy']
    _, native = body_sources()
    base = observations['baseline']['metrics']
    if (rejection_reasons(base, p, native['pressure_ceiling_kpa']) or base['fuel_J'] <= 0 or
            base['pressure_kpa'] is None or base['pressure_kpa'] <= 0):
        return dict(result, reason='baseline_evidence_invalid_for_comparison')
    result['observations_considered'] = sorted(observations)
    eligible = []
    for name in c['candidates']:
        if name not in observations:
            result['candidates'][name] = dict(status='unmeasured', reasons=['requires_measurement'])
            continue
        m = observations[name]['metrics']
        reasons = rejection_reasons(m, p, native['pressure_ceiling_kpa'])
        if m['walk_touchdowns'] != base['walk_touchdowns'] or m['walk_frames'] != base['walk_frames']:
            reasons.append('progress_not_comparable')
        fuel_delta = (m['fuel_J'] - base['fuel_J']) / base['fuel_J']
        if fuel_delta > p['maximum_relative_fuel_increase']:
            reasons.append('fuel_increase_exceeds_budget')
        if reasons:
            result['candidates'][name] = dict(status='rejected', reasons=reasons, gains=None,
                                              utility=None, metrics=deepcopy(m))
            continue
        gains = dict(pressure=(base['pressure_kpa']-m['pressure_kpa'])/base['pressure_kpa'],
                     capture_margin=(m['capture_margin_m']-base['capture_margin_m'])/base['capture_margin_m'],
                     fuel=-fuel_delta)
        utility = sum(p['weights'][key]*value for key, value in gains.items()) - (p['change_penalty'] if name != 'baseline' else 0.)
        if name != 'baseline' and utility <= p['minimum_net_gain']:
            reasons.append('no_sufficient_measured_net_gain')
        status = 'rejected' if reasons else 'baseline_reference' if name == 'baseline' else 'eligible_proposal'
        result['candidates'][name] = dict(status=status, reasons=reasons, gains=gains,
                                          utility=utility, metrics=deepcopy(m))
        if not reasons:
            eligible.append((utility, name))
    best = sorted(eligible, key=lambda row: (-row[0], row[1]))
    result.update(chosen=best[0][1] if best else None,
                  reason='highest_frozen_utility_among_admissible_measured_proposals' if best else 'no_admissible_proposal')
    return result
