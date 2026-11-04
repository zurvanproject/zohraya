"""Tadash Dream Ledger v0.1: bounded, offline *imagined* rehearsal.

Reads prior completed synthetic native-transition receipts. Counterfactual
sequences are labelled imagined and never passed back as measurements, policy
updates, live motor commands, or ground truth. No external dependencies.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import fmean

SCHEMA = 'tadash-dream-ledger/1'
METRICS = ('arousal', 'pain', 'fatigue', 'energy', 'hydration')
ACTIONS = ('observe', 'slow_breath', 'walk', 'protect')
MAX_BYTES = 2_000_000
MAX_EVENTS = 256
MAX_DREAMS = 4
MAX_STEPS = 3
AUDIT_CAPS = {'energy_error_J': 5e-5, 'water_error_L': 1e-8,
              'neural_clock_error_s': 1e-7}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def finite(value, *, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('only finite numeric evidence is accepted')
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError('metric or audit outside declared bounds')
    return float(value)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('invalid event identifier')
    return value


def vector(value):
    if not isinstance(value, dict) or set(value) != set(METRICS):
        raise ValueError('exactly five observed state metrics required')
    return {k: finite(value[k], low=0, high=1) for k in METRICS}


def no_duplicate_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError('nonfinite JSON constant')


def validate_row(row):
    required = {'event_id', 'episode_id', 'context', 'synthetic', 'requested',
                'actual', 'before', 'after', 'native_audit'}
    if not isinstance(row, dict) or set(row) != required:
        raise ValueError('native-transition schema mismatch')
    if row['synthetic'] is not True:
        raise ValueError('only declared synthetic native data allowed')
    for key in ('event_id', 'episode_id', 'context'):
        identifier(row[key])
    if row['context'] not in ('baseline', 'post_walk'):
        raise ValueError('unsupported predeclared training/evaluation context')
    if row['requested'] not in ACTIONS or row['actual'] not in ACTIONS:
        raise ValueError('unknown requested or executed action')
    before, after = vector(row['before']), vector(row['after'])
    audit = row['native_audit']
    if not isinstance(audit, dict) or not set(AUDIT_CAPS).issubset(audit):
        raise ValueError('missing native conservation audit')
    for key, cap in AUDIT_CAPS.items():
        if abs(finite(audit[key])) > cap:
            raise ValueError('failed native conservation audit')
    return {**row, 'before': before, 'after': after}


def read_native_rows(path: Path, expected_sha256: str):
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('independently supplied source SHA256 required')
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('missing or oversize source evidence')
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError('source SHA256 mismatch')
    lines = raw.splitlines()
    if not 1 <= len(lines) <= MAX_EVENTS:
        raise ValueError('event count out of bounds')
    seen, rows = set(), []
    for line in lines:
        if not line or len(line) > 16_384:
            raise ValueError('empty or oversize source row')
        row = validate_row(json.loads(line.decode('utf-8'),
                object_pairs_hook=no_duplicate_json, parse_constant=reject_constant))
        if row['event_id'] in seen:
            raise ValueError('duplicate native event')
        seen.add(row['event_id'])
        rows.append(row)
    return rows, actual_sha


def clamp(value):
    return max(0.0, min(1.0, value))


def train_delta(rows):
    """Only baseline *actual* actions train. No imagined event enters the fit."""
    train = [r for r in rows if r['context'] == 'baseline']
    eval_rows = [r for r in rows if r['context'] == 'post_walk']
    train_eps = {r['episode_id'] for r in train}
    eval_eps = {r['episode_id'] for r in eval_rows}
    if not train or not eval_rows or train_eps & eval_eps:
        raise ValueError('disjoint episode-level training and evaluation required')
    grouped = defaultdict(list)
    for r in train:
        if r['requested'] == r['actual']:
            grouped[r['actual']].append(r)
    model = {}
    for action, selected in sorted(grouped.items()):
        if len(selected) < 2:
            continue
        model[action] = {
            'count': len(selected),
            'delta': {k: fmean(r['after'][k] - r['before'][k] for r in selected)
                      for k in METRICS},
            'bounds': {k: [min(r['before'][k] for r in selected),
                           max(r['before'][k] for r in selected)]
                       for k in METRICS}}
    if not model:
        raise ValueError('insufficient matched native training actions')
    return train, eval_rows, model


def in_domain(before, spec):
    # Narrow authored guard, *not* calibrated confidence intervals.
    return all(spec['bounds'][k][0] - .05 <= before[k] <=
               spec['bounds'][k][1] + .05 for k in METRICS)


def forecast(before, spec):
    return {k: clamp(before[k] + spec['delta'][k]) for k in METRICS}


def dream_sequences(train, model, source_sha256):
    """Counterfactuals originate ONLY in training; never assert a real outcome."""
    available = [r for r in sorted(train, key=lambda r: r['event_id'])
                 if r['requested'] == r['actual']]
    dreams = []
    for root in available:
        alternatives = [a for a in sorted(model) if a != root['actual']
                        and in_domain(root['before'], model[a])]
        if not alternatives:
            continue
        alternative = alternatives[0]
        state = dict(root['before']); states = []
        for step in range(1, MAX_STEPS + 1):
            if not in_domain(state, model[alternative]):
                break
            state = forecast(state, model[alternative])
            states.append({'step': step, 'state': state,
                           'kind': 'imagined_not_observed'})
        if not states:
            continue
        dreams.append({'id': f'dream-{len(dreams)+1}',
            'root_observed_event': root['event_id'],
            'counterfactual_action': alternative, 'imagined_states': states,
            'kind': 'model_generated_hypothesis',
            'source_sha256': source_sha256, 'native_actions_executed': 0,
            'allowed_to_train_or_act': False})
        if len(dreams) == MAX_DREAMS:
            break
    return dreams


def consolidate_observed(train, source_sha256):
    """A bounded memory index, never consolidated imaginary experiences."""
    ordered = sorted(train, key=lambda r: (
        -int(r['requested'] != r['actual'] or r['actual'] == 'protect'),
        -sum(abs(r['after'][k] - r['before'][k]) for k in METRICS),
        r['event_id']))[:8]
    return [{'event_id': r['event_id'], 'source_sha256': source_sha256,
             'kind': 'observed_synthetic_native_receipt',
             'requested': r['requested'], 'actual': r['actual'],
             'priority_proxy': sum(abs(r['after'][k]-r['before'][k]) for k in METRICS),
             'imagined': False,
             'protection_or_veto_observed': (r['actual'] == 'protect' or
                                             r['requested'] != r['actual'])}
             for r in ordered]


def evaluate(rows, source_sha256):
    train, holdout, model = train_delta(rows)
    outcomes, abstained = [], []
    for row in holdout:
        action = row['actual']
        if row['requested'] != action or action not in model or not in_domain(row['before'], model[action]):
            abstained.append({'event_id': row['event_id'], 'reason':
                 'native_veto_or_untrained_or_out_of_domain'})
            continue
        predicted = forecast(row['before'], model[action])
        mae = fmean(abs(predicted[k] - row['after'][k]) for k in METRICS)
        baseline = fmean(abs(row['before'][k] - row['after'][k]) for k in METRICS)
        outcomes.append({'event_id': row['event_id'], 'episode_id': row['episode_id'],
            'model_mae': mae, 'persistence_mae': baseline,
            'observed_actual_action': action})
    candidate = fmean(r['model_mae'] for r in outcomes) if outcomes else None
    baseline = fmean(r['persistence_mae'] for r in outcomes) if outcomes else None
    # No promotion based on correlated, reused authored native fixtures.
    beats = (candidate is not None and baseline > 1e-12 and
             candidate <= .90 * baseline and len({r['episode_id'] for r in outcomes}) >= 4
             and not abstained)
    dreams = dream_sequences(train, model, source_sha256)
    memories = consolidate_observed(train, source_sha256)
    train_ids = [r['event_id'] for r in train]
    eval_ids = [r['event_id'] for r in holdout]
    if ({r['root_observed_event'] for r in dreams} - set(train_ids)
            or set(train_ids) & set(eval_ids)):
        raise AssertionError('imagined/holdout leakage')
    report = {'schema': SCHEMA, 'synthetic_only': True,
        'source_sha256': source_sha256, 'training_rows': len(train),
        'evaluation_rows': len(holdout), 'scored_rows': len(outcomes),
        'abstentions': abstained, 'training_episode_count': len({r['episode_id'] for r in train}),
        'evaluation_episode_count': len({r['episode_id'] for r in holdout}),
        'training_event_ids_sha256': digest(train_ids),
        'heldout_event_ids_sha256': digest(eval_ids),
        'model_sha256': digest(model), 'model': model,
        'per_observed_holdout': outcomes, 'model_mae': candidate,
        'persistence_mae': baseline, 'candidate_beats_persistence_by_10pct': beats,
        'imagined_scenarios': len(dreams), 'imagined_steps': sum(len(d['imagined_states']) for d in dreams),
        'imaginary_memory_used_as_training': False,
        'promotion_authorized': False, 'native_actions_executed': 0,
        'external_calls': 0, 'paid_api_calls': 0,
        'reason': 'prospective_independent_native_multistep_test_and_review_required',
        'subjective_dreams_or_consciousness_claimed': False}
    return report, dreams, memories


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    rows, sha = read_native_rows(args.source, args.expected_sha256)
    report, dreams, memory = evaluate(rows, sha)
    # Never overwrite prior evidence or silently resume/retry a partial run.
    out = args.output_dir.resolve()
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, payload in [('report.json', report), ('imagined-dreams.json', dreams),
                          ('observed-memory-index.json', memory)]:
        (out / name).write_text(encode(payload) + '\n', encoding='utf-8')
    print(encode({k: report[k] for k in ('schema','training_rows','evaluation_rows',
        'scored_rows','model_mae','persistence_mae', 'candidate_beats_persistence_by_10pct',
        'imagined_scenarios','promotion_authorized')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
