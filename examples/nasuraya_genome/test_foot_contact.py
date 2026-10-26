from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .chromosomes import digest
from .foot_contact import build_mesh, check_mesh, compile_foot, disjoint, integrate, validate_plan
from .foot_trial import evaluate, scaled_genotype
from .physics_trial import compile_candidate
from .traits import baseline, body_sources, mutate


class FootGeometryTests(unittest.TestCase):
    def test_independent_triangle_area_centroid_and_separation_fixtures(self):
        area, centre = integrate(dict(vertices_m=[[0.,0.,0.], [1.,0.,0.], [0.,1.,0.]], triangles=[[0,1,2]]))
        self.assertEqual(area, .5)
        self.assertAlmostEqual(centre[0], 1/3)
        self.assertAlmostEqual(centre[1], 1/3)
        square = [[0.,0.], [1.,0.], [1.,1.], [0.,1.]]
        self.assertTrue(disjoint(square, [[x+2,y] for x,y in square]))
        self.assertFalse(disjoint(square, [[x+.5,y] for x,y in square]))

    def test_mesh_preserves_native_centres_areas_and_contact_identities(self):
        _, design = body_sources()
        mesh = build_mesh()
        report = check_mesh(mesh)
        self.assertEqual((report['patches'], report['toes'], report['triangles']), (4,3,1024))
        self.assertTrue(report['inside_envelope'])
        self.assertTrue(report['nonoverlapping'])
        self.assertFalse(report['anatomical_validation'])
        self.assertAlmostEqual(report['analytic_area_each_foot_cm2'], 392.66515249806537)
        self.assertLess(report['maximum_relative_area_error'], .000101)
        for patch, row in zip(mesh['patches'], design['patches']):
            self.assertEqual(patch['centre_m'][:2], row['xy'])
            self.assertEqual(patch['analytic_area_m2'], row['area_m2'])

    def test_refinement_converges_and_affine_jacobian_matches_independent_mesh_area(self):
        errors = [check_mesh(build_mesh(segments=n))['maximum_relative_area_error'] for n in (64,128,256)]
        self.assertLess(errors[1], errors[0]/3.9)
        self.assertLess(errors[2], errors[1]/3.9)
        base, scaled = check_mesh(build_mesh()), check_mesh(build_mesh(1.02,1.02))
        self.assertAlmostEqual(scaled['integrated_area_each_foot_cm2'] / base['integrated_area_each_foot_cm2'],
                               1.0404, places=12)
        self.assertAlmostEqual(scaled['analytic_area_each_foot_cm2'], 408.52882465898716)

    def test_inverted_nonfinite_overlapping_outside_and_fake_contacts_rejected(self):
        source = build_mesh()
        for fault in ('inverted','nonfinite','overlap','outside','extra_toe','heel'):
            mesh = deepcopy(source)
            if fault == 'inverted':
                mesh['patches'][0]['triangles'][0] = [0,2,1]
            elif fault == 'nonfinite':
                mesh['patches'][0]['vertices_m'][1][0] = float('nan')
            elif fault == 'overlap':
                mesh['patches'][3] = dict(deepcopy(mesh['patches'][1]), id='toe_3')
            elif fault == 'outside':
                mesh['envelope_m']['width'] = .01
            elif fault == 'extra_toe':
                mesh['toe_count'] = 4
            else:
                mesh['heel_contact'] = True
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                check_mesh(mesh)

    def test_plans_reject_fixture_or_mesh_tampering_and_hold_other_body_parameters(self):
        g = scaled_genotype()
        before = digest(g)
        plan = compile_foot(g)
        validate_plan(plan)
        _, native = body_sources()
        for key in set(native) - {'patches'}:
            self.assertEqual(plan['design'][key], native[key])
        for field in ('pressure', 'mesh', 'permission'):
            bad = deepcopy(plan)
            if field == 'pressure':
                bad['design']['pressure_ceiling_kpa'] = 999
                bad['design_sha256'] = digest(bad['design'])
            elif field == 'mesh':
                bad['mesh']['patches'][0]['vertices_m'][1][0] += .001
                bad['mesh_sha256'] = digest(bad['mesh'])
            else:
                bad['native_apply_allowed'] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_plan(bad)
        self.assertEqual(digest(g), before)
        self.assertEqual(compile_candidate(g)['status'], 'blocked')  # Original live-application gate stays closed.

    def test_modes_isolate_area_centres_and_descriptor_without_implicit_changes(self):
        g = scaled_genotype()
        _, native = body_sources()
        self.assertEqual(compile_foot(g,'descriptor_only')['design'], native)
        for mode in ('area_only','centres_only'):
            for a, b in zip(compile_foot(g,mode)['design']['patches'], native['patches']):
                self.assertEqual(a['xy'] == b['xy'], mode == 'area_only')
                self.assertEqual(a['area_m2'] == b['area_m2'], mode == 'centres_only')
        dosage = mutate(baseline(), [dict(chromosome='P08A',locus='P08.L000',value=0)], expected_revision=0)
        with self.assertRaises(ValueError):
            compile_foot(dosage)


class FootTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / 'experiment'
        cls.result = evaluate(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def static(self, name, case):
        return next(s for s in self.result['results'][name]['static'] if s['case'] == case)

    def test_nominal_pressure_matches_inverse_area_and_centres_alone_do_not_reduce_it(self):
        def peak(name):
            return max(self.static(name,'nominal_single_support')['pressures_kpa'].values())
        self.assertAlmostEqual(peak('baseline'), 178.28342715336777, places=8)
        self.assertAlmostEqual(peak('affine') / peak('baseline'), 1/1.0404, places=12)
        self.assertAlmostEqual(peak('area_only'), peak('affine'), places=9)
        self.assertAlmostEqual(peak('centres_only'), peak('baseline'), places=9)

    def test_controls_force_balance_limits_and_cold_restoration(self):
        self.assertTrue(all(self.result['checks'].values()))
        self.assertTrue(self.result['candidate_reduced_model_passed'])
        for name, data in self.result['results'].items():
            self.assertFalse(self.static(name,'over_capacity_negative_control')['feasible'])
            for case in data['dynamic']:
                if case['case'] == 'zero_friction':
                    self.assertEqual(case['failure'], 'friction_limit_exceeded')
                else:
                    self.assertTrue(case['valid_throughout'])
                    self.assertTrue(case['cold_restore_exercised'])
                    self.assertTrue(case['cold_restore_equal'])
        # Even the enlarged-pad hypothesis cannot achieve this forward CoP request.
        edge = self.static('affine','forward_edge_request')
        self.assertGreater(edge['target_error_m'], 0.)
        self.assertAlmostEqual(edge['achieved_cop_m'][1], .07123006789596782, places=10)

    def test_frozen_sources_result_counts_and_production_gate(self):
        frozen = json.loads((self.output/'frozen-plan.json').read_text())
        self.assertEqual(digest(frozen), self.result['frozen_plan_sha256'])
        self.assertEqual((self.result['dynamic_run_count'], self.result['static_query_count']), (20,15))
        self.assertAlmostEqual(self.result['primary_simulated_s'], 60.5)
        self.assertAlmostEqual(self.result['cold_replay_simulated_s'], 30.)
        self.assertFalse(self.result['native_apply_allowed'])
        self.assertFalse(self.result['true_anatomical_contact_validated'])
        self.assertTrue((self.output/'contact-comparison.svg').is_file())


if __name__ == '__main__':
    unittest.main()
