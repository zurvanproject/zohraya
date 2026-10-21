from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .chromosomes import digest
from .physics_trial import compile_candidate, evaluate, run_copy, tail_genotype, validate_plan
from .traits import baseline, body_sources, mutate


class CandidateTests(unittest.TestCase):
    def test_tail_closure_has_known_numeric_answers_and_no_other_parameter_changes(self):
        _, source = body_sources()
        before = deepcopy(source)
        for scale, length, inertia in ((.98, 1.176, 4.60992), (1., 1.2, 4.8), (1.02, 1.224, 4.99392)):
            plan = compile_candidate(tail_genotype(scale))
            self.assertEqual(plan['status'], 'sandbox_only')
            self.assertFalse(plan['native_apply_allowed'])
            self.assertAlmostEqual(plan['design']['tail_length_m'], length, places=12)
            self.assertAlmostEqual(plan['design']['tail_inertia_kg_m2'], inertia, places=12)
            for key in set(source) - {'tail_length_m', 'tail_inertia_kg_m2'}:
                self.assertEqual(plan['design'][key], source[key])
        self.assertEqual(source, before)

    def test_unmapped_foot_and_dosage_proposals_have_no_executable_design(self):
        changes = [dict(chromosome='P07' + h, locus=lid, value=1.02)
                   for h in 'AB' for lid in ('P07.L010', 'P07.L011')]
        for edits in (changes, [dict(chromosome='P08A', locus='P08.L000', value=0)]):
            plan = compile_candidate(mutate(baseline(), edits, expected_revision=0))
            self.assertEqual(plan['status'], 'blocked')
            self.assertNotIn('design', plan)
            with self.assertRaisesRegex(ValueError, 'blocked'):
                run_copy(plan, {})

    def test_cosmetic_only_candidate_is_the_exact_same_physical_fixture(self):
        g = mutate(baseline(), [dict(chromosome='P08A', locus='P08.L010', value=5.)], expected_revision=0)
        self.assertEqual(compile_candidate(g)['design'], compile_candidate(baseline())['design'])
        self.assertEqual(compile_candidate(g)['changes'], {})

    def test_sandbox_rechecks_allowlist_and_closure_before_copying(self):
        original = compile_candidate(tail_genotype(1.02))
        _, native = body_sources()
        for key, value in (('mass_kg', 190.), ('pressure_ceiling_kpa', 999.),
                           ('tail_inertia_kg_m2', 4.8), ('tail_length_m', 2.4)):
            plan = deepcopy(original)
            plan['design'][key] = value
            plan['sandbox_design_sha256'] = digest(plan['design'])
            plan['changes'] = {k: dict(before=native[k], after=v) for k, v in plan['design'].items()
                               if v != native[k]}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_plan(plan)


class SandboxIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / 'trial'
        cls.result = evaluate(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def case(self, variant, name):
        return next(c for c in self.result['results'][variant]['cases'] if c['case'] == name)

    def test_frozen_protocol_and_primary_vs_cold_replay_accounting(self):
        frozen = json.loads((self.output / 'frozen-plan.json').read_text())
        self.assertEqual(digest(frozen), self.result['frozen_plan_sha256'])
        self.assertEqual(self.result['native_run_count'], 24)
        self.assertEqual(self.result['cold_restore_branches'], 20)
        self.assertAlmostEqual(self.result['simulated_s'], 80.4)
        self.assertAlmostEqual(self.result['cold_replay_simulated_s'], 40.)
        with self.assertRaises(FileExistsError):
            evaluate(self.output)

    def test_parameter_sensitivity_is_measured_but_tail_off_control_is_identical(self):
        observed = [self.case(n, 'tail_displacement')['physical_trace_sha256']
                    for n in ('tail_short', 'baseline', 'tail_long')]
        self.assertEqual(len(set(observed)), 3)
        off = [self.case(n, 'impulse_tail_off')['physical_trace_sha256']
               for n in ('tail_short', 'baseline', 'tail_long')]
        self.assertEqual(len(set(off)), 1)
        for a, b in zip(self.result['results']['baseline']['cases'],
                        self.result['results']['length_only_ablation']['cases']):
            self.assertEqual(a['physical_trace_sha256'], b['physical_trace_sha256'])
        # The frozen probe is a slowing motion: initial speed .2, torque -4.2.
        # At 0.1 seconds the known baseline angular speed is .1125 rad/s.
        self.assertAlmostEqual(self.case('baseline', 'tail_displacement')['first']['tail_speed'][0], .1125)
        self.assertAlmostEqual(self.case('tail_long', 'tail_displacement')['first']['tail_speed'][0],
                               .2 - .42 / 4.99392)
        self.assertFalse(self.result['demonstrated_physical_improvement'])

    def test_failures_limits_restoration_and_source_bound_checkpoint_rejection(self):
        self.assertTrue(all(self.result['checks'].values()))
        for name, result in self.result['results'].items():
            self.assertNotIn('reference_checkpoint', result)
            for case in result['cases']:
                self.assertEqual(case['failure'], 'friction_limit_exceeded' if case['case'] == 'zero_friction' else None)
                if case['case'] != 'zero_friction':
                    self.assertTrue(case['cold_restore_exercised'])
                    self.assertTrue(case['cold_restore_equal'])
            if name != 'baseline':
                self.assertTrue(result['foreign_checkpoint_rejected'])
        self.assertFalse(self.result['native_apply_allowed'])


if __name__ == '__main__':
    unittest.main()
