"""Genome v0.1: bounded design proposals, never a native-body write API.

The 24 A/B pairs and capacity audit are inherited from chromosomes.py.
L000 is a software copy-count locus, not an experimentally identified gene.
Four additional loci demonstrate allele-to-trait expression in a separate layer.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import tempfile

from .chromosomes import audit, digest, load_design

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BODY = ROOT / 'runtimes/tadash_body'
CONTACT = BODY / 'base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json'
VERSION = '0.1.0'
POLICY = {
    'face': 'external approved fixed face; no face mutation or rendering API',
    'narrative_roots': ['Iran', 'Zagros', 'father: dervish from Dalahu'],
    'principles': ['wisdom_before_force', 'keep_covenants', 'humility',
                   'compassion_with_boundaries', 'trust_with_responsible_action'],
    'body_contract': {'fingers_per_hand': 5, 'toes_per_foot': 3, 'horns': 2,
                      'digitigrade': True, 'external_converter_default_active': False},
    'native_write_permission': False,
}
# Bounds are authored exploration bounds, not a validated safety envelope.
TRAITS = {
    'P07.L010': dict(pair='P07', layer='structural', name='foot_length_scale',
                     minimum=1., maximum=1.02, default=1., unit='ratio',
                     target='adult_scale.feet.length_cm', module='G04'),
    'P07.L011': dict(pair='P07', layer='structural', name='foot_width_scale',
                     minimum=1., maximum=1.02, default=1., unit='ratio',
                     target='adult_scale.feet.spread_width_cm', module='G04'),
    'P09.L010': dict(pair='P09', layer='structural', name='tail_length_scale',
                     minimum=.98, maximum=1.02, default=1., unit='ratio',
                     target='contact_design_v06.tail_length_m', module='G05'),
    'P08.L010': dict(pair='P08', layer='appearance', name='foot_fur_length_mm',
                     minimum=1., maximum=8., default=3., unit='mm',
                     target='render_only.feet.fur_length_mm', module='G04'),
}


def body_sources():
    return (json.loads((BODY / 'phenotype_v1.json').read_text()),
            json.loads(CONTACT.read_text()))


def build_contract():
    """Author the closed, versioned catalogue; all 48 IDs retain their old meaning."""
    design = load_design()
    phenotype, contact = body_sources()
    for key, value in POLICY['body_contract'].items():
        if phenotype['phenotype_contract'][key] != value or design['phenotype_contract'][key] != value:
            raise ValueError('protected body contract conflict')
    domains = {d['id']: d for d in design['domains']}
    loci, chromosomes = {}, []
    for pair in design['pairs']:
        loc = pair['id'] + '.L000'
        loci[loc] = dict(pair=pair['id'], layer='simulated_physiology_proxy',
                         name='declared_copy_count', type='integer', minimum=0, maximum=4,
                         default=1, unit='copies', modules=domains[pair['domain']]['modules'],
                         expression='existing audit: min(1, (A+B)/2); G12 stays disabled',
                         status='implemented software capacity proxy; no organ performance claim')
        for lid, spec in TRAITS.items():
            if spec['pair'] == pair['id']:
                loci[lid] = dict(spec, type='number', expression='arithmetic_mean_A_B',
                                 status='implemented proposal only; physical effect unvalidated')
        for cid in pair['chromosomes']:
            chromosomes.append(dict(id=cid, pair=pair['id'], homolog=cid[-1],
                                    domain=pair['domain'], role=pair['role'],
                                    modules=domains[pair['domain']]['modules'],
                                    loci=[lid for lid, s in loci.items() if s['pair'] == pair['id']]))
    return dict(schema='nasuraya.genome.contract', version=VERSION,
                architecture='24 homologous A/B pairs; authored design, no parental assignment',
                source_design_sha256=digest(design),
                body_source_sha256={'phenotype_v1.json': digest(phenotype),
                                    'contact_design_v06.json': digest(contact)},
                policy=POLICY, chromosomes=chromosomes, loci=loci,
                learned_layer={'external_modules': ['G22', 'G23'], 'inherited': False,
                               'learning_state': 'external; never imported or reset by this module'},
                unimplemented='All biological interpretation and all other loci remain unimplemented')


def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def build_schema(contract):
    chromosomes = {}
    for chromosome in contract['chromosomes']:
        alleles = {}
        for lid in chromosome['loci']:
            spec = contract['loci'][lid]
            alleles[lid] = {k: spec[k] for k in ('type', 'minimum', 'maximum')}
        chromosomes[chromosome['id']] = object_schema(alleles)
    schema = object_schema({
        'schema': {'const': 'nasuraya.genotype'}, 'version': {'const': VERSION},
        'contract_sha256': {'const': digest(contract)},
        'revision': {'type': 'integer', 'minimum': 0},
        'parent_sha256': {'anyOf': [{'type': 'null'}, {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}]},
        'chromosomes': object_schema(chromosomes),
    })
    schema.update({'if': {'properties': {'revision': {'const': 0}}},
                   'then': {'properties': {'parent_sha256': {'type': 'null'}}},
                   'else': {'properties': {'parent_sha256': {'type': 'string',
                                                               'pattern': '^[0-9a-f]{64}$'}}}})
    return dict(schema, **{'$schema': 'http://json-schema.org/draft-07/schema#',
                           'title': 'Nasuraya computational genotype v0.1.0'})


def contract():
    saved = json.loads((HERE / 'contract-v0.1.json').read_text())
    if saved != build_contract():
        raise ValueError('catalogue/source drift: requires explicit versioned review')
    return saved


def closed(value, keys, context):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('invalid fields: ' + context)


def number(value, spec):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError('allele must be a finite JSON number, not boolean')
    if spec['type'] == 'integer' and type(value) is not int:
        raise ValueError('copy counts must be integers')
    if not spec['minimum'] <= value <= spec['maximum']:
        raise ValueError('allele outside authored exploration bounds')


def validate_genotype(genotype):
    c = contract()
    closed(genotype, ('schema', 'version', 'contract_sha256', 'revision',
                      'parent_sha256', 'chromosomes'), 'genotype')
    if (genotype['schema'] != 'nasuraya.genotype' or genotype['version'] != VERSION
            or genotype['contract_sha256'] != digest(c)):
        raise ValueError('genotype schema/version/contract mismatch')
    revision, parent = genotype['revision'], genotype['parent_sha256']
    if type(revision) is not int or revision < 0:
        raise ValueError('invalid revision')
    if ((revision == 0 and parent is not None) or
            (revision > 0 and (type(parent) is not str or len(parent) != 64 or
                              any(x not in '0123456789abcdef' for x in parent)))):
        raise ValueError('invalid parent digest')
    closed(genotype['chromosomes'], [x['id'] for x in c['chromosomes']], 'chromosomes')
    for ch in c['chromosomes']:
        alleles = genotype['chromosomes'][ch['id']]
        closed(alleles, ch['loci'], ch['id'])
        for lid, value in alleles.items():
            number(value, c['loci'][lid])
    return c


def baseline():
    c = contract()
    return dict(schema='nasuraya.genotype', version=VERSION, contract_sha256=digest(c),
                revision=0, parent_sha256=None,
                chromosomes={ch['id']: {lid: c['loci'][lid]['default'] for lid in ch['loci']}
                             for ch in c['chromosomes']})


def express(genotype):
    c = validate_genotype(genotype)
    phenotype, contact = body_sources()
    scale = phenotype['adult_scale']
    copies = {ch['id']: genotype['chromosomes'][ch['id']][ch['pair'] + '.L000']
              for ch in c['chromosomes']}
    values = {spec['name']: sum(genotype['chromosomes'][spec['pair'] + h][lid]
                               for h in ('A', 'B')) / 2.
              for lid, spec in TRAITS.items()}
    # A coupling constraint on proposed proportions, not a foot-contact simulation.
    if abs(values['foot_length_scale'] - values['foot_width_scale']) > .010000000001:
        raise ValueError('coupled foot scales differ by more than 0.01')
    proposed = dict(foot_length_cm=scale['feet']['length_cm'] * values['foot_length_scale'],
                    foot_width_cm=scale['feet']['spread_width_cm'] * values['foot_width_scale'],
                    tail_length_cm=contact['tail_length_m'] * 100 * values['tail_length_scale'])
    native = dict(height_excluding_horns_cm=scale['ground_to_crown_cm'],
                  mass_kg=contact['mass_kg'], leg_lengths_m=contact['leg_lengths_m'],
                  foot_length_cm=scale['feet']['length_cm'],
                  foot_width_cm=scale['feet']['spread_width_cm'],
                  tail_length_cm=contact['tail_length_m'] * 100,
                  loaded_contact_area_each_cm2=sum(p['area_m2'] for p in contact['patches']) * 1e4,
                  external_contact_design_each_cm2=scale['feet']['contact_area_each_cm2'],
                  pressure_ceiling_kpa=contact['pressure_ceiling_kpa'])
    structural_changed = any(proposed[key] != native[key] for key in proposed)
    dosage_changed = any(n != 1 for n in copies.values())
    return dict(schema='nasuraya.phenotype.proposal', version=VERSION,
                genotype_sha256=digest(genotype), policy_sha256=digest(c['policy']),
                native_baseline=native, structural_proposal=proposed,
                appearance_proposal={'foot_fur_length_mm': values['foot_fur_length_mm'],
                                     'status': 'authored render metadata; no mesh or image changed'},
                simulated_physiology_proxy=audit(load_design(), copies),
                learned_layer=deepcopy(c['learned_layer']),
                identity_and_face=deepcopy(c['policy']),
                compatibility={'shape_contract_valid': True,
                               'structural_changed': structural_changed,
                               'copy_deviation': dosage_changed,
                               'requires_independent_physics_tests': structural_changed,
                               'requires_dosage_review': dosage_changed,
                               'native_apply_allowed': False,
                               'validated_physical_improvement': False})


def mutate(genotype, edits, *, expected_revision):
    """Atomic batch in memory: either a fully valid new proposal or no change."""
    c = validate_genotype(genotype)
    if type(expected_revision) is not int or expected_revision != genotype['revision']:
        raise ValueError('stale genome revision')
    if type(edits) is not list or not edits:
        raise ValueError('nonempty edit list required')
    candidate = deepcopy(genotype)
    seen = set()
    for edit in edits:
        closed(edit, ('chromosome', 'locus', 'value'), 'edit')
        cid, lid = edit['chromosome'], edit['locus']
        if type(cid) is not str or type(lid) is not str:
            raise ValueError('chromosome and locus must be strings')
        if cid not in candidate['chromosomes'] or lid not in candidate['chromosomes'][cid]:
            raise ValueError('unknown or protected locus')
        if (cid, lid) in seen:
            raise ValueError('duplicate edit')
        seen.add((cid, lid))
        number(edit['value'], c['loci'][lid])
        candidate['chromosomes'][cid][lid] = edit['value']
    candidate['revision'] += 1
    candidate['parent_sha256'] = digest(genotype)
    express(candidate)  # Includes cross-locus compatibility before returning.
    return candidate


def checkpoint(genotype):
    payload = dict(schema='nasuraya.genome.checkpoint', version=VERSION,
                   genotype=deepcopy(genotype), phenotype=express(genotype))
    return dict(payload=payload, sha256=digest(payload))


def restore(saved):
    closed(saved, ('payload', 'sha256'), 'checkpoint')
    p = saved['payload']
    closed(p, ('schema', 'version', 'genotype', 'phenotype'), 'payload')
    if saved['sha256'] != digest(p) or saved != checkpoint(p['genotype']):
        raise ValueError('checkpoint mismatch: checksum, source, policy or expression')
    return deepcopy(p['genotype'])


def save(path, genotype):
    """Atomic checkpoint replacement; no native state path is supplied by this API."""
    payload = checkpoint(genotype)
    path = Path(path)
    # Restrict writes to new/non-runtime destinations, including symlink targets.
    if path.resolve().is_relative_to(BODY.resolve()):
        raise ValueError('native runtime destinations are forbidden')
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.genome-', delete=False) as handle:
            name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def demo():
    original = baseline()
    edits = [dict(chromosome='P07' + h, locus=lid, value=1.02)
             for h in ('A', 'B') for lid in ('P07.L010', 'P07.L011')]
    edits += [dict(chromosome='P09' + h, locus='P09.L010', value=1.02) for h in ('A', 'B')]
    edits += [dict(chromosome='P08A', locus='P08.L010', value=5.)]
    changed = mutate(original, edits, expected_revision=0)
    restored = restore(json.loads(json.dumps(checkpoint(changed))))
    return dict(schema='nasuraya.genome.demo', version=VERSION,
                chromosome_count=48, pair_count=24, baseline=express(original),
                edits=edits, changed=express(changed),
                cold_json_restore_equal=changed == restored,
                native_body_advanced=False, API_calls=0)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(demo(), ensure_ascii=False, indent=2) + '\n')
