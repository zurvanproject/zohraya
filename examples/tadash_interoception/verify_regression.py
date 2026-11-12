"""Compare replay with frozen confirmation, excluding machine-dependent cost."""
import gzip
import json
import math
from pathlib import Path
import sys


def compare(expected, actual, path='root'):
    if isinstance(expected, float):
        if type(actual) not in (int, float) or not math.isfinite(actual) or not math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-10):
            raise AssertionError('numeric regression at ' + path)
    elif type(expected) is not type(actual):
        raise AssertionError('type regression at ' + path)
    elif isinstance(expected, dict):
        if expected.keys() != actual.keys(): raise AssertionError('field regression at ' + path)
        for key in expected: compare(expected[key], actual[key], path + '.' + key)
    elif isinstance(expected, list):
        if len(expected) != len(actual): raise AssertionError('count regression at ' + path)
        for i, (left, right) in enumerate(zip(expected, actual)): compare(left, right, path + '[' + str(i) + ']')
    elif expected != actual:
        raise AssertionError('value regression at ' + path)


def verify(path):
    root = Path(__file__).resolve().parents[2]
    expected = json.loads(gzip.decompress((root / 'docs/evidence/tadash-interoception-v01/confirmation-report.json.gz').read_bytes()))
    actual = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ('split_ranges', 'trial_predictions', 'paired_change'):
        compare(expected[key], actual[key], key)
    compare({k: v['all'] for k, v in expected['models'].items()},
            {k: v['all'] for k, v in actual['models'].items()}, 'metrics')
    for correction in actual['corrections'].values():
        if correction['novel_cases_used_for_fitting_or_selection'] != 0:
            raise AssertionError('novel examples entered fitting')
    return {'verified': True, 'episodes': len(actual['trial_predictions']),
            'float_absolute_tolerance': 1e-10, 'float_relative_tolerance': 1e-9,
            'timing_compared': False, 'new_independent_holdout': False}


if __name__ == '__main__': print(json.dumps(verify(sys.argv[1])))
