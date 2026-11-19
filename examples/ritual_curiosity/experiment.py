#!/usr/bin/env python3
"""Bounded three-arm active-question learning experiment, standard library only.

Everything here is SYNTHETIC. Geometric bit attributes were inspired by
arrangements in a scanned manuscript, but no manuscript glyph has a known
label and we are NOT decoding the real text or testing consciousness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
from statistics import mean
from pathlib import Path

N_FEATURES = 6
HYPOTHESES = tuple((mask, bias) for mask in range(1 << N_FEATURES) for bias in (0, 1))
CANDIDATES = tuple(range(1, 48))
HOLDOUT = tuple(range(48, 64))  # Exact disjoint inputs for all arms
ARMS = ('answer_first', 'curiosity_only', 'curiosity_diversity')
REGIMES = ('learnable_parity', 'misspecified_nonlinear', 'unlearnable_random')
BUDGETS = (4, 8, 12)
N_SEEDS = 120
SEED_START = 91000


def parity_label(x: int, mask: int, bias: int) -> int:
    return ((x & mask).bit_count() & 1) ^ bias


def make_oracle(seed: int, regime: str):
    rng = random.Random(seed)
    mask = rng.randint(1, (1 << N_FEATURES) - 1)
    bias = rng.randrange(2)
    if regime == 'learnable_parity':
        return lambda x: parity_label(x, mask, bias)
    if regime == 'misspecified_nonlinear':
        return lambda x: parity_label(x, mask, bias) ^ int((x & 0b0011) == 0b0011 and (x & 0b1100) == 0b1100)
    if regime == 'unlearnable_random':
        table = [rng.randrange(2) for _ in range(64)]
        return lambda x: table[x]
    raise ValueError(regime)


def normalize(weights):
    total = sum(weights)
    if not (total > 0 and math.isfinite(total)):
        raise ValueError('Nonfinite posterior')
    return [w / total for w in weights]


def update(weights, x: int, truth: int):
    # Fixed measurement reliability assumption. No artificial answers are shown
    # to policies before they select a query.
    likelihood = (0.98 if parity_label(x, *h) == truth else 0.02 for h in HYPOTHESES)
    return normalize([w * p for w, p in zip(weights, likelihood)])


def prob_one(weights, x: int) -> float:
    return sum(w for w, h in zip(weights, HYPOTHESES) if parity_label(x, *h))


def uncertainty(weights, x: int) -> float:
    p = prob_one(weights, x)
    return 4 * p * (1 - p)


def novelty(x: int, queried: list[int]) -> float:
    # Reward a never/rarely observed value in each of six visible attributes.
    seen = [[0, 0] for _ in range(N_FEATURES)]
    for q in queried:
        for j in range(N_FEATURES):
            seen[j][(q >> j) & 1] += 1
    return sum(1 / (1 + seen[j][(x >> j) & 1]) for j in range(N_FEATURES)) / N_FEATURES


def choose(arm: str, weights, already: list[int], rng: random.Random) -> int:
    rest = [x for x in CANDIDATES if x not in already]
    if arm == 'answer_first':
        # Fair baseline: still learns from each answer, but requests salient,
        # common motifs instead of asking which unknown would be informative.
        salience = [1 / (1 + x.bit_count())**2 for x in rest]
        return rng.choices(rest, weights=salience, k=1)[0]
    if arm == 'curiosity_only':
        scores = {x: uncertainty(weights, x) for x in rest}
    elif arm == 'curiosity_diversity':
        scores = {x: .72 * uncertainty(weights, x) + .28 * novelty(x, already) for x in rest}
    else:
        raise ValueError(arm)
    best = max(scores.values())
    tied = [x for x, score in scores.items() if best - score <= 1e-10]
    return rng.choice(tied)


def assess(weights, oracle):
    probs = [prob_one(weights, x) for x in HOLDOUT]
    labels = [oracle(x) for x in HOLDOUT]
    accuracy = mean(int((p >= 0.5) == y) for p, y in zip(probs, labels))
    brier = mean((p - y)**2 for p, y in zip(probs, labels))
    return (accuracy, brier)


def run_one(seed: int, regime: str, arm: str):
    oracle = make_oracle(seed, regime)
    weights = [1 / len(HYPOTHESES)] * len(HYPOTHESES)
    # Each arm starts from exactly one identical known example.
    weights = update(weights, 0, oracle(0))
    queried = [0]
    # Deterministic per-arm random policy. No holdout results in selection.
    rng = random.Random(seed * 101 + ARMS.index(arm) * 7919 + 31)
    snapshots = {}
    for i in range(1, max(BUDGETS) + 1):
        x = choose(arm, weights, queried, rng)
        queried.append(x)
        weights = update(weights, x, oracle(x))
        if i in BUDGETS:
            accuracy, brier = assess(weights, oracle)
            snapshots[str(i)] = {'accuracy': accuracy, 'brier': brier}
    return {'budget_metrics': snapshots, 'queries': queried[1:], 'starting_sample': 0}


def mean_ci(deltas, seed=77, reps=2000):
    # Paired seed bootstrap. Descriptive uncertainty, not a causal population CI.
    avg = mean(deltas)
    rng = random.Random(seed)
    n = len(deltas)
    boot = sorted(mean(deltas[rng.randrange(n)] for _ in range(n)) for _ in range(reps))
    return [round(avg, 5), round(boot[int(.025 * reps)], 5), round(boot[int(.975 * reps)], 5)]


def run(n_seeds=N_SEEDS):
    results = {'schema': 'nasuraya/curiosity-paired-study/1',
               'description': 'Synthetic active learning, not an LLM experiment, ritual efficacy test, manuscript decoding or AGI consciousness measurement',
               'n_seeds': n_seeds, 'seed_start': SEED_START,
               'regimes': {}, 'all_holdout_disjoint': True,
               'number_of_holdout_patterns': len(HOLDOUT),
               'all_arms_equal_oracle_answers_at_each_budget': True,
               'query_budget_excludes_one_shared_initial_sample': True}
    for regime in REGIMES:
        rows = {seed: {arm: run_one(seed, regime, arm) for arm in ARMS}
                for seed in range(SEED_START, SEED_START + n_seeds)}
        summary = {'arms': {}, 'paired_accuracy_differences': {}, 'example_queries': {}}
        for arm in ARMS:
            summary['arms'][arm] = {str(b): {
                'accuracy_pct': round(mean(rows[s][arm]['budget_metrics'][str(b)]['accuracy'] for s in rows) * 100, 2),
                'mean_brier': round(mean(rows[s][arm]['budget_metrics'][str(b)]['brier'] for s in rows), 5),
                'mean_number_of_oracle_answers': b,
            } for b in BUDGETS}
            summary['example_queries'][arm] = rows[SEED_START][arm]['queries'][:8]
        for b in BUDGETS:
            for compare in ('curiosity_only', 'curiosity_diversity'):
                diff = [(rows[s][compare]['budget_metrics'][str(b)]['accuracy'] - rows[s]['answer_first']['budget_metrics'][str(b)]['accuracy']) * 100 for s in rows]
                summary['paired_accuracy_differences'][f'{compare}_minus_answer_first_budget_{b}_pp'] = mean_ci(diff, seed=b*100+ARMS.index(compare))
            diff = [(rows[s]['curiosity_diversity']['budget_metrics'][str(b)]['accuracy'] - rows[s]['curiosity_only']['budget_metrics'][str(b)]['accuracy']) * 100 for s in rows]
            summary['paired_accuracy_differences'][f'diversity_minus_curiosity_budget_{b}_pp'] = mean_ci(diff, seed=500+b)
        results['regimes'][regime] = summary
    results['method_fingerprint'] = hashlib.sha256((str(HYPOTHESES) + str(CANDIDATES) + str(HOLDOUT) + str(BUDGETS)).encode()).hexdigest()
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', type=int, default=N_SEEDS)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result = run(a.seeds)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
