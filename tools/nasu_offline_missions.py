#!/usr/bin/env python3
"""Nasuraya offline missions v1: inspect, practice, reflect, back up, repeat.

Rootless, bounded, offline after provisioning. This does not change existing
Awake, focus sessions, their ledgers, the local-brain journal, or the model.
"""
from __future__ import annotations
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
from contextlib import closing

HOME = Path('/var/lib/nasuraya')
STATE = HOME / 'autonomous-lab'
MODULE = 'examples.setar_practice'
# The successful earlier focus run was made from this reviewed source lineage.
ALLOWED_SOURCE_REVISIONS = {'ecf003bbce8805a1a20d0b4502f2c04d7cdbbd5e'}
INSTALLED = Path('/usr/local/lib/nasuraya/nasu_offline_missions.py')
NAME = 'nasuraya-offline-missions'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.new')
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError('Unresolved partial output: ' + str(tmp))
    with tmp.open('x', encoding='utf-8') as output:
        json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def sqlite_readonly(path):
    uri = 'file:' + urllib.parse.quote(str(Path(path))) + '?mode=ro'
    return sqlite3.connect(uri, uri=True, timeout=15)


def setup_database(state=STATE):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(state / 'missions.sqlite3', timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS days ('
               'day TEXT PRIMARY KEY, state TEXT NOT NULL, started TEXT NOT NULL, '
               'finished TEXT, practice_dir TEXT, total_updates INTEGER, '
               'qwen_status TEXT, report_sha256 TEXT)')
    db.commit()
    return db


def telemetry(home=HOME):
    mem = {}
    with open('/proc/meminfo', encoding='ascii') as stream:
        for line in stream:
            key, sep, value = line.partition(':')
            if sep and key in ('MemTotal', 'MemAvailable'):
                mem[key] = int(value.strip().split()[0])
    disk = os.statvfs(home)
    return {'mem_total_kib': mem.get('MemTotal'),
            'mem_available_kib': mem.get('MemAvailable'),
            'disk_available_bytes': disk.f_bavail * disk.f_frsize,
            'load_1min': round(os.getloadavg()[0], 3)}


def read_existing(home=HOME):
    """Summaries only; no access to raw questions or private text."""
    sys.path.insert(0, '/usr/local/lib/nasuraya')
    try:
        import nasu_local_brain as brain
    except ImportError:
        return {'awake': {'state': 'unavailable', 'reason': 'local_brain_not_installed'},
                'focus': {'state': 'unavailable', 'reason': 'local_brain_not_installed'}}
    result = {}
    for name, method in (('awake', brain.awake_snapshot), ('focus', brain.focus_snapshot)):
        try:
            result[name] = method(home)
        except (OSError, ValueError, TypeError, sqlite3.Error, KeyError) as exc:
            result[name] = {'state': 'unavailable', 'reason': type(exc).__name__}
    return result


def backup_journal(home=HOME, destination=STATE):
    source = home / 'local-brain/journal.sqlite3'
    if not source.is_file() or source.is_symlink():
        return {'status': 'journal_missing'}
    target = destination / 'local-brain-backups'
    target.mkdir(mode=0o700, exist_ok=True)
    day = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    final = target / ('brain-' + day + '.sqlite3')
    if final.exists():
        return {'status': 'existing', 'sha256': digest(final)}
    temp = target / ('brain-' + day + '.partial')
    if temp.exists():
        raise RuntimeError('Unreviewed partial database backup')
    try:
        with closing(sqlite_readonly(source)) as origin:
            with sqlite3.connect(temp) as copy:
                origin.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Local backup integrity check failed')
        os.chmod(temp, 0o600)
        os.rename(temp, final)
    finally:
        if temp.exists():
            temp.unlink()
    return {'status': 'created', 'sha256': digest(final)}


def source_checkout(home=HOME):
    for repo in sorted(home.glob('focus-20??????-??????/repo'), reverse=True):
        if repo.is_symlink() or not (repo / 'examples/setar_practice/__main__.py').is_file():
            continue
        venv = repo.parent / 'venv/bin/python'
        if not venv.exists():
            continue
        git = subprocess.run(['/usr/bin/git', '-C', str(repo), 'rev-parse', 'HEAD'],
                             capture_output=True, text=True, timeout=10)
        if git.returncode == 0 and git.stdout.strip() in ALLOWED_SOURCE_REVISIONS:
            dirty = subprocess.run(['/usr/bin/git', '-C', str(repo), 'status', '--porcelain'],
                                   capture_output=True, text=True, timeout=10)
            if dirty.returncode or dirty.stdout.strip():
                raise RuntimeError('Local practice source has unreviewed changes')
            return repo, venv, git.stdout.strip()
    raise RuntimeError('Verified existing Setar checkout/venv not found')


def get_parent(db, home=HOME):
    rows = db.execute("SELECT practice_dir, total_updates FROM days WHERE state IN "
                      "('completed', 'completed_without_qwen') ORDER BY day DESC").fetchall()
    for run_dir, total in rows:
        path = Path(run_dir) / 'checkpoint.json'
        if path.is_file() and not path.is_symlink():
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('total_updates') == total:
                return path
        raise RuntimeError('Last published skill checkpoint missing or inconsistent')
    candidates = sorted(home.glob('focus-20??????-??????/lesson/checkpoint.json'), reverse=True)
    if not candidates:
        raise RuntimeError('No previously completed focus checkpoint available')
    path = candidates[0]
    if path.is_symlink():
        raise RuntimeError('Checkpoint link not trusted')
    return path


def call_checked(argv, *, cwd, timeout=240):
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(HOME),
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONPATH': str(cwd),
           'PYTHONDONTWRITEBYTECODE': '1', 'OLLAMA_HOST': '127.0.0.1:11434'}
    process = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                             text=True, timeout=timeout)
    if process.returncode:
        raise RuntimeError('Bounded practice command failed, exit=' + str(process.returncode)
                           + ', stderr=' + process.stderr[-380:])
    return json.loads(process.stdout)


