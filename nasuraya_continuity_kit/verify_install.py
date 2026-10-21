"""Offline installed-wheel checks in fresh processes, outside the source tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import venv
import zipfile


def verify(wheel, output):
    wheel = Path(wheel).resolve()
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert archive.testzip() is None
        assert 'continuity/gate.py' in names
        assert all(not n.endswith('.json') and 'test_' not in n for n in names)
        assert not any(n.startswith(('project_fund/', 'runtimes/', 'examples/')) for n in names)
    env = out/'env'
    venv.EnvBuilder(with_pip=True).create(env)
    py = env/'bin/python'
    cli = env/'bin/nasuraya-continuity'
    subprocess.run([str(py), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], cwd=out, check=True,
                   stdout=(out/'installation.txt').open('w'), stderr=subprocess.STDOUT)
    imported = json.loads(subprocess.check_output([str(py), '-I', '-c',
        'import continuity.gate,nasuraya_continuity_kit,json;print(json.dumps([continuity.gate.__file__,nasuraya_continuity_kit.__file__]))'], cwd=out, text=True))
    assert all(str(env) in path for path in imported), imported
    log = []
    db = out/'synthetic.sqlite'

    def command(op, now, request=None, run=None, code=0):
        args = [str(cli), op, '--db', str(db), '--now', now]
        if request: args += ['--request-id', request]
        if run: args += ['--run-id', run]
        response = subprocess.run(args, cwd=out, capture_output=True, text=True)
        assert response.returncode == code, response.stderr
        value = json.loads(response.stdout if code == 0 else response.stderr)
        log.append(dict(operation=op, time=now, returncode=response.returncode, output=value))
        return value

    command('init', '2026-10-16T10:22:23Z')
    command('claim', '2026-10-17T10:22:22Z', 'early', 'run1', code=2)
    first = command('claim', '2026-10-17T10:22:23Z', 'claim1', 'run1')
    assert command('claim', '2026-10-17T10:22:23Z', 'claim1', 'run1') == first
    status = command('status', '2026-10-17T10:23:23Z')['result']
    assert status['request_count'] == status['run_count'] == 1
    assert status['decision']['reason'] == 'unresolved_previous_run'
    command('claim', '2026-10-17T10:23:23Z', 'claim2', 'run2', code=2)
    command('finish', '2026-10-17T10:23:23Z', 'finish1', 'run1')
    assert command('status', '2026-10-18T10:22:22Z')['result']['decision']['reason'] == 'daily_budget_used'
    assert command('status', '2026-10-18T10:22:23Z')['result']['decision']['eligible']
    command('pause', '2026-10-18T10:22:23Z', 'pause1')
    assert command('status', '2026-10-19T10:22:23Z')['result']['decision']['reason'] == 'paused'
    result = dict(passed=True, fresh_process_cli_invocations=len(log), installed_imports=imported,
                  wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), wheel_entries=names,
                  scope='local installed-wheel behavior on injected-clock fixtures; no jobs or payments executed', log=log)
    (out/'results.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--wheel', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = verify(args.wheel, args.output)
    print(json.dumps({k:result[k] for k in ('passed', 'fresh_process_cli_invocations', 'wheel_sha256')}))
