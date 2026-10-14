"""Worker entry point; imports verified runtime only in its isolated process."""
import json
from pathlib import Path
import sys
import unittest

from .host import BodyLoop, validate_duration


def main(args):
    command = args['command']
    if command == 'care-memory':
        from .care import reconcile
        from .api_host import BodyAPIHost
        with BodyLoop(args['session']) as loop:
            host = BodyAPIHost.resume(loop, run_id=args['run_id'])
            result = reconcile(host)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if command == 'care-test':
        from . import test_care
        r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_care))
        return 0 if r.wasSuccessful() else 1
    if command == 'care-demo':
        from .care_demo import demo
        return demo(args['output_dir'])
    if command == 'wake-demo':
        from .wake_demo import demo
        return demo(args['output_dir'])
    if command == 'wake-test':
        from . import test_scheduler
        r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_scheduler))
        return 0 if r.wasSuccessful() else 1
    if command == 'schedule':
        from .scheduler import register
        with BodyLoop(args['session']) as loop:
            result = register(loop, wake_id=args['wake_id'], run_id=args['run_id'],
                due_at=args['due_at'], expires_at=args['expires_at'], model=args['model'],
                backend=args['wake_backend'], max_attempts=args['wake_attempts'],
                timeout_seconds=args['timeout_seconds'], retry_delay_seconds=args['retry_delay_seconds'])
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if command in ('wake', 'wake-watch', 'wake-status'):
        import time
        from .scheduler import schedules, tick, TERMINAL
        try:
            with BodyLoop(args['session']) as loop:
                rows = schedules(loop)
        except BlockingIOError:
            rows = None
        if command == 'wake-status':
            print(json.dumps(dict(state='busy') if rows is None else rows, ensure_ascii=False, sort_keys=True))
            return 0
        selected = next((r for r in rows or [] if r['id'] == args['wake_id']), None)
        if rows is not None and selected is None:
            raise ValueError('saved wakeup required')
        if selected and selected['contract']['backend'] == 'api' and not args['allow_live_wakeup']:
            raise ValueError('saved API wakeup requires explicit --allow-live-wakeup')
        if rows is None:
            # Do not dispatch an uninspected live schedule while another host owns it.
            print(json.dumps(dict(state='busy', execution_started=False)))
            return 0
        count = args['watch_ticks'] if command == 'wake-watch' else 1
        for i in range(count):
            result = tick(args['session'], wake_id=args['wake_id'])
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
            if result['state'] in TERMINAL:
                return 0 if result['state'] == 'completed' else 1
            if i + 1 < count:
                time.sleep(args['poll_seconds'])
        return 0
    if command == 'test':
        from . import test_body_loop
        r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_body_loop))
        return 0 if r.wasSuccessful() else 1
    if command == 'api-test':
        from . import test_api_host, test_api_recovery, test_continuation
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m)
                                   for m in (test_api_host, test_api_recovery, test_continuation))
        r = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if r.wasSuccessful() else 1
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
    if command == 'authorize-continuation':
        from .continuation import authorize
        with BodyLoop(args['session']) as loop:
            grant = authorize(loop, grant_id=args['grant_id'], run_id=args['run_id'],
                additional_actions=args['additional_actions'], additional_calls=args['additional_calls'],
                observed_checkpoint_sha256=args['observed_checkpoint_sha256'])
            print(json.dumps(dict(grant=grant, status=loop.status()), ensure_ascii=False, sort_keys=True))
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