def practice(db, out, *, day, home=HOME):
    repo, python, rev = source_checkout(home)
    parent = get_parent(db, home)
    output = out / 'practice'
    seed = 4200000 + int(day.replace('-', '')) % 70000
    base = [str(python), '-m', MODULE]
    # Daily bounded local regression. No source modification or remote CI.
    tests = subprocess.run([str(python), '-m', 'unittest',
          'examples.setar_practice.test_focus_cycle', '-q'], cwd=repo,
          env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(home),
               'LANG': 'C.UTF-8', 'PYTHONPATH': str(repo),
               'PYTHONDONTWRITEBYTECODE': '1'},
          capture_output=True, text=True, timeout=120)
    if tests.returncode:
        raise RuntimeError('Pinned Setar regression suite failed')
    before = call_checked(base + ['evaluate', '--checkpoint', str(parent)], cwd=repo)
    summary = call_checked(base + ['practice', '--checkpoint', str(parent),
                       '--output-dir', str(output), '--episodes', '3',
                       '--seed', str(seed), '--accelerated'], cwd=repo, timeout=320)
    after = call_checked(base + ['evaluate', '--checkpoint', str(output / 'checkpoint.json')], cwd=repo)
    if (summary['episodes'] != 3 or summary['inherited_updates'] != before['status']['total_updates']
            or summary['total_updates'] <= summary['inherited_updates']
            or digest(output / 'checkpoint.json') != summary['checkpoint_sha256']
            or digest(output / 'practice.wav') != summary['audio']['sha256']):
        raise RuntimeError('Practice summary, output or inherited memory mismatch')
    return {'status': 'completed', 'source_revision': rev,
            'source_regression': 'passed',
            'synthetic_seconds': summary['scheduled_music_seconds'],
            'note_events': summary['note_events'],
            'inherited_updates': summary['inherited_updates'],
            'new_updates': summary['new_updates'],
            'total_updates': summary['total_updates'],
            'before_holdout': before['summary'], 'after_holdout': after['summary'],
            'checkpoint_sha256': summary['checkpoint_sha256'],
            'audio_sha256': summary['audio']['sha256'],
            'physical_hand_control': False, 'accelerated': True}


def qwen_reflect(snapshot):
    import nasu_local_brain as brain
    # Reuse the verified Persian-only local API with no code/tool execution.
    return brain.infer(snapshot, [])


