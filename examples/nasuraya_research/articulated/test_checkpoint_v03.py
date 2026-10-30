"""Real v03 command-boundary continuation and incompatible-body rejection."""
from copy import deepcopy
import json
import unittest
import numpy as np
from .canon_trial import CANDIDATE
from .checkpoint import (GEOMETRY_SCHEMA, restore_checkpoint, integration_state,
                         digest, model_digest)
from .evaluate import load
from .resize import SMALL
from .stepping import walk_trial


class GeometryCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = walk_trial(steps=1, model_dir=CANDIDATE, geometry_support=True,
                               checkpoint_v03=True, retain_checkpoint=True)
        if cls.first['checkpoint'] is None:
            raise AssertionError('first v03 step failed to settle: '+str(cls.first['failure']))
        # JSON is the actual process boundary representation, never a Python object cache.
        cls.cp = json.loads(json.dumps(cls.first['checkpoint'], allow_nan=False))
        cls.second = walk_trial(steps=1, model_dir=CANDIDATE, geometry_support=True,
                                checkpoint_v03=True, checkpoint=cls.cp)

    def setUp(self):
        self.checkpoint = deepcopy(self.cp)
        self.model, self.data = load(CANDIDATE)
        self.parameters = self.checkpoint['value']['parameters']
        self.model.opt.timestep = self.parameters['dt']
        self.model.geom_friction[:, 0] = self.parameters['friction']
        self.opts = dict(model_dir=CANDIDATE, geometry_support=True)

    def restore(self, cp=None, parameters=None):
        return restore_checkpoint(cp or self.checkpoint, self.model, self.data,
                                  parameters or self.parameters, **self.opts)

    def reject_unchanged(self, cp=None, parameters=None):
        before = integration_state(self.model, self.data).copy()
        with self.assertRaises(ValueError):
            self.restore(cp, parameters)
        np.testing.assert_array_equal(integration_state(self.model, self.data), before)

    def test_exact_body_and_controller_round_trip(self):
        c, feet, com, height, next_step, ticks = self.restore()
        p = self.cp['value']
        self.assertEqual(p['schema'], GEOMETRY_SCHEMA)
        np.testing.assert_array_equal(integration_state(self.model, self.data), p['integration'])
        np.testing.assert_array_equal(c.prev, p['controller']['prev'])
        np.testing.assert_array_equal(c.previous_solution, p['controller']['previous_solution'])
        np.testing.assert_array_equal(c.support_bounds, p['controller']['support_bounds'])
        np.testing.assert_array_equal(feet, p['feet'])
        np.testing.assert_array_equal(com, p['previous_com'])
        self.assertEqual(next_step, 1)

    def test_second_command_moves_opposite_foot_without_initialization(self):
        first, second = self.first, self.second
        self.assertTrue(first['walk_pass'])
        self.assertTrue(second['walk_pass'])
        self.assertIsNotNone(second['checkpoint'])
        self.assertEqual(first['steps'][0]['swing_side'], 0)
        self.assertEqual(second['steps'][0]['swing_side'], 1)
        self.assertEqual(second['initialization_seconds'], 0.)
        self.assertEqual(second['start_time'], first['end_time'])
        self.assertEqual(second['initial_qpos'], first['final_qpos'])
        self.assertEqual(second['initial_qvel'], first['final_qvel'])
        self.assertEqual(second['initial_integration_sha256'], digest(self.cp['value']['integration']))
        self.assertEqual(second['continued_from'], self.cp['sha256'])
        self.assertEqual(second['checkpoint']['value']['next_step'], 2)
        self.assertGreater(second['mean_foot_forward_displacement_m'], 0.)
        self.assertLess(second['final_max_generalized_speed'], .05)

    def test_bounds_cannot_be_widened_even_with_recomputed_hash(self):
        self.checkpoint['value']['controller']['support_bounds'][0][0] -= .01
        self.checkpoint['sha256'] = digest(self.checkpoint['value'])
        self.reject_unchanged()

    def test_model_physics_change_is_rejected(self):
        self.model.body_mass[1] += .1
        self.reject_unchanged()

    def test_v02_and_v03_are_not_interchangeable(self):
        model, data = load(SMALL)
        before = integration_state(model, data).copy()
        with self.assertRaises(ValueError):
            restore_checkpoint(self.cp, model, data, self.parameters)
        np.testing.assert_array_equal(integration_state(model, data), before)
        self.checkpoint['value']['schema'] = 'nasuraya-articulated-checkpoint/1'
        self.checkpoint['sha256'] = digest(self.checkpoint['value'])
        self.reject_unchanged()

    def test_source_parameter_shape_and_nonfinite_drift_rejected(self):
        for name, value in [('dt', .0005), ('com_bias_x_m', .006)]:
            self.reject_unchanged(parameters=dict(self.parameters, **{name:value}))
        cp = deepcopy(self.cp)
        cp['value']['integration'] = []
        cp['sha256'] = digest(cp['value'])
        self.reject_unchanged(cp)
        cp = deepcopy(self.cp)
        cp['value']['controller']['max_residual'] = float('nan')
        self.reject_unchanged(cp)
        cp = deepcopy(self.cp)
        cp['value']['contract']['source']['files']['support_geometry.py'] = 'changed'
        cp['sha256'] = digest(cp['value'])
        self.reject_unchanged(cp)

    def test_disagreeing_physics_metadata_rejected_before_mutation(self):
        self.checkpoint['value']['time'] += 1.
        self.checkpoint['sha256'] = digest(self.checkpoint['value'])
        self.reject_unchanged()

    def test_v03_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            walk_trial(steps=1, model_dir=CANDIDATE, geometry_support=True,
                       retain_checkpoint=True)
        with self.assertRaises(ValueError):
            walk_trial(steps=1, model_dir=SMALL, geometry_support=True,
                       checkpoint_v03=True, retain_checkpoint=True)


if __name__ == '__main__':
    unittest.main()
