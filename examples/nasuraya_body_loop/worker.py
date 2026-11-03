"""Worker entry point; imports verified runtime only in its isolated process."""
import json
from pathlib import Path
import sys
import unittest

from .host import BodyLoop, validate_duration


def main(args):
    command = args['command']
    if command == 'workspace-test':
        from . import test_workspace
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_workspace)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if command == 'workspace-demo':
        from .workspace_demo import demo
        result = demo(Path(args['output_dir']))
        (Path(args['output_dir']) / 'summary.json').write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\\n',
            encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result['workspace_updated_from_native_receipts'] == 6 else 1
    if command.startswith('workspace-'):
        from .experience import ExperienceController
        from . import workspace
        with BodyLoop(args['session']) as loop:
            controller = ExperienceController(loop)
            if command == 'workspace-enable':
                result = controller.enable_workspace()
            elif command == 'workspace-step':
                if 'workspace' not in controller.status()['state']:
                    raise ValueError('enable integrated workspace before workspace-step')
                result = controller.step(args['decision_id'], duration_s=args['duration_s'])
            else:
                state = controller.status()
                result = state['integrated_workspace'] or {'enabled': False}
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if command == 'workspace-step':
                return 0 if result['native_receipt']['status'] == 'complete' else 1
        return 0
    if command == 'self-knowledge-eval':
        from .self_knowledge_eval import run_evaluation
        summary = run_evaluation(Path(args['output_dir']))
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary['validation_passed'] else 1
    if command == 'instinct-test':
        from . import test_instinct
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_instinct)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if command == 'instinct-demo':
        from .instinct import demo
        print(json.dumps(demo(Path(args['output_dir'])), ensure_ascii=False, sort_keys=True))
        return 0
    if command.startswith('instinct-'):
        from .instinct import InstinctController
        with BodyLoop(args['session']) as loop:
            if command == 'instinct-enable':
                summary = InstinctController.enable(loop).status()
            elif command == 'instinct-step':
                event = json.loads(Path(args['event_json']).read_text(encoding='utf-8'))
                summary = InstinctController(loop).step(event)
            elif command == 'instinct-disable':
                summary = InstinctController(loop).disable()
            else:
                summary = InstinctController(loop).status()
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    if command == 'experience-test':
        from . import test_experience, test_self_knowledge, test_affect_audit, test_self_knowledge_eval
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
            for module in (test_experience, test_self_knowledge, test_affect_audit, test_self_knowledge_eval))
        r = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if r.wasSuccessful() else 1
    if command.startswith('experience-'):
        from .experience import ExperienceController
        if command == 'experience-demo':
            from .experience_demo import demo
            print(json.dumps(demo(Path(args['output_dir'])), ensure_ascii=False, sort_keys=True))
            return 0
        with BodyLoop(args['session']) as loop:
            if command == 'experience-enable':
                summary = ExperienceController.enable(loop).status()
            else:
                controller = ExperienceController(loop)
                if command == 'experience-step':
                    summary = controller.step(args['decision_id'], duration_s=args['duration_s'])
                elif command == 'experience-consolidate':
                    summary = controller.consolidate()
                else:
                    summary = controller.status()
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            if command == 'experience-step':
                return 0 if summary['native_receipt']['status'] == 'complete' else 1
        return 0
    if command == 'test':
        from . import test_body_loop, test_instinct
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
            for module in (test_body_loop, test_instinct))
        r = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if r.wasSuccessful() else 1
    if command == 'api-test':
        from . import test_api_host, test_api_recovery
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m)
                                   for m in (test_api_host, test_api_recovery))
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
