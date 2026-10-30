"""Bounded parallel orchestration with durable claims and fail-closed crash recovery."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from . import worker

VERSION = 'nasuraya-agent-network/1'
MAX_RUN_SECONDS = 210
ROOTS = ('examples', 'runtimes', 'continuity_host')
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(encode(value) + '\n', encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def coordinator_lock(workspace: Path):
    with (workspace / '.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another coordinator owns this workspace') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def copy_snapshot(root: Path, destination: Path) -> str:
    """Only code/data roots; reject symlinks and credential-looking files."""
    manifest = {}
    total = 0
    files = []
    for name in ROOTS:
        base = root / name
        if base.is_symlink():
            raise ValueError('symlink source root')
        if base.is_dir():
            files.extend(base.rglob('*'))
    if (root / 'core_mechanics.py').exists():
        files.append(root / 'core_mechanics.py')
    for source in sorted(files):
        relative = source.relative_to(root)
        if '__pycache__' in relative.parts:
            continue
        if source.is_symlink():
            raise ValueError('symlink source: ' + str(relative))
        if not source.is_file():
            continue
        # A .gitignore is repository metadata, not executable input. Ignore only
        # this exact basename in visible directories; still reject other hidden files.
        if source.name == '.gitignore' and not any(p.startswith('.') for p in relative.parts[:-1]):
            continue
        if any(part.startswith('.') for part in relative.parts) or source.suffix in ('.key', '.pem', '.p12'):
            raise ValueError('hidden or credential-like source excluded')
        size = source.stat().st_size
        if len(manifest) >= 5000 or total + size > MAX_SOURCE_BYTES:
            raise ValueError('source size budget exceeded')
        raw = source.read_bytes()
        total += len(raw)
        if total > MAX_SOURCE_BYTES:
            raise ValueError('source grew beyond budget')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
    if not manifest:
        raise ValueError('no repository source files')
    return hashlib.sha256(encode(manifest).encode()).hexdigest()


def implementation_digest() -> str:
    files = {p.name: worker.digest(p) for p in Path(__file__).parent.glob('*.py')}
    return hashlib.sha256(encode(files).encode()).hexdigest()


def artifacts(directory: Path) -> dict[str, str]:
    result = {}
    size = 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink artifact')
        if path.is_file():
            size += path.stat().st_size
            if len(result) >= 2000 or size > MAX_SOURCE_BYTES:
                raise ValueError('artifact budget exceeded')
            result[path.relative_to(directory).as_posix()] = worker.digest(path)
    return result


def validate_artifacts(directory: Path, manifest: dict) -> None:
    if artifacts(directory) != manifest:
        raise ValueError('saved evidence changed or is missing; refusing replay')


def database(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, report TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (run_id TEXT, agent TEXT, status TEXT NOT NULL, receipt TEXT, PRIMARY KEY(run_id,agent))')
    db.commit()
    return db


def review(receipts: dict) -> dict:
    reasons = []
    for role in worker.ROLES:
        r = receipts.get(role, {})
        if r.get('passed') is not True or r.get('network_syscalls_denied') is not True:
            reasons.append(role + ': failed, interrupted, or missing')
        if not r.get('commands') or any(c.get('returncode') != 0 or c.get('interrupted')
                or c.get('network_syscalls_denied') is not True for c in r.get('commands', [])):
            reasons.append(role + ': command evidence incomplete')
    return {'agent': 'reviewer', 'passed': not reasons, 'reasons': reasons,
            'automatic_promotion': False, 'next_action': 'review evidence' if not reasons else 'inspect failed worker logs'}


def run(root: Path, workspace: Path, run_id: str, max_workers: int = 2) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
        raise ValueError('invalid run ID')
    if type(max_workers) is not int or not 1 <= max_workers <= 4:
        raise ValueError('max-workers must be 1..4')
    root, workspace = root.resolve(), workspace.resolve()
    if root.is_relative_to(workspace) or workspace.is_relative_to(root):
        raise ValueError('workspace must be outside the source tree')
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    with coordinator_lock(workspace), tempfile.TemporaryDirectory(prefix='snapshot-', dir=workspace) as temp:
        snapshot = Path(temp)
        source_hash = copy_snapshot(root, snapshot)
        binding = {'schema': VERSION, 'source_sha256': source_hash,
                   'implementation_sha256': implementation_digest(), 'max_workers': max_workers}
        fingerprint = hashlib.sha256(encode(binding).encode()).hexdigest()
        db = database(workspace / 'ledger.sqlite')
        try:
            existing = db.execute('SELECT fingerprint,status,report FROM runs WHERE id=?', (run_id,)).fetchone()
            output = workspace / run_id
            if existing:
                if existing[0] != fingerprint:
                    raise ValueError('run ID already bound to different source or configuration')
                if existing[1] != 'finished':
                    raise RuntimeError('unfinished run requires review; no automatic retry or budget refund')
                report = json.loads(existing[2])
                for role, receipt in report['workers'].items():
                    if 'artifacts' in receipt:
                        validate_artifacts(output / role, receipt['artifacts'])
                atomic_json(output / 'summary.json', report)
                return report
            stop = workspace / 'STOP'
            if stop.exists():
                raise RuntimeError('network paused by STOP; no run claimed')
            output.mkdir(exist_ok=False)
            with db:
                db.execute('INSERT INTO runs VALUES (?,?,?,NULL)', (run_id, fingerprint, 'running'))
                db.executemany('INSERT INTO jobs VALUES (?,?,?,NULL)', [(run_id, r, 'pending') for r in (*worker.ROLES, 'reviewer')])
            started = datetime.now(timezone.utc).isoformat()
            deadline = time.monotonic() + MAX_RUN_SECONDS
            pending, active, receipts = list(worker.ROLES), {}, {}
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                while pending or active:
                    halted = stop.exists() or time.monotonic() >= deadline
                    while pending and len(active) < max_workers and not halted:
                        role = pending.pop(0)
                        with db:
                            changed = db.execute('UPDATE jobs SET status=? WHERE run_id=? AND agent=? AND status=?',
                                                 ('running', run_id, role, 'pending')).rowcount
                            if changed != 1:
                                raise RuntimeError('claim collision')
                        future = pool.submit(worker.execute, role, snapshot, output / role, stop, deadline)
                        active[future] = role
                    if halted and pending:
                        for role in pending:
                            receipts[role] = {'agent': role, 'passed': False, 'error': 'not started: stop/time budget'}
                            with db:
                                db.execute('UPDATE jobs SET status=?,receipt=? WHERE run_id=? AND agent=?',
                                           ('blocked', encode(receipts[role]), run_id, role))
                        pending.clear()
                    if not active:
                        break
                    done, _ = wait(active, timeout=.05, return_when=FIRST_COMPLETED)
                    for future in done:
                        role = active.pop(future)
                        try:
                            receipt = future.result()
                            receipt['artifacts'] = artifacts(output / role)
                        except Exception as exc:
                            receipt = {'agent': role, 'passed': False, 'error': type(exc).__name__ + ': ' + str(exc)[:250]}
                        receipts[role] = receipt
                        with db:
                            db.execute('UPDATE jobs SET status=?,receipt=? WHERE run_id=? AND agent=?',
                                       ('completed' if receipt['passed'] else 'failed', encode(receipt), run_id, role))
            checked = review(receipts)
            report = {**binding, 'run_id': run_id, 'started_at': started,
                      'finished_at': datetime.now(timezone.utc).isoformat(),
                      'status': 'passed' if checked['passed'] else 'failed',
                      'workers': receipts, 'reviewer': checked, 'model_api_calls': 0,
                      'mode': 'offline_fixed_workers', 'source_tree_modified_by_design': False,
                      'scheduled_service_installed': False}
            with db:
                db.execute('UPDATE jobs SET status=?,receipt=? WHERE run_id=? AND agent=?',
                           ('completed', encode(checked), run_id, 'reviewer'))
                db.execute('UPDATE runs SET status=?,report=? WHERE id=?', ('finished', encode(report), run_id))
            atomic_json(output / 'summary.json', report)
            lines = ['# گزارش شبکهٔ ناسورایا', '', 'شناسه: ' + run_id, 'نتیجه: ' + report['status'], '']
            lines += [r + ': ' + ('موفق' if receipts[r]['passed'] else 'نیازمند بررسی') for r in worker.ROLES]
            lines += ['', 'فراخوانی مدل: صفر. ادغام خودکار: خیر.', 'این نسخه اجراکنندهٔ وظایف مشخص است، نه نسخهٔ مستقل یک مدل زبانی.']
            (output / 'REPORT_FA.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            return report
        finally:
            db.close()
