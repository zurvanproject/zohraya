"""Offline-only tests for fixed synthetic curiosity benchmark."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("experiment", HERE / "experiment.py")
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


class CuriosityTests(unittest.TestCase):
    def test_train_holdout_are_disjoint(self):
        self.assertFalse(set(e.CANDIDATES) & set(e.HOLDOUT))
        self.assertEqual(len(e.HOLDOUT), 16)

    def test_same_oracle_for_all_policies(self):
        for regime in e.REGIMES:
            for seed in (91000, 91001, 91013):
                a = e.make_oracle(seed, regime)
                b = e.make_oracle(seed, regime)
                self.assertEqual([a(x) for x in range(64)], [b(x) for x in range(64)])

    def test_posterior_updates_toward_true_answer(self):
        prior = [1 / len(e.HYPOTHESES)] * len(e.HYPOTHESES)
        self.assertAlmostEqual(e.prob_one(prior, 11), 0.5)
        posterior = e.update(prior, 11, 1)
        self.assertAlmostEqual(sum(posterior), 1)
        self.assertGreater(e.prob_one(posterior, 11), 0.95)

    def test_query_budgets_same_and_no_repeats(self):
        for arm in e.ARMS:
            result = e.run_one(91000, 'learnable_parity', arm)
            self.assertEqual(result['starting_sample'], 0)
            self.assertEqual(len(result['queries']), max(e.BUDGETS))
            self.assertEqual(len(set(result['queries'])), max(e.BUDGETS))
            self.assertTrue(set(result['queries']).issubset(e.CANDIDATES))
            self.assertFalse(set(result['queries']) & set(e.HOLDOUT))

    def test_heldout_not_in_query_choice_input(self):
        import inspect
        parameters = inspect.signature(e.choose).parameters
        self.assertNotIn('oracle', parameters)
        self.assertNotIn('holdout', parameters)

    def test_novelty_decreases_after_repeat_exposure(self):
        first = e.novelty(47, [0])
        later = e.novelty(47, [0, 47, 47])
        self.assertGreater(first, later)

    def test_reproducible_frozen_seed_results(self):
        self.assertEqual(e.run(5), e.run(5))

    def test_three_regimes_run_with_same_policies(self):
        x = e.run(2)
        for regime in e.REGIMES:
            self.assertEqual(set(x['regimes'][regime]['arms']), set(e.ARMS))
            for arm in e.ARMS:
                self.assertEqual(set(x['regimes'][regime]['arms'][arm]), {str(b) for b in e.BUDGETS})


if __name__ == '__main__':
    unittest.main()
