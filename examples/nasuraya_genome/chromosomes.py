"""Read-only design capacity audit. No body mutation or biological gene editing."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load_design():
    design = json.loads(Path(__file__).with_name('genome48.json').read_text())
    validate(design)
    return design


def validate(design):
    if design['schema'] != 'nasuraya.genome48.v1':
        raise ValueError('unsupported design')
    if design['design_chromosome_count'] != 48 or design['homologs'] != ['A', 'B']:
        raise ValueError('48 chromosome design requires A/B homologs')
    if design['learned_overlays'] != ['G22', 'G23']:
        raise ValueError('learned overlays must stay outside inherited design')
    modules = {m['id']: m for m in design['modules']}
    domains = {d['id']: d for d in design['domains']}
    pairs = {p['id']: p for p in design['pairs']}
    if len(modules) != len(design['modules']) or set(modules) != {f'G{i:02d}' for i in range(22)}:
        raise ValueError('22 unique anatomical modules required')
    if len(domains) != len(design['domains']) or set(domains) != {f'C{i:02d}' for i in range(1, 13)}:
        raise ValueError('12 unique regulatory domains required')
    if len(pairs) != len(design['pairs']) or set(pairs) != {f'P{i:02d}' for i in range(1, 25)}:
        raise ValueError('24 unique pairs required')
    coverage = [m for d in domains.values() for m in d['modules']]
    if len(coverage) != 22 or set(coverage) != set(modules):
        raise ValueError('anatomical modules must have unique domain coverage')
    chromosomes = []
    linked = []
    for d in domains.values():
        for role in ('development', 'maintenance'):
            pid = d[role + '_pair']
            if pid not in pairs:
                raise ValueError('missing pair')
            p = pairs[pid]
            if p['domain'] != d['id'] or p['role'] != role:
                raise ValueError('pair role/domain mismatch')
            if p['chromosomes'] != [pid + 'A', pid + 'B']:
                raise ValueError('invalid homolog identities')
            linked.append(pid)
            chromosomes.extend(p['chromosomes'])
    if len(set(linked)) != 24 or len(set(chromosomes)) != 48:
        raise ValueError('duplicate pair or chromosome')
    pending = set(modules)
    ordered = []
    while pending:
        ready = sorted(mid for mid in pending if set(modules[mid]['needs']) <= set(ordered))
        if not ready:
            raise ValueError('missing dependency or dependency cycle')
        for mid in ready:
            m = modules[mid]
            if m['first_phase'] not in ('S0', 'S1', 'S2', 'S3', 'S4'):
                raise ValueError('invalid phase')
            if len(m['needs']) != len(set(m['needs'])):
                raise ValueError('duplicate dependency')
        ordered.extend(ready)
        pending.difference_update(ready)
    return ordered


def audit(design, copies=None, boundary_faults=(), phase='S3'):
    """Project bounded capacities; caller declarations are not observed DNA faults.

    Each homolog contributes half nominal capacity; extra copies never amplify it.
    Development propagates source prerequisites. Adult maintenance remains a local
    expression ceiling: it does not erase organs or grant permission to act.
    """
    ordered = validate(design)
    if phase not in ('S0', 'S1', 'S2', 'S3', 'S4'):
        raise ValueError('invalid phase')
    declared = {} if copies is None else deepcopy(copies)
    if not isinstance(declared, dict):
        raise ValueError('copies must be a mapping')
    chromosome_ids = {c for p in design['pairs'] for c in p['chromosomes']}
    if set(declared) - chromosome_ids:
        raise ValueError('unknown chromosome')
    for n in declared.values():
        if type(n) is not int or not 0 <= n <= 4:
            raise ValueError('copy count must be an integer from 0 to 4')
    faults = list(boundary_faults)
    if len(faults) != len(set(faults)) or set(faults) - {d['id'] for d in design['domains']}:
        raise ValueError('invalid boundary fault')
    states = {}
    for p in design['pairs']:
        homolog_counts = {c: declared.get(c, 1) for c in p['chromosomes']}
        raw = sum(homolog_counts.values())
        states[p['id']] = dict(raw_copies=raw, homolog_counts=homolog_counts,
                              copy_deviation=any(n != 1 for n in homolog_counts.values()),
                              capacity=min(1., raw / 2.))
    module_domain = {m: d for d in design['domains'] for m in d['modules']}
    modules = {m['id']: m for m in design['modules']}
    outputs = {}
    for mid in ordered:
        m = modules[mid]
        d = module_domain[mid]
        available = d['id'] not in faults
        dev = states[d['development_pair']]['capacity'] if available else 0.
        maintenance = states[d['maintenance_pair']]['capacity'] if available else 0.
        dependencies = {dep: outputs[dep]['development_capacity'] for dep in m['needs']}
        eligible_phase = int(m['first_phase'][1]) <= int(phase[1])
        dev = min([dev] + list(dependencies.values())) if eligible_phase else 0.
        if mid == 'G12':
            dev = maintenance = 0.
        outputs[mid] = dict(domain=d['id'], phase_eligible=eligible_phase,
                            development_capacity=dev, maintenance_ceiling=maintenance,
                            development_dependencies=dependencies,
                            boundary_quarantined=not available,
                            permanently_disabled=mid == 'G12')
    payload = dict(schema='nasuraya.genome48.audit.v1', design_sha256=digest(design),
                   phase=phase, copies=declared, boundary_faults=sorted(faults),
                   pairs=states, modules=outputs, learned_overlays_encoded=False,
                   native_body_advanced=False, energy_or_material_created=False,
                   action_permission_granted=False,
                   scope='dimensionless software design capacity; not physiological performance')
    return dict(payload=payload, sha256=digest(payload))


def verify(saved, design):
    if saved['sha256'] != digest(saved['payload']):
        raise ValueError('audit checksum mismatch')
    p = saved['payload']
    expected = audit(design, p['copies'], p['boundary_faults'], p['phase'])
    if saved != expected:
        raise ValueError('audit does not match source design and declared condition')
    return deepcopy(saved)


def evaluate():
    design = load_design()
    frozen = digest(design)
    baseline = audit(design)
    rows = []
    for pair in design['pairs']:
        for chromosome in pair['chromosomes']:
            trial = audit(design, {chromosome: 0})
            affected = [m for m, v in trial['payload']['modules'].items()
                        if v != baseline['payload']['modules'][m]]
            assert trial['payload']['pairs'][pair['id']]['capacity'] == .5
            verify(json.loads(json.dumps(trial)), design)
            rows.append(dict(chromosome=chromosome, pair=pair['id'], domain=pair['domain'],
                             role=pair['role'], affected_modules=affected,
                             capacity=.5))
    faults = []
    for d in design['domains']:
        trial = audit(design, boundary_faults=[d['id']])
        assert all(trial['payload']['modules'][m]['maintenance_ceiling'] == 0. for m in d['modules'])
        assert all(trial['payload']['modules'][m]['maintenance_ceiling'] == v['maintenance_ceiling']
                   for m, v in baseline['payload']['modules'].items() if m not in d['modules'])
        faults.append(dict(domain=d['id'], audit_sha256=trial['sha256'],
                           local_quarantine=True, unrelated_maintenance_unchanged=True))
    duplicates = []
    for pair in design['pairs']:
        for chromosome in pair['chromosomes']:
            trial = audit(design, {chromosome: 2})
            assert trial['payload']['modules'] == baseline['payload']['modules']
            duplicates.append(dict(chromosome=chromosome, amplification=False,
                                   deviation_flagged=trial['payload']['pairs'][pair['id']]['copy_deviation']))
    phases = [dict(phase=p, audit_sha256=audit(design, phase=p)['sha256'])
              for p in ('S0', 'S1', 'S2', 'S3', 'S4')]
    assert digest(design) == frozen
    return dict(design_sha256=digest(design), chromosome_count=48,
                single_copy_loss_cases=rows, case_count=len(rows),
                boundary_fault_cases=faults, extra_copy_cases=duplicates, phase_cases=phases,
                total_conditions=1 + len(rows) + len(faults) + len(duplicates) + len(phases),
                baseline_audit=baseline, source_unchanged=True,
                claim='software contract sensitivity; no biological phenotype improvement measured')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(evaluate(), ensure_ascii=False, indent=2) + '\n')
