"""Independent Linux installed-wheel/crash evidence under syscall network denial.

libseccomp is a verifier-only host prerequisite, never a runtime dependency.
Fault hooks exist only in this verification driver, not the local-job CLI.
"""
import argparse
import ctypes
import errno
import hashlib
import json
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import time
import venv

START = '2026-10-16T10:22:23Z'
DUE = '2026-10-17T10:22:23Z'
LATER = '2026-10-18T10:22:23Z'


def deny_network():
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)  # Allow everything except listed network syscalls.
    if not ctx: raise RuntimeError('seccomp init failed')
    denied = ['socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
              'sendto', 'recvfrom', 'sendmsg', 'recvmsg', 'sendmmsg', 'recvmmsg']
    try:
        for name in denied:
            syscall = lib.seccomp_syscall_resolve_name(name.encode())
            if syscall < 0 or lib.seccomp_rule_add(ctx, 0x50000 | errno.EPERM, syscall, 0) != 0:
                raise RuntimeError('seccomp rule failed: '+name)
        if lib.seccomp_load(ctx) != 0: raise RuntimeError('seccomp load failed')
    finally: lib.seccomp_release(ctx)
    try: socket.socket()
    except OSError as exc: assert exc.errno == errno.EPERM
    else: raise AssertionError('network socket unexpectedly permitted')
    return denied


# Separate child: use installed package; pause at real termination boundaries.
CRASH_WORKER = r'''
import json, pathlib, signal, sys
from unittest.mock import patch
from nasuraya_continuity_kit.store import Store
from nasuraya_continuity_kit.local_job import LocalJobs
import nasuraya_continuity_kit.local_job as module
path, phase, marker, source = sys.argv[1:]
store = Store(path)
jobs = LocalJobs(store)
raw = pathlib.Path(source).read_bytes()
def stop():
    pathlib.Path(marker).write_text(phase)
    signal.pause()
if phase == 'after_claim':
    jobs._complete = lambda *args: stop()
elif phase == 'after_compute':
    original = module.integrity_report
    def report(raw):
        result = original(raw)
        stop()
        return result
    module.integrity_report = report
elif phase == 'after_commit':
    original = jobs._complete
    def complete(*args):
        result = original(*args)
        stop()
        return result
    jobs._complete = complete
elif phase == 'after_result_write':
    original = store._apply_in_transaction
    def transition(operation, *args):
        if operation == 'finish':
            stop()  # Result UPDATE is uncommitted inside the active transaction.
        return original(operation, *args)
    store._apply_in_transaction = transition
jobs.run('request1', 'run1', '2026-10-17T10:22:23Z', raw)
'''


