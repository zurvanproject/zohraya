"""Pre-registered negative control for Tadash intrinsic valuation v0.1.

30 deterministic paired seeds. Context-label corruption is only a synthetic
ablation; this test does not probe experienced pleasure or machine awareness.
"""
import random
import statistics
import unittest

from .intrinsic_valuation_probe_v01 import (
    ACTIONS, CONTEXTS, Learner, episodes, outcome, evaluate)


def train(seed, corrupt_context):
    learner = Learner.blank()
    choose_rng = random.Random(seed)
    corrupt_rng = random.Random(seed + 501)
    for actual_context, noise in episodes(seed + 1, 320):
        observed_context = (corrupt_rng.choice(tuple(CONTEXTS))
                            if corrupt_context else actual_context)
        action = learner.choose(observed_context, choose_rng, epsilon=.22)
        value = outcome(actual_context, action, noise)['intrinsic_utility_proxy']
        learner.learn(observed_context, action, value)
    return learner


def heldout_score(learner, seed):
    choices = {context: learner.choose(context, random.Random(0))
               for context in CONTEXTS}
    points = [outcome(context, choices[context], noise)['intrinsic_utility_proxy']
              for context, noise in episodes(seed + 2, 160)]
    return statistics.mean(points)


def paired_controls():
    results = []
    for seed in range(20261108, 20261138):
        normal = heldout_score(train(seed, False), seed)
        scrambled = heldout_score(train(seed, True), seed)
        prior = evaluate(seed=seed)['heldout_mean_utility']
        results.append(dict(seed=seed, learned=normal, shuffled=scrambled,
                            random=prior['random'], fixed_rest=prior['fixed_rest']))
    return results


class TestContextCorruption(unittest.TestCase):
    def test_context_matters_across_paired_seeds(self):
        trials = paired_controls()
        self.assertEqual(len(trials), 30)
        self.assertTrue(all(t['learned'] > t['shuffled'] for t in trials))
        self.assertTrue(all(t['learned'] > t['fixed_rest'] for t in trials))
        self.assertGreater(statistics.mean(t['learned'] for t in trials)
                           - statistics.mean(t['shuffled'] for t in trials), .10)


if __name__ == '__main__':
    unittest.main()
