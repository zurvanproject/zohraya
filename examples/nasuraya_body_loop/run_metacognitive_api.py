"""Explicit four-run live bridge check using the existing approved-key CLI.

No key enters this module or its outputs. Full local session/transport files are
private; results.json is a reduced, publishable integration report.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from examples.nasuraya_self_model.monitor import SelfModel, ROOT, digest
from .__main__ import verified_sources
from .metacognition import sources

PROTOCOL = Path(__file__).with_name('metacognitive_api_protocol.json')


def save(path, value):
    from persistent_embodiment_v1 import atomic_json
    atomic_json(path, value)


def cli(directory, label, arguments):
    proc = subprocess.run([sys.executable, '-m', 'examples.nasuraya_body_loop', *arguments],
                          cwd=ROOT, text=True, capture_output=True)
    (directory/f'{label}.stdout.txt').write_text(proc.stdout)
    (directory/f'{label}.stderr.txt').write_text(proc.stderr)
    if proc.returncode:
        raise RuntimeError(f'{label} did not complete; private output retained')
    return json.loads(proc.stdout.strip().splitlines()[-1])


def cold(session, model, output):
    from .host import BodyLoop
    from .api_host import BodyAPIHost
    from examples.nasuraya_agent_loop.agents_api import run_api
    count = [0]
    def forbidden(*args, **kwargs):
        count[0] += 1
        raise AssertionError('completed goal must not contact API')
    client = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=SimpleNamespace(
        create=forbidden, delete=forbidden, retrieve=forbidden,
        events=SimpleNamespace(stream=forbidden, create=forbidden)))))
    with BodyLoop(session) as loop:
        host = BodyAPIHost.resume(loop)
        before = loop.body().checkpoint()
        knowledge = loop.metacognition.model.verify()
        result = run_api(host, client, model=model, max_calls=host.max_calls)
        if (count[0] or loop.body().checkpoint() != before or
                loop.metacognition.model.verify() != knowledge or result['actions_this_process']):
            raise AssertionError('cold replay changed state or executed work')
        report = dict(status=result['status'], goal_reached=host.evaluate()['goal_reached'],
            body_checkpoint_sha256=before['sha256'], network_calls=count[0], new_body_cycles=0,
            knowledge_unchanged=True, live_api_verified=result['live_api_verified'])
    save(output, report)


def integration_sources():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('metacognition.py', 'host.py', 'api_host.py', 'worker.py', '__main__.py', 'run_metacognitive_api.py')}


def live(output, *, resume=False):
    from .host import BodyLoop
    from .api_host import BodyAPIHost
    from .metacognition import configure
    protocol = json.loads(PROTOCOL.read_text())
    if protocol['shadow_runs'] != 3 or protocol['enforced_runs'] != 1:
        raise ValueError('review the live budget before changing this protocol')
    native = verified_sources()
    out = Path(output).resolve()
    if resume:
        result = json.loads((out/'results.json').read_text())
        if (result['status'] != 'blocked' or result['blocker'] != 'verified experience does not yet authorize the enforced walk'
                or result['sources'] != sources() or json.loads((out/'frozen-protocol.json').read_text()) != protocol
                or len(result['rows']) != 3 or not all(r['live_api_verified'] for r in result['rows'])):
            raise ValueError('resume is limited to the known pre-API assessment correction')
        if (out/'run-04-enforce/api').exists():
            raise ValueError('API work may have begun; use the existing transport recovery instead')
        save(out/'before-duration-normalization.json', result)
        for row in result['rows']:
            row['integration_sha256'] = result['integration_sha256']
        result.update(status='incomplete', integration_sha256=integration_sources(),
            implementation_correction='canonicalize integral JSON duration at the API boundary; preserve all native receipts and learning',
            resumed_before_fourth_api_call=True)
        result.pop('blocker', None)
        result.pop('blocker_type', None)
    else:
        out.mkdir(mode=0o700, parents=True, exist_ok=False)
        save(out/'frozen-protocol.json', protocol)
        result = dict(schema=protocol['schema'], model=protocol['model'], environment=protocol['environment'],
        protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(), sources=sources(),
        integration_sha256=integration_sources(),
        rows=[], status='incomplete', same_fixture_generalization_claim=False,
        native_source_files_verified=len(native), private_user_body_loaded=False)
    memory = out/'self-model.sqlite'
    last_session = None
    try:
        for index, mode in enumerate(['shadow']*protocol['shadow_runs']+['enforce']):
            if index < len(result['rows']):
                continue
            directory = out/f'run-{index+1:02d}-{mode}'
            session = directory/'session.sqlite'
            if resume:
                with BodyLoop(session) as loop:
                    if loop.records() or loop.status()['actions_reserved'] or loop.body().revision != 0:
                        raise ValueError('the resumed fourth body has already advanced')
                    head = loop.body().checkpoint()['sha256']
            else:
                directory.mkdir(mode=0o700)
                start = cli(directory, 'start', ['start', '--session', str(session), '--max-actions', '1'])
                head = start['self_model']['checkpoint_sha256']
                args = ['configure-metacognition', '--session', str(session), '--self-model', str(memory),
                    '--metacognition-mode', mode, '--observed-checkpoint-sha256', head]
                if index == 0:
                    args.append('--create-self-model')
                cli(directory, 'configure', args)
            with BodyLoop(session) as loop:
                host = BodyAPIHost(loop, mode='bounded', target_cycles=1,
                                   max_calls=protocol['max_tool_calls_per_run'])
                forecast = host.admission_assessment('walk', protocol['duration_s'], head)
                if mode == 'enforce' and forecast['recommendation'] != 'request_walk':
                    raise RuntimeError('verified experience does not yet authorize the enforced walk')
            # APIRecovery supplies its own saved-goal input. Use a persistent
            # host instruction extension in the worker, not discarded initial text.
            api_dir = directory/'api'
            cli(directory, 'api', ['api', '--session', str(session), '--api-mode', 'bounded',
                '--target-cycles', '1', '--model', protocol['model'], '--max-calls', str(protocol['max_tool_calls_per_run']),
                '--timeout-seconds', str(protocol['timeout_seconds_per_run']), '--output-dir', str(api_dir)])
            summary = json.loads((api_dir/'summary.json').read_text())
            with BodyLoop(session) as loop:
                records = loop.records()
                tools = [dict(row) for row in loop.engine.db.execute(
                    'SELECT tool,status,result FROM body_api_calls ORDER BY rowid')]
                public_tools = []
                for tool in tools:
                    response = json.loads(tool['result']) if tool['result'] else {}
                    item = dict(tool=tool['tool'], status=tool['status'], success=response.get('success'))
                    if tool['tool'] == 'assess_body_action' and response.get('success'):
                        item['assessment'] = json.loads(response['output'])
                    public_tools.append(item)
                row = dict(index=index+1, mode=mode, status=summary['status'],
                    integration_sha256=integration_sources(),
                    live_api_verified=summary['live_api_verified'], cleanup_status=summary['cleanup_status'],
                    goal_reached=summary['evaluation']['goal_reached'],
                    initial_checkpoint_sha256=head, final_checkpoint_sha256=loop.body().checkpoint()['sha256'],
                    completed_cycles=loop.status()['completed_cycles'],
                    forecast_before=forecast, tools=public_tools,
                    actions=[BodyAPIHost.public_receipt(loop.receipt(r, replayed=True),
                        max(r['request']['actions'], key=lambda c:c['score']['respect'])['body_action']) for r in records],
                    learned_episodes=loop.metacognition.overview()['learned_episodes'])
                result['rows'].append(row)
                save(out/'results.json', result)
                valid = (summary['status'] == 'completed' and summary['live_api_verified'] and row['goal_reached'] and
                    summary['cleanup_status'] == 'deleted' and row['completed_cycles'] == 1 and len(records) == 1 and
                    any(t['tool'] == 'assess_body_action' and t['success'] for t in public_tools) and
                    row['actions'][0]['requested_action'] == 'walk' and row['actions'][0]['actual_action'] == 'walk' and
                    row['actions'][0]['metacognition']['duration_s'] == protocol['duration_s'])
                if not valid:
                    raise RuntimeError('live acceptance condition not met; no additional run started')
            last_session = session
        cold_path = out/'cold-replay.json'
        subprocess.run([sys.executable, '-m', 'examples.nasuraya_body_loop.run_metacognitive_api', 'cold',
            '--session', str(last_session), '--model', protocol['model'], '--output', str(cold_path)], cwd=ROOT, check=True)
        result.update(status='completed', cold_replay=json.loads(cold_path.read_text()),
            native_source_files_unchanged=verified_sources() == native,
            learned_episodes=SelfModel(memory).verify()['episodes'],
            native_cycles_total=sum(r['completed_cycles'] for r in result['rows']),
            all_remote_sessions_deleted=all(r['cleanup_status'] == 'deleted' for r in result['rows']))
        if not result['native_source_files_unchanged'] or result['learned_episodes'] != 4:
            raise AssertionError('native source or learning count changed unexpectedly')
    except Exception as error:
        result.update(status='blocked', blocker_type=type(error).__name__, blocker=str(error))
        save(out/'results.json', result)
        raise
    save(out/'results.json', result)
    print(json.dumps(dict(status=result['status'], native_cycles=result['native_cycles_total'],
        learned_episodes=result['learned_episodes'], cold_replay=result['cold_replay']), indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('live', 'cold'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--session')
    parser.add_argument('--model', default='gpt-6-astra')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.mode == 'cold':
        cold(args.session, args.model, args.output)
    else:
        live(args.output, resume=args.resume)
