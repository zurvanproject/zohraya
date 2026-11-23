#!/usr/bin/env python3
"""Explicit, root-only, SHA-pinned Ubuntu Bridge v3.1 upgrade.

This installer does nothing without --apply --approve-sha <EXACT_PREVIEW_SHA>.
No GitHub writes, source checkout mutation, model changes or research run.
Preview is read-only. Apply changes exactly TWO files and restarts only the
nasuraya-bridge service, with an automatic rollback on failure.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time

BRIDGE = Path('/usr/local/lib/nasuraya/bridge.py')
WORKER = Path('/usr/local/lib/nasuraya/nasu_bridge_research.py')
SERVICE = 'nasuraya-bridge.service'
BACKUPS = Path('/var/backups/nasuraya-bridge-v31')
EXPECTED_BRIDGE = 'a8fdac423d1161bf4209e43f991168df31721cb1529e367d01e2b5c10841dd74'
WORKER_SOURCE = Path(__file__).with_name('nasu_bridge_research.py')
PATCHER_SOURCE = Path(__file__).with_name('preview_nasuraya_bridge_v31.py')
# These hashes are pinned to this review revision and checked at execution.
EXPECTED_WORKER = 'f4a4631c7170e807d1bfa11c29be962928658970c71247170c5612eae1e78cc9'
EXPECTED_PATCHER = '2311a6643abde6063364aa67cbfb63335528918b13e2840a92bab7991dd17c75'


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_file(path: Path, *, max_size: int = 250000) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('not_regular_or_symlinked:' + path.name)
    if path.stat().st_size > max_size or path.stat().st_size == 0:
        raise ValueError('file_size_invalid:' + path.name)
    return path.read_bytes()


def load_plan():
    bridge = safe_file(BRIDGE)
    if digest(bridge) != EXPECTED_BRIDGE:
        raise ValueError('LIVE_BRIDGE_SHA_CHANGED_REFUSE')
    worker = safe_file(WORKER_SOURCE)
    patcher_source = safe_file(PATCHER_SOURCE)
    if digest(worker) != EXPECTED_WORKER or digest(patcher_source) != EXPECTED_PATCHER:
        raise ValueError('REVIEWED_SOURCE_HASH_MISMATCH')
    if WORKER.exists() or WORKER.is_symlink():
        raise ValueError('RUNNER_TARGET_ALREADY_PRESENT_REFUSE')
    spec = importlib.util.spec_from_file_location('pinned_bridge_patch_v31', PATCHER_SOURCE)
    if spec is None or spec.loader is None:
        raise ValueError('PATCHER_UNAVAILABLE')
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    before = bridge.decode('utf-8')
    after = patcher.patch(before, exact_live=True)
    compile(after, str(BRIDGE), 'exec')
    compile(worker.decode('utf-8'), str(WORKER), 'exec')
    return bridge, after.encode('utf-8'), worker


def atomic_bytes(path: Path, content: bytes, mode: int, uid: int, gid: int):
    fd, temp_name = tempfile.mkstemp(prefix='.' + path.name + '.v31-', dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'wb') as dst:
            dst.write(content)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def systemctl(*args):
    return subprocess.run(['/usr/bin/systemctl', *args], capture_output=True,
                          text=True, timeout=25, check=False,
                          env={'PATH':'/usr/bin:/bin', 'LANG':'C', 'LC_ALL':'C'})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--preview', action='store_true', help='Print exact diff, no writes')
    p.add_argument('--apply', action='store_true', help='Install after review and SHA approval')
    p.add_argument('--approve-sha', default='', help='SHA-256 of exact proposed bridge')
    a = p.parse_args()
    if a.preview == a.apply:
        p.error('select exactly one: --preview or --apply')
    if a.apply and (os.geteuid() != 0):
        raise SystemExit('ROOT_REQUIRED_FOR_APPLY')
    old, new, worker = load_plan()
    new_sha = digest(new)
    print('LIVE_BRIDGE_SHA256:', digest(old), flush=True)
    print('PROPOSED_BRIDGE_SHA256:', new_sha, flush=True)
    print('WORKER_SHA256:', digest(worker), flush=True)
    if a.preview:
        print(''.join(difflib.unified_diff(old.decode().splitlines(keepends=True),
             new.decode().splitlines(keepends=True), fromfile='installed/bridge.py',
             tofile='proposed/bridge.py')))
        print('PREVIEW_ONLY_NO_CHANGES', flush=True)
        return
    if a.approve_sha != new_sha:
        raise SystemExit('APPROVED_SHA_MISSING_OR_DIFFERENT')
    if not BRIDGE.parent.is_dir() or not BACKUPS.parent.is_dir():
        raise SystemExit('UNKNOWN_INSTALL_LAYOUT')
    if systemctl('is-active','--quiet',SERVICE).returncode != 0:
        raise SystemExit('BRIDGE_NOT_ACTIVE_REFUSE')
    st = BRIDGE.stat()
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o022:
        raise SystemExit('INSECURE_BRIDGE_MODE_REFUSE')
    backups_preexisting = BACKUPS.exists()
    if BACKUPS.is_symlink() or (backups_preexisting and not BACKUPS.is_dir()):
        raise SystemExit('INVALID_BACKUP_DIRECTORY')
    BACKUPS.mkdir(mode=0o700, parents=False, exist_ok=True)
    if stat.S_IMODE(BACKUPS.stat().st_mode) != 0o700:
        raise SystemExit('BACKUP_DIRECTORY_PERMISSIONS_REFUSE')
    backup = BACKUPS / ('bridge-' + digest(old) + '-' + str(int(time.time_ns())) + '.bak')
    backup_fd = os.open(str(backup), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(backup_fd, 'wb') as f:
        f.write(old)
        f.flush()
        os.fsync(f.fileno())
    bridge_changed = False
    worker_changed = False
    try:
        atomic_bytes(WORKER, worker, 0o644, 0, 0)
        worker_changed = True
        atomic_bytes(BRIDGE, new, mode, st.st_uid, st.st_gid)
        bridge_changed = True
        restart = systemctl('restart', SERVICE)
        if restart.returncode != 0 or systemctl('is-active','--quiet',SERVICE).returncode != 0:
            raise RuntimeError('BRIDGE_RESTART_FAILED')
        if digest(safe_file(BRIDGE)) != new_sha or digest(safe_file(WORKER)) != digest(worker):
            raise RuntimeError('POST_INSTALL_HASH_MISMATCH')
    except BaseException:
        if bridge_changed:
            atomic_bytes(BRIDGE, old, mode, st.st_uid, st.st_gid)
        if worker_changed:
            WORKER.unlink(missing_ok=True)
        systemctl('restart', SERVICE)
        print('ROLLBACK_ATTEMPTED_BACKUP:', backup, flush=True)
        raise
    print('UPGRADE_INSTALLED_BACKUP:', backup, flush=True)
    print('ONLY_SERVICE_RESTARTED:', SERVICE, flush=True)
    print('RESEARCH_NOT_STARTED', flush=True)


if __name__ == '__main__':
    main()
