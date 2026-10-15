from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .chromosomes import digest
from .traits import (BODY, HERE, ROOT, baseline, build_contract, build_schema,
                     body_sources, checkpoint, contract, demo, express, mutate, restore, save,
                     validate_genotype)


def edit(cid, lid, value):
    return dict(chromosome=cid, locus=lid, value=value)


class TraitTests(unittest.TestCase):
    def test_all_48_have_stable_ids_typed_loci_and_module_links(self):
        c = contract()
        self.assertEqual(c, build_contract())
        self.assertEqual(len(c['chromosomes']), 48)
        self.assertEqual(len({ch['id'] for ch in c['chromosomes']}), 48)
        for ch in c['chromosomes']:
            self.assertEqual(ch['id'], ch['pair'] + ch['homolog'])
            self.assertTrue(ch['modules'])
            self.assertIn(ch['pair'] + '.L000', ch['loci'])
            for lid in ch['loci']:
                spec = c['loci'][lid]
                self.assertEqual(spec['pair'], ch['pair'])
                self.assertIn('expression', spec)
        self.assertEqual(json.loads((HERE / 'genotype-v0.1.schema.json').read_text()), build_schema(c))
        self.assertEqual(json.loads((HERE / 'baseline-v0.1.json').read_text()), baseline())

    def test_baseline_provenance_units_and_contact_area_distinction(self):
        p = express(baseline())
        n = p['native_baseline']
        self.assertEqual((n['height_excluding_horns_cm'], n['mass_kg']), (250, 195))
        self.assertAlmostEqual(n['loaded_contact_area_each_cm2'], 392.66515249806537)
        self.assertEqual(n['external_contact_design_each_cm2'], 450)
        self.assertEqual(p['structural_proposal']['tail_length_cm'], 120)
        self.assertFalse(p['compatibility']['structural_changed'])
        self.assertFalse(p['compatibility']['native_apply_allowed'])

    def test_heterozygous_mean_and_coordinated_homozygous_expression(self):
        g = baseline()
        one = mutate(g, [edit('P07A', 'P07.L010', 1.02)], expected_revision=0)
        self.assertAlmostEqual(express(one)['structural_proposal']['foot_length_cm'], 52.52)
        two = mutate(g, [edit('P07' + h, lid, 1.02) for h in 'AB'
                         for lid in ('P07.L010', 'P07.L011')], expected_revision=0)
        p = express(two)
        self.assertAlmostEqual(p['structural_proposal']['foot_length_cm'], 53.04)
        self.assertAlmostEqual(p['structural_proposal']['foot_width_cm'], 26.52)
        self.assertTrue(p['compatibility']['requires_independent_physics_tests'])
        self.assertEqual(g, baseline())

    def test_cosmetic_expression_does_not_change_structure_or_capacity(self):
        g = baseline()
        b = express(g)
        changed = mutate(g, [edit('P08A', 'P08.L010', 5.)], expected_revision=0)
        p = express(changed)
        self.assertEqual(p['appearance_proposal']['foot_fur_length_mm'], 4)
        for key in ('native_baseline', 'structural_proposal', 'simulated_physiology_proxy',
                    'identity_and_face', 'learned_layer'):
            self.assertEqual(p[key], b[key])

    def test_dosage_changes_capacity_but_never_rewrites_adult_dimensions(self):
        g = mutate(baseline(), [edit('P08A', 'P08.L000', 0)], expected_revision=0)
        p = express(g)
        self.assertEqual(p['simulated_physiology_proxy']['payload']['modules']['G04']['maintenance_ceiling'], .5)
        self.assertTrue(p['compatibility']['requires_dosage_review'])
        self.assertEqual(p['structural_proposal'], express(baseline())['structural_proposal'])
        self.assertFalse(p['compatibility']['native_apply_allowed'])

    def test_unknown_face_identity_learning_or_force_loci_are_rejected(self):
        g = baseline()
        for lid in ('face.width', 'identity.origin', 'learning.G22', 'force_limit', 'P09.L010'):
            with self.subTest(lid=lid), self.assertRaises(ValueError):
                mutate(g, [edit('P07A', lid, 1)], expected_revision=0)
        for key in ('identity', 'learned_state', 'appearance', 'native_apply_allowed'):
            bad = deepcopy(g)
            bad[key] = 'injected'
            with self.assertRaises(ValueError):
                validate_genotype(bad)
        self.assertEqual(g, baseline())

    def test_bounds_nonfinite_types_and_cross_locus_rejection_are_atomic(self):
        g = baseline()
        before = digest(g)
        for value in (True, None, '1', float('nan'), float('inf'), 10**1000, .5, 1.03, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mutate(g, [edit('P07A', 'P07.L010', value)], expected_revision=0)
        with self.assertRaises(ValueError):
            mutate(g, [edit('P07A', 'P07.L010', 1.02),
                       edit('P07B', 'P07.L010', 1.02)], expected_revision=0)
        with self.assertRaises(ValueError):
            mutate(g, [edit('P07A', 'P07.L010', 1.01),
                       edit('P08A', 'P08.L000', .5)], expected_revision=0)
        self.assertEqual(digest(g), before)

    def test_stale_revisions_duplicate_edits_and_bad_chromosome_sets(self):
        g = baseline()
        for revision in (True, 1, -1, '0'):
            with self.assertRaises(ValueError):
                mutate(g, [edit('P09A', 'P09.L010', 1.01)], expected_revision=revision)
        with self.assertRaises(ValueError):
            mutate(g, [edit('P09A', 'P09.L010', 1.01)] * 2, expected_revision=0)
        for change in ('missing', 'extra', 'wrong_pair', 'bad_parent', 'wrong_version', 'contract'):
            bad = deepcopy(g)
            if change == 'missing':
                del bad['chromosomes']['P01A']
            elif change == 'extra':
                bad['chromosomes']['P25A'] = {}
            elif change == 'wrong_pair':
                bad['chromosomes']['P07A']['P09.L010'] = 1
            elif change == 'bad_parent':
                bad['parent_sha256'] = 'a' * 64
            elif change == 'wrong_version':
                bad['version'] = '0.2.0'
            else:
                bad['contract_sha256'] = '0' * 64
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_genotype(bad)

    def test_restore_recomputes_traits_policy_and_capacity_after_checksum(self):
        state = mutate(baseline(), [edit('P09A', 'P09.L010', 1.02)], expected_revision=0)
        saved = checkpoint(state)
        self.assertEqual(restore(json.loads(json.dumps(saved))), state)
        self.assertEqual(state['parent_sha256'], digest(baseline()))
        for target in ('structural', 'policy', 'permission', 'capacity'):
            bad = deepcopy(saved)
            p = bad['payload']['phenotype']
            if target == 'structural':
                p['structural_proposal']['foot_length_cm'] = 1
            elif target == 'policy':
                p['identity_and_face']['narrative_roots'] = ['changed']
            elif target == 'permission':
                p['compatibility']['native_apply_allowed'] = True
            else:
                p['simulated_physiology_proxy']['payload']['modules']['G12']['maintenance_ceiling'] = 1
            bad['sha256'] = digest(bad['payload'])
            with self.subTest(target=target), self.assertRaises(ValueError):
                restore(bad)
        bad = deepcopy(saved)
        bad['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            restore(bad)

    def test_file_checkpoint_survives_fresh_process(self):
        state = mutate(baseline(), [edit('P08A', 'P08.L010', 5.)], expected_revision=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            save(path, state)
            code = ('import json,sys; from examples.nasuraya_genome.traits import restore; '
                    'from examples.nasuraya_genome.chromosomes import digest; '
                    'print(digest(restore(json.load(open(sys.argv[1])))))')
            result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=ROOT,
                                    check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), digest(state))
            save(path, baseline())
            self.assertEqual(restore(json.loads(path.read_text())), baseline())
            self.assertEqual([p.name for p in path.parent.iterdir()], ['state.json'])
        with self.assertRaises(ValueError):
            save(BODY / 'forbidden-test.json', state)

    def test_source_drift_rejects_restore_instead_of_silently_rebasing(self):
        saved = checkpoint(baseline())
        phenotype, contact = body_sources()
        contact['mass_kg'] += 1
        with patch('examples.nasuraya_genome.traits.body_sources', return_value=(phenotype, contact)):
            with self.assertRaisesRegex(ValueError, 'drift'):
                restore(saved)

    def test_native_source_hashes_and_paired_trajectories_unchanged(self):
        # Fresh synthetic PostureLoop, no original practice/API ledger is loaded.
        before = {str(p): p.read_bytes() for p in BODY.rglob('*') if p.is_file()
                  and '__pycache__' not in str(p)}
        sys.path.insert(0, str(BODY))
        from examples.nasuraya_body_loop.__main__ import verified_sources
        self.assertEqual(len(verified_sources()), 70)
        import unified_body_v2  # Native bootstrap supplies retained runtime import paths.
        from posture_step import GaitEnvironment, Inputs, PostureLoop
        source = PostureLoop()
        checkpoint_before = source.checkpoint()
        other = deepcopy(source)
        express(mutate(baseline(), [edit('P08A', 'P08.L010', 5.)], expected_revision=0))
        for _ in range(10):
            a = source.step(GaitEnvironment(command='stand', body=Inputs(dt_s=.1)))
            b = other.step(GaitEnvironment(command='stand', body=Inputs(dt_s=.1)))
            self.assertEqual(a, b)
            self.assertTrue(a['balance']['model_valid'])
        self.assertEqual(source.checkpoint(), other.checkpoint())
        self.assertNotEqual(source.checkpoint(), checkpoint_before)
        self.assertEqual(before, {str(p): p.read_bytes() for p in BODY.rglob('*') if p.is_file()
                                 and '__pycache__' not in str(p)})

    def test_demo_is_reproducible_and_explicitly_gated(self):
        d = demo()
        self.assertEqual(d, demo())
        self.assertEqual((d['chromosome_count'], d['pair_count']), (48, 24))
        self.assertTrue(d['cold_json_restore_equal'])
        self.assertFalse(d['native_body_advanced'])
        self.assertFalse(d['changed']['compatibility']['native_apply_allowed'])
        self.assertEqual(d['baseline']['identity_and_face'], d['changed']['identity_and_face'])


if __name__ == '__main__':
    unittest.main()
