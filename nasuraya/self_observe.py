"""Read the existing native body through its audit and the Zohraya projection.

The observer restores a checkpoint in an isolated, credential-free process.
It never opens the mutable BodyLoop/ReflectionCycle hosts, saves a checkpoint,
or advances simulated time. Freshness is relative to an explicit simulation
clock, never an inference that a saved simulation is current in the real world.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

from examples.nasuraya_body_loop.__main__ import ROOT, SOURCE, verified_sources


WORKER = """
import json, sys
from unified_body_v2 import UnifiedBody
from audit_self_model import assess
from zohraya.self_model import SelfModel
request = json.load(sys.stdin)
body = UnifiedBody.restore(request['checkpoint'])
before = body.checkpoint()
audit = assess(body, at_simulated_s=request['at_simulated_s'])
telemetry = SelfModel(request['agent_id']).get_telemetry(audit)
if body.checkpoint() != before or before != request['checkpoint']:
    raise ValueError('observer changed the native checkpoint')
print(json.dumps(dict(schema='nasuraya.self-observation/1',
    checkpoint_sha256=before['sha256'], audit=audit, telemetry=telemetry,
    native_checkpoint_unchanged=True, simulated_cycles_executed=0,
    external_api_calls=0), allow_nan=False, sort_keys=True))
"""


def observe_checkpoint(checkpoint, *, at_simulated_s=None, agent_id='NASURAYA'):
    """Derive telemetry from a source-verified native checkpoint without writes."""
    if at_simulated_s is not None and (type(at_simulated_s) not in (int, float)
            or not math.isfinite(at_simulated_s)):
        raise ValueError('evaluation clock must be finite simulated seconds')
    payload = json.dumps(dict(checkpoint=checkpoint, at_simulated_s=at_simulated_s,
                              agent_id=agent_id), allow_nan=False)
    manifest = verified_sources()
    with tempfile.TemporaryDirectory(prefix='nasuraya-self-observer-') as directory:
        work = Path(directory)
        for name in manifest:
            target = work/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, target)
        env = dict(PATH=os.defpath, PYTHONPATH=str(work)+os.pathsep+str(ROOT),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
        result = subprocess.run([sys.executable, '-S', '-c', WORKER], cwd=work,
                                env=env, input=payload, text=True,
                                capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('native checkpoint observation rejected: ' + result.stderr.strip())
    return json.loads(result.stdout)


def _session_checkpoint(db):
    marker = db.execute('SELECT value FROM meta WHERE key=?',
                        ('nasuraya-bounded-body-loop/1',)).fetchone()
    if marker is None:
        raise ValueError('existing native body-loop session required')
    if db.execute("SELECT 1 FROM decisions WHERE status='running' LIMIT 1").fetchone():
        raise ValueError('unresolved native execution; saved checkpoint may precede action')
    row = db.execute('SELECT digest, value FROM runtime WHERE key=?',
                     ('nasuraya-body-loop',)).fetchone()
    if row is None:
        raise ValueError('native body checkpoint missing from session')
    checkpoint = json.loads(row[1])
    encoded = json.dumps(checkpoint, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != row[0]:
        raise ValueError('stored native runtime digest mismatch')
    return checkpoint


def observe_session(path, *, at_simulated_s=None, agent_id='NASURAYA'):
    """Inspect one existing, idle ledger using SQLite's read-only connection."""
    path = Path(path).absolute()
    # This lock matches BodyLoop's inode lock; a running writer is not inspected.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as lock:
        info = os.fstat(lock.fileno())
        # Match BodyLoop: WAL sidecars are path-based, so an inode alias could
        # otherwise omit pending WAL data and report an older checkpoint.
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('owned regular body-loop session without hard links required')
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            checkpoint = _session_checkpoint(db)
            report = observe_checkpoint(checkpoint, at_simulated_s=at_simulated_s,
                                        agent_id=agent_id)
            if _session_checkpoint(db) != checkpoint:
                raise ValueError('stored body checkpoint changed during observation')
            report['source_access'] = 'existing_body_loop_sqlite_read_only'
            return report
        finally:
            db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--session', type=Path, help='Existing native body.sqlite ledger')
    source.add_argument('--checkpoint', type=Path, help='Existing native checkpoint JSON')
    parser.add_argument('--at-simulated-s', type=float)
    parser.add_argument('--agent-id', default='NASURAYA')
    args = parser.parse_args(argv)
    options = dict(at_simulated_s=args.at_simulated_s, agent_id=args.agent_id)
    if args.session:
        report = observe_session(args.session, **options)
    else:
        report = observe_checkpoint(json.loads(args.checkpoint.read_text()), **options)
        report['source_access'] = 'existing_native_checkpoint_json_read_only'
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
