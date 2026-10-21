from copy import deepcopy
import json
import unittest

from .chromosomes import audit, digest, evaluate, load_design, validate, verify


class ChromosomeTests(unittest.TestCase):
    def setUp(self):
        self.design = load_design()

    def test_complete_48_and_no_learned_overlay_inheritance(self):
        d = self.design
        self.assertEqual(len({c for p in d['pairs'] for c in p['chromosomes']}), 48)
        mapped = [m for d in d['domains'] for m in d['modules']]
        self.assertEqual(len(mapped), 22)
        self.assertNotIn('G22', mapped)
        self.assertNotIn('G23', mapped)

    def test_loss_is_reduced_capacity_without_silhouette_rewrite(self):
        initial = deepcopy(self.design)
        result = audit(self.design, {'P08A': 0})['payload']
        self.assertEqual(result['modules']['G04']['maintenance_ceiling'], .5)
        self.assertEqual(self.design, initial)
        self.assertEqual(self.design['phenotype_contract']['toes_per_foot'], 3)
        self.assertEqual(self.design['phenotype_contract']['fingers_per_hand'], 5)

    def test_duplicate_has_no_amplification_and_reports_deviation(self):
        base = audit(self.design)['payload']
        result = audit(self.design, {'P08A': 4})['payload']
        self.assertEqual(base['modules'], result['modules'])
        self.assertTrue(result['pairs']['P08']['copy_deviation'])

    def test_compensated_total_still_records_missing_homolog(self):
        result = audit(self.design, {'P08A': 2, 'P08B': 0})['payload']
        self.assertEqual(result['pairs']['P08']['raw_copies'], 2)
        self.assertTrue(result['pairs']['P08']['copy_deviation'])
        self.assertEqual(result['pairs']['P08']['homolog_counts']['P08B'], 0)

    def test_all_copies_missing_has_no_capacity(self):
        copies = {c: 0 for p in self.design['pairs'] for c in p['chromosomes']}
        result = audit(self.design, copies)['payload']
        self.assertTrue(all(v['development_capacity'] == 0 and v['maintenance_ceiling'] == 0
                            for v in result['modules'].values()))

    def test_lost_foundation_blocks_development_not_adult_maintenance(self):
        result = audit(self.design, {'P01A': 0, 'P01B': 0})['payload']
        self.assertEqual(result['modules']['G21']['development_capacity'], 0)
        self.assertEqual(result['modules']['G21']['maintenance_ceiling'], 1)
        self.assertFalse(result['action_permission_granted'])

    def test_boundary_is_local_for_maintenance_and_transitive_for_development(self):
        result = audit(self.design, boundary_faults=['C07'])['payload']
        self.assertEqual(result['modules']['G07']['maintenance_ceiling'], 0)
        self.assertEqual(result['modules']['G04']['development_capacity'], 0)
        self.assertEqual(result['modules']['G04']['maintenance_ceiling'], 1)
        self.assertEqual(result['modules']['G00']['development_capacity'], 1)

    def test_phase_never_erases_existing_adult_expression(self):
        result = audit(self.design, phase='S0')['payload']
        self.assertEqual(result['modules']['G17']['development_capacity'], 0)
        self.assertEqual(result['modules']['G17']['maintenance_ceiling'], 1)

    def test_external_converter_stays_disabled_at_s4_with_extra_copies(self):
        result = audit(self.design, {'P23A': 4, 'P24A': 4}, phase='S4')['payload']
        self.assertEqual(result['modules']['G12']['development_capacity'], 0)
        self.assertEqual(result['modules']['G12']['maintenance_ceiling'], 0)

    def test_invalid_copy_evidence_rejected_without_mutation(self):
        before = digest(self.design)
        for value in [True, -1, .5, float('nan'), 5, '1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit(self.design, {'P01A': value})
        with self.assertRaises(ValueError):
            audit(self.design, {'P99A': 0})
        self.assertEqual(digest(self.design), before)

    def test_ambiguous_boundaries_rejected(self):
        for faults in [['C01', 'C01'], ['C99']]:
            with self.assertRaises(ValueError):
                audit(self.design, boundary_faults=faults)

    def test_duplicate_or_omitted_coverage_rejected(self):
        self.design['domains'][0]['modules'].append('G01')
        with self.assertRaises(ValueError):
            validate(self.design)

    def test_dependency_cycle_or_missing_module_rejected(self):
        for dependency in ['G21', 'G99', 'G22']:
            changed = deepcopy(self.design)
            changed['modules'][0]['needs'] = [dependency]
            with self.assertRaises(ValueError):
                validate(changed)

    def test_pair_identity_conflict_rejected(self):
        self.design['pairs'][0]['chromosomes'] = ['P01A', 'P01A']
        with self.assertRaises(ValueError):
            validate(self.design)

    def test_saved_result_revalidated_not_just_checksum(self):
        saved = json.loads(json.dumps(audit(self.design, {'P02B': 0})))
        self.assertEqual(verify(saved, self.design), saved)
        saved['payload']['modules']['G21']['development_capacity'] = 1
        saved['sha256'] = digest(saved['payload'])
        with self.assertRaises(ValueError):
            verify(saved, self.design)

    def test_declared_survey_covers_every_slot_and_domain(self):
        result = evaluate()
        self.assertEqual(result['case_count'], 48)
        self.assertEqual(len(result['boundary_fault_cases']), 12)
        self.assertEqual(len(result['extra_copy_cases']), 48)
        self.assertEqual(result['total_conditions'], 114)
        self.assertTrue(result['source_unchanged'])


if __name__ == '__main__':
    unittest.main()
