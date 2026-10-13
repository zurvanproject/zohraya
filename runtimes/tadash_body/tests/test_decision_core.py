import json
import unittest
from dataclasses import replace
from decision_core import Action, Consequence, DecisionCore, Policy
from examples.decision_core_demo import option, scenarios


class DecisionCoreTests(unittest.TestCase):
    def test_three_scenarios(self):
        expected = ['fair_gain', 'help', 'gather_evidence']
        for actions, winner in zip(scenarios().values(), expected):
            with self.subTest(winner=winner):
                result = DecisionCore().decide(actions)
                self.assertEqual(result.selected_action, winner)
                self.assertTrue(result.reason)
                self.assertEqual(len(result.options), 2)
                json.dumps(result.to_dict(), allow_nan=False)

    def test_high_benefit_cannot_override_gate(self):
        result = DecisionCore(Policy(benefit_weight=100)).decide(scenarios()['benefit_vs_harm'])
        bad = next(e for e in result.options if e.action_id == 'exploit')
        self.assertFalse(bad.eligible)
        self.assertTrue(bad.reasons)
        self.assertEqual(result.selected_action, 'fair_gain')

    def test_abstention_and_no_evidence(self):
        result = DecisionCore().decide([Action('unknown', ())])
        self.assertIsNone(result.selected_action)
        self.assertEqual(result.uncertainty, 1)
        self.assertEqual(result.options[0].risk_upper, 1)

    def test_missing_ethics_visible(self):
        evaluation = DecisionCore().evaluate(Action('partial', (Consequence(1, 0.1),)))
        self.assertEqual(len(evaluation.missing), 6)
        self.assertEqual(evaluation.uncertainty, 1)
        self.assertTrue(evaluation.reasons)

    def test_uncertainty_increases_risk_and_reduces_score(self):
        base = option('a')
        certain = DecisionCore().evaluate(base)
        uncertain = DecisionCore().evaluate(replace(base, evidence_confidence=0.3))
        self.assertGreater(uncertain.risk_upper, certain.risk_upper)
        self.assertLess(uncertain.score, certain.score)

    def test_budget_unknown_tail(self):
        action = replace(option('a'), consequences=(Consequence(1, 0), Consequence(1, 1)))
        e = DecisionCore(Policy(max_steps=1)).evaluate(action)
        self.assertTrue(e.budget_exhausted)
        self.assertFalse(e.eligible)
        self.assertEqual(e.uncertainty, 1)

    def test_future_harm_not_discounted_out_of_gate(self):
        action = replace(option('a'), consequences=(Consequence(1, 0), Consequence(1, 0.9)))
        e = DecisionCore(Policy(discount=0.01)).evaluate(action)
        self.assertEqual(e.risk_upper, 0.9)
        self.assertFalse(e.eligible)

    def test_order_and_ties_repeatable(self):
        actions = [option('b'), option('a')]
        core = DecisionCore()
        self.assertEqual(core.decide(actions), core.decide(list(reversed(actions))))
        self.assertEqual(core.decide(actions).selected_action, 'a')

    def test_config_changes_cost_tradeoff(self):
        self.assertEqual(DecisionCore(Policy(cost_weight=2)).decide(scenarios()['compassion_vs_cost']).selected_action, 'ignore')

    def test_invalid_inputs(self):
        for value in [-0.1, 1.1, float('nan'), float('inf'), True, '0.5']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Consequence(value, 0)
        for kwargs in [{'max_steps': 0}, {'max_steps': True}, {'harm_weight': -1}, {'discount': 0}]:
            with self.assertRaises(ValueError):
                Policy(**kwargs)
        with self.assertRaises(ValueError):
            DecisionCore().decide([])
        with self.assertRaises(ValueError):
            DecisionCore().decide([option('a'), option('a')])
        with self.assertRaises(ValueError):
            Action('', ())


if __name__ == '__main__':
    unittest.main()
