"""Internal worker; launch through body_cli so retained sources are verified."""
import json
import sys
import unittest
from examples.nasuraya_body_loop.host import BodyLoop
from .clocked import ClockedSetarBridge


def main(args):
    if args['command'] == 'test':
        from . import test_body_native, test_clocked_native
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                   for module in (test_body_native, test_clocked_native))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    with BodyLoop(args['session']) as loop:
        bridge = ClockedSetarBridge(loop)
        command = args['command']
        if command == 'bind':
            result = bridge.bind(args['checkpoint'], max_steps=args['max_steps'])
        elif command == 'evaluate':
            result = bridge.evaluate()
        elif command in ('step', 'lesson'):
            action = bridge.lesson if command == 'lesson' else bridge.step
            result = action(args['run_id'], args['output_dir'],
                                 realtime=args['realtime'], seed=args['seed'])
        else:
            result = bridge.status()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 2 if result.get('state') == 'deferred' else 1 if result.get('state') == 'failed_or_interrupted' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps({'state': 'rejected', 'exception_type': type(exc).__name__, 'reason': str(exc)}))
        raise SystemExit(1)
