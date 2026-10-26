"""Only launched after verifying/copying the recovered native body sources."""
import json
from pathlib import Path
import shutil
import sys
import unittest

from examples.nasuraya_body_loop.host import BodyLoop
from .engine import AffectiveAgent
from .body_dialogue import DialogueBodyBridge


def main(args):
    if args['command'] == 'test':
        from . import test_body_dialogue, test_integrated_dialogue
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                   for module in (test_body_dialogue, test_integrated_dialogue))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args['command'] == 'evaluate':
        from .evaluate_dialogue import evaluate
        print(json.dumps(evaluate(Path(args['output'])), ensure_ascii=False, indent=2))
        return 0
    folder = Path(args['session_dir'])
    if args['command'] == 'init':
        folder.mkdir(parents=True, exist_ok=False)
        if args['seed_affect']:
            shutil.copyfile(args['seed_affect'], folder/'affect.sqlite')
        with BodyLoop.start(folder/'body.sqlite', fixture=args['fixture'], max_actions=args['max_actions']) as body:
            with AffectiveAgent(folder/'affect.sqlite') as affect:
                bridge = DialogueBodyBridge.enable(body, affect)
                result = bridge.status()
    else:
        if not (folder/'body.sqlite').is_file() or not (folder/'affect.sqlite').is_file():
            raise ValueError('existing paired session required')
        with BodyLoop(folder/'body.sqlite') as body, AffectiveAgent(folder/'affect.sqlite') as affect:
            bridge = DialogueBodyBridge(body, affect)
            if args['command'] == 'resume':
                bridge.resume()
            elif args['command'] == 'pause':
                bridge.pause()
            if args['command'] == 'message':
                result = bridge.receive(json.loads(Path(args['message']).read_text()))
            elif args['command'] == 'trace':
                result = bridge.trace(args['message_id'])
            elif args['command'] == 'recall':
                result = bridge.recall(args['cue'])
            elif args['command'] == 'consolidate':
                result = bridge.experience.consolidate()
            else:
                result = bridge.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps(dict(status='rejected', kind=type(exc).__name__, reason=str(exc))))
        raise SystemExit(1)
