"""Worker entry point; imports verified runtime only in its isolated process."""
import json
from pathlib import Path
import sys
import unittest

from .host import BodyLoop, validate_duration


def main(args):
    command = args['command']
    if command == 'adaptive-test':
        from . import test_adaptive_memory
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_adaptive_memory)
        r = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if r.wasSuccessful() else 1
    if command == 'predictive-benchmark':
        from .predictive_benchmark import run_benchmark
        report = run_benchmark(args['output_dir'])
        print(json.dumps({'success':report['success'], 'test_mae':report['evaluation']['test']['mae'],
                          'improvement_percent':report['improvement_percent']},sort_keys=True))
        return 0
    if command == 'adaptive':
        from .adaptive_memory import AdaptiveMemory
        with BodyLoop(args['session']) as loop:
            result = AdaptiveMemory(loop).run_goal(args['goal_id'],target_cycles=args['target_cycles'],
                                                  time_budget_s=args['timeout_seconds'])
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0 if result['status']=='completed' else 1
    if command == 'test':
        from . import test_body_loop, test_self_maintenance
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m)
                                   for m in (test_body_loop, test_self_maintenance))
        r = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if r.wasSuccessful() else 1
    if command == 'api-test':
        from . import test_api_host, test_api_recovery
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m)
                                   for m in (test_api_host, test_api_recovery))
        r = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if r.wasSuccessful() else 1
    if command == 'benchmark':
        from .paired_benchmark import run_benchmark
        report = run_benchmark(args['output_dir'])
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    if command == 'maintain':
        from .self_maintenance import SelfMaintenance
        with BodyLoop(args['session']) as loop:
            result = SelfMaintenance(loop, goal_id=args['goal_id'],
                                     target_cycles=args['target_cycles']).run()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result['status'] == 'completed' else 1
    if command == 'api':
        from examples.nasuraya_agent_loop.agents_api import make_client, run_api
        from examples.nasuraya_agent_loop.local import Journal
        from .api_host import BodyAPIHost
        output = Path(args['output_dir'])
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        with BodyLoop(args['session']) as loop:
            host = BodyAPIHost(loop, mode=args['api_mode'], target_cycles=args['target_cycles'],
                               max_calls=args['max_calls'], journal=Journal(output / 'events.jsonl'), run_id=args['run_id'])
            with make_client() as client:
                summary = run_api(host, client, model=args['model'], max_calls=args['max_calls'],
                                  timeout_seconds=args['timeout_seconds'], live_service=True,
                                  recovery=args['api_recovery'], max_reconnects=args['max_reconnects'])
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary['status'] == 'completed' else 1
    if command == 'run-status':
        from .api_host import BodyAPIHost
        with BodyLoop(args['session']) as loop:
            host = BodyAPIHost.resume(loop, run_id=args['run_id'])
            print(json.dumps(dict(run_id=host.run_id, evaluation=host.evaluate(),
                                 self_model=host.snapshot()), ensure_ascii=False, sort_keys=True))
        return 0
    if command == 'demo':
        output = Path(args['output_dir'])
        if type(args['steps']) is not int or not 0 <= args['steps'] <= args['max_actions'] <= 100:
            raise ValueError('steps must fit the declared action budget')
        validate_duration(args['duration_s'])
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        with BodyLoop.start(output / 'session.sqlite', fixture=args['fixture'],
                            mode=args['mode'], max_actions=args['max_actions']) as loop:
            rows = []
            for i in range(args['steps']):
                observation = loop.observe()
                result = loop.step(duration_s=args['duration_s'])
                rows.append({'before': observation, 'outcome': result})
                if result['status'] != 'complete':
                    break
            summary = loop.status()
            summary['status'] = ('failed' if summary['failed_cycles'] else
                                 'completed' if summary['completed_cycles'] == args['steps'] else 'incomplete')
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
    if command == 'demo':
        return 0 if summary['status'] == 'completed' else 1
    if command == 'step':
        return 0 if summary['status'] == 'complete' else 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps({'status':'rejected','exception_type':type(exc).__name__,'reason':str(exc)}))
        raise SystemExit(1)
