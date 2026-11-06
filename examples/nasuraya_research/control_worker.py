"""Worker loaded only after the existing native source manifest is verified."""
import json
import sys
import unittest


def main(args):
    if args['command'] == 'transfer':
        from .transfer import run
        print(json.dumps(run(args['output_dir']), ensure_ascii=False, sort_keys=True))
        return 0
    if args['command'] == 'transfer-test':
        from . import test_transfer
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_transfer)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if args['command'] == 'evaluate':
        from .evaluate_confidence import evaluate
        print(json.dumps(evaluate(), ensure_ascii=False, sort_keys=True))
        return 0
    if args['command'] == 'test':
        from . import test_controller, test_confidence, test_transfer
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                   for module in (test_controller, test_confidence, test_transfer))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    from examples.nasuraya_body_loop.host import BodyLoop
    from .controller import BoundedResearchController
    command = args['command']
    loop = (BodyLoop.start(args['session'], fixture=args['fixture'], mode='bounded',
                          max_actions=args['max_actions']) if command == 'init'
            else BodyLoop(args['session']))
    with loop:
        control = (BoundedResearchController.enable(loop,
                       forecast_confidence=args.get('forecast_confidence')) if command == 'init'
                   else BoundedResearchController(loop))
        if command == 'pause': control.pause()
        elif command == 'resume': control.resume()
        if command == 'run':
            result = control.run(steps=args['steps'], duration_s=args['duration_s'])
        elif command == 'step':
            result = control.step(args['request_id'], duration_s=args['duration_s'])
        else:
            result = control.status()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps(dict(status='rejected', exception_type=type(exc).__name__, reason=str(exc))))
        raise SystemExit(1)
