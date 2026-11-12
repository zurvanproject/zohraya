"""Regression only: reproduce already-opened stage-2 test data, never fit a model.

Run as `python -m scripts.verify_nasuraya_stage2 --output NEW_DIRECTORY`.
Exact categorical/structural comparison; numeric tolerance accommodates Python
3.11/3.12 summation. Timing and byte-level state digests are reported separately.
The evaluator itself verifies every frozen source byte before generating data.
"""
import argparse
import gzip
import json
import math
from pathlib import Path
import platform

from examples.nasuraya_runtime import stream_study
from examples.tadash_interoception.state import digest

REFERENCE = Path(__file__).resolve().parents[1] / 'docs/evidence/nasuraya-stage2-v01'


def compare(expected, actual, path='root'):
    if type(expected) in (int, float) and type(actual) in (int, float):
        if not math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-10):
            raise AssertionError(f'{path}: {expected!r} != {actual!r}')
    elif isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys(): raise AssertionError(f'{path}: keys changed')
        for key in expected:
            if key not in ('all_model_evaluation_seconds', 'state_sha'):
                compare(expected[key], actual[key], path+'.'+key)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual): raise AssertionError(f'{path}: length changed')
        for i, (a, b) in enumerate(zip(expected, actual)): compare(a, b, f'{path}[{i}]')
    elif type(expected) is not type(actual) or expected != actual:
        raise AssertionError(f'{path}: categorical value changed')


def audit_observer(lines, predictions):
    expected = {f'{group}/selected:{r["seed"]}:{r["tick"]}': r
                for group, rows in predictions.items() for r in rows}
    pending, seen, tail, wrong, count = {}, set(), '0'*64, 0, 0
    for sequence, line in enumerate(lines):
        row = json.loads(line); sha = row.pop('sha256')
        if row['sequence'] != sequence or row['previous'] != tail or digest(row) != sha:
            raise AssertionError('observer hash/sequence discontinuity')
        tail = sha; identity = row['identity']; reference = expected[identity]
        if row['kind'] == 'prediction':
            if identity in seen or 'truth' in row: raise AssertionError('repeated or nonblind prediction')
            compare(reference['predictions']['full'], row['prediction'])
            if reference['state_sha'] != row['state_sha']: raise AssertionError('state commitment mismatch')
            pending[identity] = row; seen.add(identity)
        elif row['kind'] == 'revealed_outcome':
            if identity not in pending: raise AssertionError('truth revealed before prediction')
            compare(reference['truth'], row['truth']); pending.pop(identity)
            wrong += int(row['wrong']); count += 1
        else: raise AssertionError('unexpected observer event')
    if pending or set(expected) != seen: raise AssertionError('incomplete observer coverage')
    return {'predictions': count, 'observer_events': len(lines), 'strict_errors': wrong, 'tail_sha256': tail}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = json.loads((REFERENCE/'report.json').read_text(encoding='utf-8'))
    predicted = json.loads(gzip.decompress((REFERENCE/'predictions.json.gz').read_bytes()))
    original_audit = audit_observer(gzip.decompress((REFERENCE/'observer.jsonl.gz').read_bytes()).splitlines(), predicted)
    stream_study.test(args.output, REFERENCE/'frozen-models.json.gz')
    # Compare persisted JSON on both sides (the in-memory splits are tuples).
    result = json.loads((args.output/'report.json').read_text(encoding='utf-8'))
    actual = json.loads(gzip.decompress((args.output/'predictions.json.gz').read_bytes()))
    compare(original, result); compare(predicted, actual)
    current_audit = audit_observer((args.output/'observer.jsonl').read_bytes().splitlines(), actual)
    hash_differences = sum(a['state_sha'] != b['state_sha'] for group in predicted
                           for a,b in zip(predicted[group],actual[group]))
    verification = {'regression_passed': True, 'python': platform.python_version(),
        'model_updates': 0, 'categorical_comparison': 'exact', 'absolute_tolerance': 1e-10,
        'relative_tolerance': 1e-9, 'reference_observer': original_audit,
        'current_observer': current_audit, 'state_byte_hash_differences': hash_differences,
        'state_hash_policy': 'exact within each transcript; cross-version numeric predictions compared with tolerance',
        'timings_compared': False, 'new_independent_test': False}
    stream_study.write(args.output/'verification.json', verification)
    print(json.dumps(verification, sort_keys=True))


if __name__ == '__main__': main()
