"""Bounded, reproducible 2-vs-4 test of REAL Nasuraya repository jobs.

Linux / Python 3.12+, no pip, no paid API. Writes only below --workspace.
This is a single-host measurement, NOT a distributed/ten-machine test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sqlite3
import subprocess
import sys
import time

from . import engine, worker


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_in(directory: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(directory)): (sha(p), p.stat().st_mtime_ns)
        for p in sorted(directory.rglob('command-*.log'))
        if p.is_file()
    }


def run_args(root: Path, workspace: Path, run_id: str, slots: int) -> list[str]:
    return [sys.executable, '-m', 'nasuraya_agent_network', 'run',
            '--root', str(root), '--workspace', str(workspace),
            '--run-id', run_id, '--max-workers', str(slots)]


def process_tree_rss_kib(root_pid: int) -> tuple[int, int]:
    """Sample summed /proc RSS (shared pages double-counted), never call it PSS."""
    pages = {}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            raw = (p / 'stat').read_text()
            rest = raw.rsplit(')', 1)[1].split()
            pages[int(p.name)] = (int(rest[1]), int(rest[21]))
        except (OSError, ValueError, IndexError):
            continue
    members = {root_pid}
    while True:
        extra = {pid for pid, (ppid, _) in pages.items() if ppid in members}
        if extra <= members:
            break
        members |= extra
    rss_kib = sum(max(0, pages[pid][1]) * os.sysconf('SC_PAGE_SIZE') // 1024
                  for pid in members if pid in pages)
    return rss_kib, len(members)


def running_claims(workspace: Path, run_id: str) -> int:
    path = workspace / 'ledger.sqlite'
    if not path.exists():
        return 0
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=0.1) as db:
            return db.execute(
                "SELECT count(*) FROM jobs WHERE run_id=? AND status='running'",
                (run_id,)).fetchone()[0]
    except sqlite3.Error:
        return 0


def measured_run(root: Path, workspace: Path, run_id: str, slots: int) -> dict:
    workspace.mkdir(parents=True, exist_ok=False)
    command = run_args(root, workspace, run_id, slots)
    # Verify STOP is fail-closed before a run is claimed.
    (workspace / 'STOP').touch()
    blocked = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert blocked.returncode != 0 and 'paused' in blocked.stdout, 'STOP not enforced'
    assert running_claims(workspace, run_id) == 0
    with sqlite3.connect(workspace / 'ledger.sqlite') as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
    (workspace / 'STOP').unlink()

    stdout_file = workspace / 'first.json'
    stderr_file = workspace / 'first.stderr'
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.monotonic()
    peak_rss, peak_tree, peak_claims = 0, 0, 0
    with stdout_file.open('wb') as stdout, stderr_file.open('wb') as stderr:
        proc = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr)
        try:
            while proc.poll() is None:
                if time.monotonic() - t0 > 225:
                    raise TimeoutError('bounded probe exceeded 225 seconds')
                rss, n = process_tree_rss_kib(proc.pid)
                peak_rss, peak_tree = max(peak_rss, rss), max(peak_tree, n)
                peak_claims = max(peak_claims, running_claims(workspace, run_id))
                time.sleep(.12)
        finally:
            if proc.poll() is None:
                # Avoid leaving a test coordinator after a budget overrun.
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        ret = proc.wait()
    wall = time.monotonic() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    # A failed native run is an important scale result, not a probe crash.
    # Still audit its terminal ledger, durable receipts, and cold replay.
    if ret not in (0, 1):
        raise RuntimeError(f'coordinator exit={ret}: {stderr_file.read_text()[-1400:]}')
    report = json.loads(stdout_file.read_text())
    assert report['status'] in ('passed', 'failed')
    assert (ret == 0) is (report['status'] == 'passed')
    assert report['reviewer']['passed'] is (report['status'] == 'passed')
    assert report['model_api_calls'] == 0
    assert set(report['workers']) == set(worker.ROLES)
    assert all(r['model_api_calls'] == 0 for r in report['workers'].values())
    assert all(r['network_syscalls_denied'] is True for r in report['workers'].values()
               if r['passed'] is True)
    assert peak_claims <= slots

    # Distinct receipts must be durable; replay must not launch a worker.
    log_dir = workspace / run_id
    receipts_before = files_in(log_dir)
    assert receipts_before, 'no command receipts'
    with sqlite3.connect(workspace / 'ledger.sqlite') as db:
        jobs_before = db.execute('SELECT agent,status,receipt FROM jobs ORDER BY agent').fetchall()
        assert len(jobs_before) == len(worker.ROLES) + 1
        assert all(status in ('completed', 'failed') for _, status, _ in jobs_before)
    replay_file = workspace / 'replay.json'
    with replay_file.open('wb') as stdout:
        second = subprocess.run(command, cwd=root, stdout=stdout, stderr=subprocess.PIPE, timeout=30)
    assert second.returncode == ret, second.stderr.decode(errors='replace')
    assert json.loads(replay_file.read_text()) == report
    assert receipts_before == files_in(log_dir), 'replay modified command receipts'
    with sqlite3.connect(workspace / 'ledger.sqlite') as db:
        assert db.execute('SELECT agent,status,receipt FROM jobs ORDER BY agent').fetchall() == jobs_before

    # Run identity binds concurrency; accidental cross-config replay must fail.
    other = 4 if slots == 2 else 2
    drift = subprocess.run(run_args(root, workspace, run_id, other),
                           cwd=root, capture_output=True, text=True, timeout=30)
    assert drift.returncode != 0 and 'different source or configuration' in drift.stdout
    assert receipts_before == files_in(log_dir)
    storage = sum(p.stat().st_size for p in workspace.rglob('*') if p.is_file())
    return {
        'slots': slots, 'role_count': len(worker.ROLES),
        'wall_seconds': round(wall, 3),
        'peak_sampled_summed_rss_mib': round(peak_rss / 1024, 2),
        'peak_sampled_process_tree_size': peak_tree,
        'peak_running_role_claims': peak_claims,
        'coordinator_child_user_cpu_seconds': round(after.ru_utime - before.ru_utime, 3),
        'coordinator_child_system_cpu_seconds': round(after.ru_stime - before.ru_stime, 3),
        # ru_maxrss is a historical max over children, so omit it from paired comparison.
        'workspace_bytes': storage, 'source_sha256': report['source_sha256'],
        'implementation_sha256': report['implementation_sha256'],
        'worker_elapsed_seconds': {k: r['elapsed_seconds'] for k, r in report['workers'].items()},
        'worker_log_count': len(receipts_before),
        'status': report['status'],
        'successful_roles': sum(r['passed'] is True for r in report['workers'].values()),
        'failed_roles': {role: {'error': r.get('error'),
                               'commands': [{'returncode': c.get('returncode'),
                                             'interrupted': c.get('interrupted')}
                                            for c in r.get('commands', [])]}
                         for role, r in report['workers'].items() if r['passed'] is not True},
        'all_jobs_terminal': True, 'cold_replay_identical': True,
        'receipts_hash_and_mtime_unchanged': True,
        'different_slot_replay_rejected': True,
        'pause_before_claim_rejected': True,
    }


CRASH_CODE = """
import sys, time
from pathlib import Path
from nasuraya_agent_network import engine, worker
def slow_worker(*args):
    time.sleep(30)