def run(*, home=HOME, state=STATE, date=None):
    if os.geteuid() == 0:
        raise PermissionError('Autonomous mission must not run as root')
    os.umask(0o077)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / 'missions.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(setup_database(state)) as db:
            now = dt.datetime.now(dt.timezone.utc)
            day = date or now.strftime('%Y-%m-%d')
            past = db.execute('SELECT state FROM days WHERE day=?', (day,)).fetchone()
            if past:
                return {'status': 'already_reserved', 'date': day, 'previous_state': past[0]}
            db.execute('INSERT INTO days(day,state,started) VALUES(?,?,?)',
                       (day, 'running', now.isoformat()))
            db.commit()  # Reserve first. A crash is not mistaken for success.
            folder = state / day
            folder.mkdir(mode=0o700, exist_ok=False)
            data = {'schema': 'nasuraya.offline-missions/1', 'date': day,
                    'telemetry': telemetry(home), 'existing': read_existing(home)}
            try:
                data['backup'] = backup_journal(home, state)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                data['backup'] = {'status': 'failed', 'error_class': type(exc).__name__}
            try:
                data['practice'] = practice(db, folder, day=day, home=home)
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as exc:
                data['practice'] = {'status': 'failed', 'error_class': type(exc).__name__,
                                    'reason': str(exc)[:230]}
                atomic(folder / 'result.json', data)
                db.execute('UPDATE days SET state=?, finished=?, report_sha256=? WHERE day=?',
                           ('failed', dt.datetime.now(dt.timezone.utc).isoformat(),
                            digest(folder / 'result.json'), day))
                db.commit()
                return {'status': 'failed', 'date': day, 'stage': 'practice',
                        'error_class': type(exc).__name__}
            try:
                data['reflection'] = {'status': 'completed',
                                      'text': qwen_reflect({'telemetry': data['telemetry'],
                                         'awake': data['existing']['awake'],
                                         'setar': data['practice']})}
                state_value = 'completed'
            except (OSError, RuntimeError, ValueError, TimeoutError, sqlite3.Error) as exc:
                data['reflection'] = {'status': 'failed', 'error_class': type(exc).__name__}
                state_value = 'completed_without_qwen'
            atomic(folder / 'result.json', data)
            db.execute('UPDATE days SET state=?, finished=?, practice_dir=?, '
                       'total_updates=?, qwen_status=?, report_sha256=? WHERE day=?',
                       (state_value, dt.datetime.now(dt.timezone.utc).isoformat(),
                        str(folder / 'practice'), data['practice']['total_updates'],
                        data['reflection']['status'], digest(folder / 'result.json'), day))
            db.commit()
            return {'status': state_value, 'date': day,
                    'total_updates': data['practice']['total_updates'],
                    'notes': data['practice']['note_events'],
                    'qwen': data['reflection']['status'],
                    'report': str(folder / 'result.json')}


def status(state=STATE):
    dbpath = state / 'missions.sqlite3'
    if not dbpath.exists():
        return {'status': 'uninitialized'}
    with closing(sqlite_readonly(dbpath)) as db:
        n = db.execute('SELECT COUNT(*) FROM days').fetchone()[0]
        rows = db.execute('SELECT day,state,total_updates,qwen_status FROM days '
                          'ORDER BY day DESC LIMIT 3').fetchall()
    return {'status': 'ok', 'day_count': n,
            'recent': [{'day': x[0], 'state': x[1],
                        'total_updates': x[2], 'qwen': x[3]} for x in rows]}


def install():
    if os.geteuid() != 0:
        raise PermissionError('Installing systemd timer requires root')
    subprocess.run(['/usr/bin/id', 'nasuraya'], check=True, capture_output=True)
    if not Path('/usr/local/lib/nasuraya/nasu_local_brain.py').is_file():
        raise RuntimeError('Local Qwen reporter not yet installed')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.chown(STATE, user='nasuraya', group='nasuraya')
    os.chmod(STATE, 0o700)
    INSTALLED.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve()
    if INSTALLED.exists() and INSTALLED.read_bytes() != source.read_bytes():
        raise RuntimeError('Different mission runner already installed, refusing overwrite')
    if not INSTALLED.exists():
        shutil.copyfile(source, INSTALLED)
        os.chmod(INSTALLED, 0o644)
    service = Path('/etc/systemd/system/' + NAME + '.service')
    timer = Path('/etc/systemd/system/' + NAME + '.timer')
    service_text = f'''[Unit]
Description=Nasuraya autonomous offline missions (bounded and unprivileged)
After=ollama.service
Wants=ollama.service
[Service]
Type=oneshot
User=nasuraya
Group=nasuraya
WorkingDirectory={HOME}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 {INSTALLED} run
TimeoutStartSec=600
MemoryMax=8G
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={STATE}
'''
    timer_text = f'''[Unit]
Description=One offline Nasuraya mission set per day
[Timer]
OnCalendar=*-*-* 05:17:00 UTC
Persistent=true
AccuracySec=1min
Unit={NAME}.service
[Install]
WantedBy=timers.target
'''
    for path, body in ((service, service_text), (timer, timer_text)):
        if path.exists() and path.read_text() != body:
            raise RuntimeError('Unit exists and differs: ' + str(path))
        if not path.exists():
            path.write_text(body)
            os.chmod(path, 0o644)
    subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
    subprocess.run(['/usr/bin/systemctl', 'enable', '--now', NAME + '.timer'], check=True)
    subprocess.run(['/usr/bin/systemctl', 'start', NAME + '.service'], check=True)
    print('MISSIONS_INSTALL=OK;OFFLINE=YES;SCHEDULE=DAILY_05:17_UTC')
    print('TIMER=' + subprocess.check_output(['/usr/bin/systemctl', 'is-active', NAME + '.timer'], text=True).strip())
    print('RESULT=' + json.dumps(status(), ensure_ascii=False))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'install','run','status'}:
        raise SystemExit('Usage: nasu_offline_missions.py install|run|status')
    action = sys.argv[1]
    if action == 'install':
        install()
    else:
        print(json.dumps(run() if action == 'run' else status(), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        print('MISSIONS_FAILED=' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