def verify(wheel, output):
    denied = deny_network()  # Inherited by venv, pip and EVERY probe child.
    wheel, out = Path(wheel).resolve(), Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = out/'env'
    venv.EnvBuilder(with_pip=True).create(env)
    py = env/'bin/python'
    with (out/'installation.txt').open('w') as log:
        subprocess.run([str(py), '-I', '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)],
                       cwd=out, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=60)
    imports = json.loads(subprocess.check_output([str(py), '-I', '-c',
        'import nasuraya_continuity_kit.local_job as j,continuity.gate as g,json;print(json.dumps([j.__file__,g.__file__]))'],
        cwd=out, text=True))
    assert all(str(env) in item for item in imports)
    # Assert the inherited restriction in a fresh installed interpreter too.
    probe = "import socket,errno\ntry: socket.socket()\nexcept OSError as e: assert e.errno==errno.EPERM\nelse: raise AssertionError('network allowed')\nprint('EPERM')"
    assert subprocess.check_output([str(py), '-I', '-c', probe], cwd=out, text=True).strip() == 'EPERM'
    raw = '["abc", "", "سلام"]'.encode('utf-8')
    source = out/'input.json'
    source.write_bytes(raw)
    log = []

    def cli(db, operation, *extra, now=DUE, code=0, forbid_compute=False):
        if forbid_compute:
            script = "import nasuraya_continuity_kit.local_job as j; j.integrity_report=lambda *a: (_ for _ in ()).throw(AssertionError('report computation forbidden on replay')); from nasuraya_continuity_kit.cli import main; raise SystemExit(main())"
            launch = [str(py), '-I', '-c', script]
        else:
            launch = [str(py), '-I', '-m', 'nasuraya_continuity_kit.cli']
        args = [*launch, operation,
                '--db', str(db), '--now', now, *extra]
        proc = subprocess.run(args, cwd=out, text=True, capture_output=True, timeout=10)
        assert proc.returncode == code, (args, proc.stdout, proc.stderr)
        result = json.loads(proc.stdout if code == 0 else proc.stderr)
        log.append(dict(db=db.name, operation=operation, arguments=list(extra), now=now,
                        exit_code=proc.returncode, report_computation_forbidden=forbid_compute, output=result))
        return result

    def run(db, code=0, forbid_compute=False):
        return cli(db, 'run-local', '--request-id', 'request1', '--run-id', 'run1', '--input', str(source),
                   code=code, forbid_compute=forbid_compute)

    def audit(db, expected_status):
        # Independent reader: do not import or call the implementation under test.
        conn = sqlite3.connect(db)
        try:
            assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            rows = conn.execute('SELECT input,status,result FROM local_jobs').fetchall()
            assert len(rows) == 1
            snapshot, status, result = rows[0]
            assert status == expected_status and snapshot == raw
            control = json.loads(conn.execute('SELECT payload FROM control').fetchone()[0])
            assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 1
            if status == 'completed':
                expected = dict(schema='nasuraya-local-integrity/1', input_sha256=hashlib.sha256(raw).hexdigest(),
                    input_bytes=len(raw), record_count=3, utf8_bytes=11,
                    record_sha256=[hashlib.sha256(s.encode()).hexdigest() for s in ['abc','','سلام']])
                assert json.loads(result) == expected
                assert control['inflight_run_id'] is None
                assert conn.execute('SELECT count(*) FROM requests').fetchone()[0] == 2
            elif status == 'running':
                assert result is None and control['inflight_run_id'] == 'run1'
                assert conn.execute('SELECT count(*) FROM requests').fetchone()[0] == 1
            else:
                assert result is None and control['inflight_run_id'] is None
                assert conn.execute('SELECT count(*) FROM requests').fetchone()[0] == 2
        finally: conn.close()

    db = out/'normal.sqlite'
    cli(db, 'init', now=START)
    early = cli(db, 'run-local', '--request-id','early','--run-id','early','--input',str(source),now=START,code=2)
    assert early['error'] == 'recent_contact'
    first = run(db)
    assert first['result']['status'] == 'completed'
    audit(db, 'completed')
    assert run(db, forbid_compute=True) == first
    # Mutating the same file cannot turn the historical receipt into new work.
    source.write_bytes(b'[]')
    assert 'different local parameters' in run(db, code=2)['error']
    source.write_bytes(raw)
    assert cli(db, 'status')['result']['decision']['reason'] == 'daily_budget_used'
    # A caller can legitimately use the legacy internal finish ID as its claim
    # ID. Verify a fresh installed process completes, then cold-replays without
    # computation; independently audit the committed report and both receipts.
    db = out/'colliding-request.sqlite'
    cli(db, 'init', now=START)
    collision = 'local-finish-'+hashlib.sha256(b'run1').hexdigest()
    args = ('--request-id', collision, '--run-id', 'run1', '--input', str(source))
    completed = cli(db, 'run-local', *args)
    assert completed['result']['status'] == 'completed'
    audit(db, 'completed')
    assert cli(db, 'run-local', *args, forbid_compute=True) == completed
    audit(db, 'completed')
    crashes = []
    for phase in ['after_claim', 'after_compute', 'after_result_write', 'after_commit']:
        db = out/(phase+'.sqlite')
        cli(db, 'init', now=START)
        marker = out/(phase+'.ready')
        proc = subprocess.Popen([str(py), '-I', '-c', CRASH_WORKER, str(db), phase, str(marker), str(source)],
                                cwd=out, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic()+10
            while not marker.exists() and time.monotonic() < deadline and proc.poll() is None:
                time.sleep(0.02)
            assert marker.exists(), (phase, proc.poll())
            proc.kill()  # Actual SIGKILL, not a simulated exception or graceful close.
            stdout, stderr = proc.communicate(timeout=10)
            assert proc.returncode == -signal.SIGKILL, (stdout, stderr)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.communicate(timeout=10)
        if phase == 'after_commit':
            audit(db, 'completed')
            replay = run(db, forbid_compute=True)
            assert replay['result'] == first['result']
            audit(db, 'completed')
        else:
            audit(db, 'running')
            assert 'outcome unknown' in run(db, code=2, forbid_compute=True)['error']
            assert 'unresolved_previous_run' in cli(db, 'run-local','--request-id','new','--run-id','new',
                        '--input',str(source),now=LATER,code=2)['error']
            assert 'host reconciliation' in cli(db,'finish','--request-id','bypass','--run-id','run1',code=2)['error']
            assert 'attestation' in cli(db,'abandon-local','--request-id','review','--run-id','run1',
                        '--operator','verifier-host','--evidence','SIGKILL confirmed and child reaped',code=2)['error']
            cli(db,'abandon-local','--request-id','review','--run-id','run1','--operator','verifier-host',
                '--evidence','SIGKILL confirmed and child reaped','--worker-stopped')
            audit(db, 'abandoned')
            assert run(db, forbid_compute=True)['result']['status'] == 'abandoned'
            assert cli(db,'status')['result']['decision']['reason'] == 'daily_budget_used'
        crashes.append(dict(phase=phase, signal='SIGKILL', exit_code=proc.returncode,
                            sqlite_integrity='ok', replay_did_not_reexecute=True))
    result = dict(passed=True, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        installed_imports=imports, denied_network_syscalls=denied, inherited_socket_probe='EPERM',
        fresh_process_cli_invocations=len(log), actual_killed_workers=crashes, log=log,
        limitations=['Injected fixture clock; no 24-hour wait', 'Trusted local operator/time',
                    'No scheduler daemon or physical/network effects', 'Only SQLite report publication tested'])
    (out/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--wheel', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = verify(args.wheel, args.output)
    print(json.dumps({k: result[k] for k in ['passed','wheel_sha256','fresh_process_cli_invocations','actual_killed_workers']}))