worker.execute = slow_worker
engine.run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
"""


def crash_recovery(root: Path, base: Path, slots: int) -> dict:
    """SIGKILL a real coordinator after exactly 'slots' synthetic claims.

    Mock only the sleeping tasks, not the SQLite/locking/claim machinery.
    No expensive real jobs are killed or orphaned by this test.
    """
    fixture = base / f'fixture-{slots}'
    (fixture / 'examples').mkdir(parents=True)
    (fixture / 'examples' / 'dummy.txt').write_text('immutable synthetic fixture\n')
    workspace = base / f'crash-{slots}'
    run_id = f'crash-{slots}'
    proc = subprocess.Popen([sys.executable, '-c', CRASH_CODE,
                             str(fixture), str(workspace), run_id, str(slots)],
                            cwd=root, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    observed = 0
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError('synthetic coordinator exited before claim')
            observed = max(observed, running_claims(workspace, run_id))
            if observed == slots:
                break
            time.sleep(.05)
        assert observed == slots, f'expected {slots} running claims, saw {observed}'
    finally:
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=6)
    with sqlite3.connect(workspace / 'ledger.sqlite') as db:
        first = db.execute('SELECT id,fingerprint,status,report FROM runs').fetchall()
        jobs = db.execute('SELECT agent,status,receipt FROM jobs ORDER BY agent').fetchall()
    assert len(first) == 1 and first[0][2] == 'running'
    assert sum(1 for _, state, _ in jobs if state == 'running') == slots
    try:
        engine.run(fixture, workspace, run_id, slots)
    except RuntimeError as e:
        assert 'unfinished run requires review' in str(e)
    else:
        raise AssertionError('unsafe automatic replay after coordinator SIGKILL')
    with sqlite3.connect(workspace / 'ledger.sqlite') as db:
        assert first == db.execute('SELECT id,fingerprint,status,report FROM runs').fetchall()
        assert jobs == db.execute('SELECT agent,status,receipt FROM jobs ORDER BY agent').fetchall()
    return {'slots': slots, 'claims_before_sigkill': observed,
            'inflight_state_preserved': True, 'automatic_retry_blocked': True,
            'real_workers_used_for_crash': False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    root, base = args.root.resolve(), args.workspace.resolve()
    if root.is_relative_to(base) or base.is_relative_to(root):
        raise ValueError('workspace must be outside source tree')
    base.mkdir(parents=True, exist_ok=False)
    result = {
        'schema': 'nasuraya-network-single-host-scale-probe/1',
        'base_sha': os.environ.get('GITHUB_SHA', 'local-unset'),
        'host_scope': 'one ephemeral GitHub Actions Ubuntu runner',
        'roles': list(worker.ROLES),
        'benchmark': [],
        'controlled_sigkill': [],
        'limits': ['not a multi-host queue', 'not ten workers',
                   'RSS sums shared pages and is sampled, not PSS',
                   'CPU rusage is direct coordinator child only, not all descendants'],
    }
    for slots in (2, 4):
        result['benchmark'].append(measured_run(root, base / f'real-{slots}',
                                                f'real-{slots}', slots))
        result['controlled_sigkill'].append(crash_recovery(root, base, slots))
        (base / 'scale-results.json').write_text(json.dumps(
            result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    two, four = result['benchmark']
    if two['status'] == four['status'] == 'passed':
        result['speedup_2_over_4'] = round(two['wall_seconds'] / four['wall_seconds'], 3)
        result['time_saved_percent'] = round(
            100 * (two['wall_seconds'] - four['wall_seconds']) / two['wall_seconds'], 2)
    else:
        result['speedup_2_over_4'] = None
        result['time_saved_percent'] = None
        result['comparison_note'] = 'Failed runs do not count as completed throughput.'
    (base / 'scale-results.json').write_text(json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'wall_s_2': two['wall_seconds'], 'wall_s_4': four['wall_seconds'],
                      'status_2': two['status'], 'status_4': four['status'],
                      'speedup': result['speedup_2_over_4'],
                      'roles': result['roles'], 'receipts_valid': True,
                      'sigkill_fail_closed': True}, sort_keys=True))


if __name__ == '__main__':
    main()
