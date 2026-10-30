"""Fixed repository jobs, disposable copies, sanitized environment, no API adapter.

The reviewed repository code is trusted. Network denial is enforced by libseccomp,
not by a Python monkeypatch. This is NOT an adversarial filesystem/container sandbox.
"""
from __future__ import annotations
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import time

ROLES = ('body', 'memory', 'genome', 'research', 'self_model')
MAX_LOG = 2 * 1024 * 1024
TASK_SECONDS = 90
SELF_MODEL_WALL_SECONDS = 130  # 64 frozen synthetic body cycles; still bound by total run budget


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commands(role: str, output: Path) -> list[list[str]]:
    body = ['-m', 'examples.nasuraya_body_loop']
    genome = ['-m', 'examples.nasuraya_genome.history']
    plans = {
        'body': [body + ['test'], body + ['demo', '--fixture', 'sleep', '--steps', '3',
                 '--max-actions', '12', '--output-dir', str(output / 'body')]],
        'memory': [body + ['experience-test'], body + ['experience-demo', '--output-dir', str(output / 'memory')]],
        'genome': [['-m', 'unittest', 'discover', '-s', 'examples/nasuraya_genome', '-t', '.', '-v'],
                   genome + ['--demo-output', str(output / 'history.json')],
                   genome + ['--verify', str(output / 'history.json')]],
        'research': [['-m', 'examples.nasuraya_agent_loop.evaluate_grid', '--output', str(output / 'grid.json')]],
        'self_model': [body + ['self-knowledge-eval', '--output-dir', str(output / 'self_model')]],
    }
    return plans[role]


def deny_network() -> None:
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('seccomp initialization failed')
    try:
        for name in ('socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
                     'sendto', 'recvfrom', 'sendmsg', 'recvmsg', 'sendmmsg', 'recvmmsg'):
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number < 0 or lib.seccomp_rule_add(ctx, 0x50000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError('network restriction unavailable')
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError('network restriction failed')
    finally:
        lib.seccomp_release(ctx)
    try:
        socket.socket()
    except OSError as exc:
        if exc.errno != errno.EPERM:
            raise
    else:
        raise RuntimeError('network restriction self-test failed')


def child(argv: list[str]) -> None:
    root, *command = argv
    deny_network()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_LOG, MAX_LOG))
    resource.setrlimit(resource.RLIMIT_CPU, (TASK_SECONDS, TASK_SECONDS))
    if len(command) < 2 or command[0] != '-m':
        raise ValueError('module command required')
    sys.path.insert(0, root)
    sys.argv = command[1:]
    print('NASURAYA_NETWORK_DENIED=1', flush=True)
    runpy.run_module(command[1], run_name='__main__', alter_sys=True)


