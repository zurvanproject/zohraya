"""Loaded in a source-verified temporary native runtime by the CLI."""
import json
import sys
import unittest

from examples.nasuraya_body_loop.host import BodyLoop
from .appraisal import apply


def main(args):
    if args['command'] == 'test':
        from . import test_appraisal, test_integration
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m)
                                   for m in (test_appraisal, test_integration))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if args['command'] == 'evaluate':
        from .evaluate import evaluate
        result = evaluate(args.get('output_dir'))
    else:
        with BodyLoop(args['session']) as loop:
            result = apply(loop, args['observation'], approved_reference=args['approved_reference'],
                           image_path=args['image_path'])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps(dict(status='rejected', error_type=type(exc).__name__, reason=str(exc))))
        raise SystemExit(1)
