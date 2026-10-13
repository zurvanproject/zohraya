"""Worker entry point; imports verified runtime only in its isolated process."""
import json
from pathlib import Path
import sys
import unittest

from .host import BodyLoop


def main(args):
    command = args['command']
    if command == 'test':
        from . import test_body_loop
        r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_body_loop))
        return 0 if r.wasSuccessful() else 1
    if command == 'demo':
        output = Path(args['output_dir'])
        if type(args['steps']) is not int or not 0 <= args['steps'] <= args['max_actions'] <= 100:
            raise ValueError('steps must fit the declared action budget')
        output.mkdir(parents=True, exist_ok=False)
        with BodyLoop.start(output / 'session.sqlite', fixture=args['fixture'],
                            mode=args['mode'], max_actions=args['max_actions']) as loop:
            rows = []
            for i in range(args['steps']):
                observation = loop.observe()
                result = loop.step(duration_s=args['duration_s'])
                rows.append({'before': observation, 'outcome': result})
            summary = loop.status()
            summary['status'] = 'completed' if summary['completed_cycles'] == args['steps'] else 'incomplete'
            (output / 'events.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n' for row in rows))
            (output / 'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
            (output / 'decisions.json').write_text(json.dumps(loop.engine.export(),ensure_ascii=False,indent=2)+'\n')
    else:
        if command == 'start':
            loop = BodyLoop.start(args['session'], fixture=args['fixture'], mode=args['mode'], max_actions=args['max_actions'])
        else:
            loop = BodyLoop(args['session'])
        with loop:
            if command == 'observe': summary = loop.observe()
            elif command == 'step': summary = loop.step(decision_id=args['decision_id'], duration_s=args['duration_s'])
            else: summary = loop.status()
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps({'status':'rejected','exception_type':type(exc).__name__,'reason':str(exc)}))
        raise SystemExit(1)