def stop_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def metrics(role: str, output: Path) -> dict:
    if role == 'body':
        data = json.loads((output / 'body/summary.json').read_text())
        if (data['completed_cycles'] != 3 or data['actions_remaining'] != 9
                or data['external_model_api_used'] is not False):
            raise ValueError('body evidence mismatch')
        rows = [json.loads(line) for line in (output / 'body/events.jsonl').read_text().splitlines()]
        if [r['outcome']['actual_action'] for r in rows] != ['protect', 'observe', 'observe']:
            raise ValueError('body action receipts mismatch')
        errors = [r['outcome']['body_audit']['energy_error_J'] for r in rows]
        if not all(type(e) in (float, int) and math.isfinite(e) and abs(e) < 1e-6 for e in errors):
            raise ValueError('body energy audit failed')
        return {'native_cycles': 3, 'actions_remaining': 9, 'energy_audit_passed': True}
    if role == 'memory':
        data = json.loads((output / 'memory/summary.json').read_text())
        if data['native_cycles'] != 6 or data['model_api_calls'] != 0:
            raise ValueError('memory evidence mismatch')
        if set(data['sessions']) != {'normal', 'sleep'} or any(s['cold_reopen_equal'] is not True for s in data['sessions'].values()):
            raise ValueError('memory recovery mismatch')
        return {'native_cycles': 6, 'cold_reopen_equal': True}
    if role == 'research':
        data = json.loads((output / 'grid.json').read_text())
        if data['cases'] != 484 or data['completed'] != 484 or data['violations'] != 0:
            raise ValueError('research grid mismatch')
        return {'cases': 484, 'completed': 484, 'violations': 0}
    if role == 'self_model':
        data = json.loads((output / 'self_model/summary.json').read_text())
        required_checks = {
            'all_native_cycles_completed', 'no_failed_or_unresolved',
            'budgets_exhausted', 'expected_split', 'complete_unique_trials',
            'forecasts_preserved', 'expected_training', 'training_is_warmup_only',
            'frozen_training', 'protocol_preserved', 'fixed_trial_order',
            'scores_match_frozen_forecasts', 'forecasts_match_prior_evidence',
            'prior_evidence_stamps_match',
        }
        checks = data.get('validation_checks')
        if (data.get('schema') != 'nasuraya-self-knowledge-evaluation/1'
                or data.get('validation_passed') is not True
                or not isinstance(checks, dict)
                or not required_checks.issubset(checks)
                or any(checks[name] is not True for name in required_checks)):
            raise ValueError('self-model frozen validation failed')
        warmup, holdout = data['warmup'], data['holdout']
        if (data['actual_native_cycles'] != 64
                or data['expected_native_cycles'] != 64
                or data['training_receipts'] != 40
                or warmup['attempted'] != 40 or warmup['scored'] != 40
                or holdout['attempted'] != 24 or holdout['scored'] != 24
                or holdout['failed_or_unresolved'] != 0
                or holdout['supported'] != 24
                or data['all_forecasts_reserved_before_execution'] is not True
                or data['holdout_outcomes_used_for_fitting'] is not False
                or data['model_api_calls'] != 0
                or data['physical_actuator_calls'] != 0):
            raise ValueError('self-model sample or isolation contract failed')
        measures = ('mean_brier', 'mean_pooled_brier',
                    'mean_shuffled_context_brier', 'mean_zero_history_brier')
        scores = {name: holdout[name] for name in measures}
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2
               for value in scores.values()):
            raise ValueError('self-model Brier metrics invalid')
        delta = scores['mean_pooled_brier'] - scores['mean_brier']
        recorded = data['heldout_brier_improvement_absolute']
        if (type(recorded) not in (float, int) or not math.isfinite(recorded)
                or not math.isclose(delta, recorded, rel_tol=0., abs_tol=1e-10)
                or data['context_helped_on_this_constructed_holdout'] is not (delta > 0)):
            raise ValueError('self-model control comparison inconsistent')
        return {'native_cycles': 64, 'training_receipts': 40, 'heldout_trials': 24,
                'context_brier': scores['mean_brier'],
                'pooled_brier': scores['mean_pooled_brier'],
                'shuffled_context_brier': scores['mean_shuffled_context_brier'],
                'zero_history_brier': scores['mean_zero_history_brier'],
                'pooled_minus_context_brier': delta,
                'context_helped_on_constructed_holdout': delta > 0,
                'scope': 'two synthetic fixtures; forecasting only, not consciousness'}
    history = output / 'history.json'
    json.loads(history.read_text())
    return {'history_verified_by_cli': True, 'history_sha256': digest(history)}


def execute(role: str, snapshot: Path, output: Path, stop: Path, deadline: float) -> dict:
    """Run a fixed specialist plan; any missing evidence fails the task."""
    if role not in ROLES:
        raise ValueError('unknown role')
    started = time.monotonic()
    receipts = []
    result = {'agent': role, 'passed': False, 'commands': receipts,
              'network_syscalls_denied': False, 'model_api_calls': 0}
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    shutil.copytree(snapshot, source)
    home, temp = output / 'home', output / 'tmp'
    home.mkdir(); temp.mkdir()
    env = {'PATH': os.defpath, 'HOME': str(home), 'TMPDIR': str(temp),
           'PYTHONPATH': str(source), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    wall_limit = SELF_MODEL_WALL_SECONDS if role == 'self_model' else TASK_SECONDS
    deadline = min(deadline, started + wall_limit)
    try:
        for index, command in enumerate(commands(role, output)):
            if stop.exists() or time.monotonic() >= deadline:
                raise RuntimeError('stopped or time budget exhausted')
            log_path = output / f'command-{index}.log'
            with log_path.open('xb') as log:
                process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), str(source), *command],
                    cwd=source, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True, close_fds=True)
                reason = None
                try:
                    while process.poll() is None:
                        if stop.exists() or time.monotonic() >= deadline:
                            reason = 'stopped' if stop.exists() else 'timeout'
                            break
                        if log_path.stat().st_size > MAX_LOG:
                            reason = 'output_limit'
                            break
                        time.sleep(.025)
                finally:
                    # Also reap descendants if a module exits before its child.
                    stop_group(process)
            raw = log_path.read_bytes()
            denied = b'NASURAYA_NETWORK_DENIED=1\n' in raw
            receipts.append({'argv': command, 'returncode': process.returncode, 'interrupted': reason,
                             'log': log_path.name, 'log_sha256': hashlib.sha256(raw).hexdigest(),
                             'network_syscalls_denied': denied})
            if reason or process.returncode != 0 or not denied:
                raise RuntimeError(reason or 'command failed or restriction not established')
        result['metrics'] = metrics(role, output)
        result['passed'] = True
        result['network_syscalls_denied'] = True
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:250]
    finally:
        result['elapsed_seconds'] = round(time.monotonic() - started, 4)
        shutil.rmtree(source)
        shutil.rmtree(home)
        shutil.rmtree(temp)
    return result


if __name__ == '__main__':
    child(sys.argv[1:])
