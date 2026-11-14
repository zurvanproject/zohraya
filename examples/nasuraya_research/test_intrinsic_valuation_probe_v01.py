"""Contract and ablation tests for synthetic Tadash intrinsic valuation."""
import random
import unittest

from .intrinsic_valuation_probe_v01 import (
    ACTIONS, CONTEXTS, Learner, evaluate, outcome, utility)


class TestIntrinsicValuation(unittest.TestCase):
    def test_zero_change_zero_information_has_no_intrinsic_value(self):
        state = (.5, .3, .2)
        self.assertEqual(utility(state, state, 0.), 0.)

    def test_only_simulated_internal_outcomes_have_value(self):
        trial = outcome('depleted', 'rest', (0., 0., 0.))
        self.assertGreater(trial['intrinsic_utility_proxy'], 0.)
        self.assertEqual(trial['provenance'], 'synthetic_fixture')
        self.assertNotIn('external_reward', trial)

    def test_state_specific_actions_learned(self):
        report = evaluate()
        self.assertEqual(report['learned_action_by_state'],
                         {'depleted': 'rest', 'uncertain': 'verify',
                          'overloaded': 'rest', 'curious': 'explore'})
        self.assertGreater(report['gain_over_random'], .15)
        self.assertGreater(report['gain_over_fixed_rest'], .05)
        self.assertEqual(report['heldout_mean_utility']['learned'],
                         report['heldout_mean_utility']['oracle_ceiling'])

    def test_learning_ablation_cannot_discover_context_specific_values(self):
        untrained = Learner.blank()
        self.assertEqual(set(untrained.q), set(CONTEXTS))
        self.assertTrue(all(value == 0. for row in untrained.q.values()
                            for value in row.values()))
        self.assertEqual(len(set(untrained.choose(c, random.Random(0))
                                 for c in CONTEXTS)), 1)

    def test_repeatable_and_bounded(self):
        self.assertEqual(evaluate(), evaluate())
        for context in CONTEXTS:
            for action in ACTIONS:
                row = outcome(context, action, (.02, -.02, 0.))
                self.assertTrue(all(0 <= v <= 1 for v in row['after']))
        with self.assertRaises(ValueError):
            outcome('unknown', 'rest', (0., 0., 0.))
        with self.assertRaises(ValueError):
            outcome('depleted', 'rest', (.5, 0., 0.))

    def test_report_declares_epistemic_limits(self):
        result = evaluate()
        self.assertIs(result['external_reward'], False)
        self.assertIs(result['subjective_experience_evidence'], False)
        self.assertEqual(result['observations'], 'synthetic_only')
        self.assertEqual(result['native_body_cycles'], 0)


if __name__ == '__main__':
    unittest.main()
