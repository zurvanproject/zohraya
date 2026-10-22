"""Finite offline research curriculum. Proposals only; never a body authority.

A generated policy adds one evidence rule at a time. Training errors choose the
question; a separate deterministic synthetic split decides acceptance. This is
not open-web research, arbitrary code generation, or a blinded capability study.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import re

SCHEMA = 'nasuraya-research-memory/1'
FEATURES = ('context', 'trusted', 'freshness', 'conflict')
BASELINE = {name: False for name in FEATURES}
KINDS = ('clean', 'context', 'trusted', 'stale', 'future', 'conflict')
QUESTIONS = {
    'context': 'Does restricting recall to the requested context reduce wrong recall?',
    'trusted': 'Does ignoring untrusted observations reduce wrong recall?',
    'freshness': 'Does abstaining on stale or future evidence reduce wrong recall?',
    'conflict': 'Does abstaining on equally recent conflicting evidence reduce wrong recall?',
}


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def engine_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def cases(seed, count):
    """Authored toy situations; independent split, shared generator family."""
    rng = random.Random(seed)
    rows = []
    for kind in KINDS:
        for _ in range(count):
            now = rng.randint(2000, 20000)
            context = 'context_' + str(rng.randrange(8))
            value = rng.randrange(2)
            valid = dict(context=context, value=value, at=now-rng.randint(10, 60), trusted=True)
            observations = [valid]
            expected = value
            if kind == 'context':
                observations += [dict(valid, context='foreign', at=now-1, value=1-value)]
            elif kind == 'trusted':
                observations += [dict(valid, at=now-1, value=1-value, trusted=False)]
            elif kind == 'stale':
                observations = [dict(valid, at=now-rng.randint(301, 600))]
                expected = None
            elif kind == 'future':
                observations = [dict(valid, at=now+rng.randint(1, 60))]
                expected = None
            elif kind == 'conflict':
                observations += [dict(valid, value=1-value)]
                expected = None
            rows.append(dict(kind=kind, context=context, now=now,
                             observations=observations, expected=expected))
    rng.shuffle(rows)
    return rows


def recall(policy, row):
    observations = [item for item in row['observations']
        if (not policy['context'] or item['context'] == row['context'])
        and (not policy['trusted'] or item['trusted'] is True)
        and (not policy['freshness'] or 0 <= row['now']-item['at'] <= 120)]
    if not observations:
        return None
    latest = max(item['at'] for item in observations)
    newest = [item for item in observations if item['at'] == latest]
    if policy['conflict'] and len({item['value'] for item in newest}) > 1:
        return None
    return newest[0]['value']


def evaluate(policy, rows):
    errors = {name: 0 for name in KINDS}
    for row in rows:
        if recall(policy, row) != row['expected']:
            errors[row['kind']] += 1
    return dict(total=len(rows), errors=sum(errors.values()), by_kind=errors)


def propose(policy, tried):
    train = cases(20261022, 32)
    baseline = evaluate(policy, train)
    weights = {name: baseline['by_kind'].get(name, 0) for name in FEATURES}
    weights['freshness'] = baseline['by_kind']['stale'] + baseline['by_kind']['future']
    remaining = [name for name in FEATURES if name not in tried and weights[name] > 0]
    if not remaining:
        return None
    feature = max(remaining, key=lambda name: (weights[name], -FEATURES.index(name)))
    candidate = dict(policy, **{feature: True})
    training = evaluate(candidate, train)
    # Holdout never participates in feature selection. It gates this proposal.
    holdout = cases(9261022, 48)
    before = evaluate(policy, holdout)
    after = evaluate(candidate, holdout)
    accepted = (training['errors'] < baseline['errors']
        and after['errors'] < before['errors']
        and all(after['by_kind'][kind] <= before['by_kind'][kind] for kind in KINDS))
    return dict(feature=feature, question=QUESTIONS[feature], candidate=candidate,
        accepted=accepted, training=dict(before=baseline, after=training),
        holdout=dict(before=before, after=after),
        dataset_hashes=dict(training=digest(train), holdout=digest(holdout)),
        lesson=('Candidate retained in laboratory only; validate on external cases.' if accepted
                else 'Candidate rejected; preserve the incumbent and do not repeat this feature.'),
        limitations='Authored synthetic family, reused validation split; no generalization claim.')


def initial():
    return dict(schema=SCHEMA, engine=engine_digest(), policy=deepcopy(BASELINE), history=[])


def _append(memory, run_id):
    trial = propose(memory['policy'], [entry['trial']['feature'] for entry in memory['history']])
    if trial is None:
        return deepcopy(memory), dict(status='curriculum_complete', next='owner_review_new_curriculum')
    receipt = dict(run_id=run_id, index=len(memory['history'])+1,
                   parent=digest(memory), trial=trial)
    result = deepcopy(memory)
    result['history'].append(receipt)
    if trial['accepted']:
        result['policy'] = trial['candidate'].copy()
    return result, receipt


def validate(memory):
    if not isinstance(memory, dict) or set(memory) != {'schema', 'engine', 'policy', 'history'}:
        raise ValueError('invalid research memory')
    if memory['schema'] != SCHEMA or memory['engine'] != engine_digest():
        raise ValueError('research engine changed; explicit migration required')
    if not isinstance(memory['history'], list) or len(memory['history']) > len(FEATURES):
        raise ValueError('invalid history bound')
    policy = memory['policy']
    if not isinstance(policy, dict) or set(policy) != set(FEATURES) or any(type(v) is not bool for v in policy.values()):
        raise ValueError('invalid policy')
    replay = initial()
    seen = set()
    for receipt in memory['history']:
        run_id = receipt.get('run_id') if isinstance(receipt, dict) else None
        check_id(run_id)
        if run_id in seen:
            raise ValueError('duplicate research run')
        seen.add(run_id)
        replay, expected = _append(replay, run_id)
        if encode(expected) != encode(receipt):
            raise ValueError('research receipt does not replay')
    if encode(replay) != encode(memory):
        raise ValueError('research policy does not match evidence')


def check_id(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('invalid research run id')


def advance(memory, run_id):
    validate(memory)
    check_id(run_id)
    for receipt in memory['history']:
        if receipt['run_id'] == run_id:
            return deepcopy(memory), deepcopy(receipt)
    return _append(memory, run_id)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--initial']:
        print(encode(initial()))
    else:
        request = json.load(sys.stdin)
        result, receipt = advance(request['memory'], request['run_id'])
        print(encode(dict(memory=result, receipt=receipt)))
