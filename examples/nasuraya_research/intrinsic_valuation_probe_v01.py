#!/usr/bin/env python3
"""Tadash motivational valuation v0.1: deterministic synthetic research fixture.

Contextual software learning from changes in declared internal state, with
no human approval reward. Not evidence of pleasure, orgasm, or consciousness.
No body calls, model calls, network, real sensors, or background execution.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass

ACTIONS = ('rest', 'verify', 'explore')
CONTEXTS = {
    'depleted': (.15, .45, .35),
    'uncertain': (.72, .24, .87),
    'overloaded': (.48, .91, .42),
    'curious': (.82, .14, .64),
}
# Synthetic delta energy, load, uncertainty, information gain by context/action.
EFFECTS = {
    'depleted': {
        'rest': (+.34, -.16, -.04, .01), 'verify': (-.11, +.02, -.29, .11),
        'explore': (-.24, +.14, -.18, .28)},
    'uncertain': {
        'rest': (+.09, -.13, -.05, .01), 'verify': (-.08, +.01, -.54, .19),
        'explore': (-.17, +.15, -.31, .23)},
    'overloaded': {
        'rest': (+.20, -.43, -.04, .01), 'verify': (-.12, +.12, -.21, .12),
        'explore': (-.21, +.22, -.24, .24)},
    'curious': {
        'rest': (+.07, -.11, -.04, .01), 'verify': (-.07, +.02, -.27, .13),
        'explore': (-.10, +.06, -.48, .49)},
}


def clamp(v: float) -> float:
    return min(1., max(0., v))


def utility(before: tuple[float, float, float],
            after: tuple[float, float, float], information: float) -> float:
    """Designer-specified valuation proxy, never a claim of felt experience."""
    e0, l0, u0 = before
    e1, l1, u1 = after
    return round(.8*(e1-e0) - .9*(l1-l0) - .7*(u1-u0) + .5*information, 6)


def outcome(context: str, action: str, noise: tuple[float, float, float]) -> dict:
    if context not in CONTEXTS or action not in ACTIONS:
        raise ValueError('unknown synthetic state or action')
    if len(noise) != 3 or any(abs(x) > .02 for x in noise):
        raise ValueError('noise outside prespecified envelope')
    before = CONTEXTS[context]
    effect = EFFECTS[context][action]
    after = tuple(clamp(before[i] + effect[i] + noise[i]) for i in range(3))
    info = effect[3]
    return dict(context=context, action=action, before=before, after=after,
                information_gain=info, intrinsic_utility_proxy=utility(before, after, info),
                provenance='synthetic_fixture')


@dataclass
class Learner:
    q: dict
    counts: dict

    @classmethod
    def blank(cls) -> 'Learner':
        return cls({c: {a: 0. for a in ACTIONS} for c in CONTEXTS},
                   {c: {a: 0 for a in ACTIONS} for c in CONTEXTS})

    def choose(self, context: str, rng: random.Random, epsilon: float = 0.) -> str:
        if not 0. <= epsilon <= 1.:
            raise ValueError('epsilon outside range')
        if rng.random() < epsilon:
            return rng.choice(ACTIONS)
        return max(ACTIONS, key=lambda a: (self.q[context][a], -ACTIONS.index(a)))

    def learn(self, context: str, action: str, observed_utility: float) -> None:
        n = self.counts[context][action] + 1
        self.counts[context][action] = n
        old = self.q[context][action]
        self.q[context][action] = old + (observed_utility - old)/n


def episodes(seed: int, n: int) -> list[tuple[str, tuple[float, float, float]]]:
    rng = random.Random(seed)
    contexts = tuple(CONTEXTS)
    return [(contexts[i % len(contexts)],
             tuple(rng.uniform(-.02, .02) for _ in range(3))) for i in range(n)]


def evaluate(seed: int = 20261108, train_n: int = 320, test_n: int = 160) -> dict:
    if train_n < 1 or test_n < 4:
        raise ValueError('positive trial counts required')
    rng = random.Random(seed)
    learner = Learner.blank()
    for ctx, noise in episodes(seed+1, train_n):
        action = learner.choose(ctx, rng, epsilon=.22)
        result = outcome(ctx, action, noise)
        learner.learn(ctx, action, result['intrinsic_utility_proxy'])

    heldout = episodes(seed+2, test_n)
    random_policy = random.Random(seed+3)
    policies = {'learned': [], 'random': [], 'fixed_rest': [], 'oracle_ceiling': []}
    choices = {c: learner.choose(c, random.Random(0)) for c in CONTEXTS}
    for ctx, noise in heldout:
        acts = {
            'learned': choices[ctx],
            'random': random_policy.choice(ACTIONS),
            'fixed_rest': 'rest',
            'oracle_ceiling': max(
                ACTIONS, key=lambda a: outcome(ctx, a, noise)['intrinsic_utility_proxy']),
        }
        for policy, action in acts.items():
            policies[policy].append(outcome(ctx, action, noise)['intrinsic_utility_proxy'])
    means = {k: round(sum(v)/len(v), 5) for k, v in policies.items()}
    return {
        'schema': 'tadash-intrinsic-valuation-proxy/0.1',
        'seed': seed, 'train_episodes': train_n, 'heldout_episodes': test_n,
        'learned_action_by_state': choices, 'training_counts': learner.counts,
        'heldout_mean_utility': means,
        'gain_over_random': round(means['learned']-means['random'], 5),
        'gain_over_fixed_rest': round(means['learned']-means['fixed_rest'], 5),
        'external_reward': False, 'observations': 'synthetic_only',
        'native_body_cycles': 0, 'subjective_experience_evidence': False,
        'interpretation': 'Behavioral valuation of engineered internal proxies only; not felt pleasure or self-awareness.',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=20261108)
    parser.add_argument('--train', type=int, default=320)
    parser.add_argument('--test', type=int, default=160)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.seed, args.train, args.test),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
