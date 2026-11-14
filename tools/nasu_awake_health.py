#!/usr/bin/env python3
"""Bounded, read-only Awake health receipt. Never selects question text or keys."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess

HOME = Path('/var/lib/nasuraya')


def current_state(home):
    report_path = home / 'migration' / 'latest-import.json'
    if report_path.is_symlink():
        raise ValueError('report symlink')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else None
    legacy = home / 'awake-stage' / 'awake.sqlite3'
    path = Path(report.get('working_db') or legacy) if report else legacy
    if path != legacy and (path.name != 'awake.sqlite3' or path.parent.parent != home / 'migration' / 'working'):
        raise ValueError('unexpected state path')
    # Reject symlinks anywhere below the service home, including parent directories.
    if not path.is_absolute() or path.resolve(strict=True) != path or home.resolve(strict=True) != home:
        raise ValueError('untrusted state path')
    if not path.is_file():
        raise ValueError('state missing')
    return path, report, 'VERSIONED' if path != legacy else 'LEGACY'


def systemd_value(command, expected):
    try:
        result = subprocess.run(['/usr/bin/systemctl', *command], capture_output=True,
                                text=True, timeout=5, check=False)
        value = result.stdout.strip()
        return value if value in expected else 'unknown'
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'


def health(home=HOME):
    if os.geteuid() == 0:
        raise ValueError('requires service account')
    path, report, source = current_state(home)
    # mode=ro cannot create an absent database. Counts and pause flag share one snapshot.
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('integrity failure')
        counts = [db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('evidence', 'questions', 'ticks', 'ledger')]
        paused = db.execute("SELECT value FROM control WHERE name='paused'").fetchone()
        if paused not in (('0',), ('1',)):
            raise ValueError('pause state missing')
    control_path = home / 'awake-control.json'
    gate = 'STANDBY'
    if control_path.is_symlink():
        raise ValueError('control symlink')
    if control_path.is_file():
        control = json.loads(control_path.read_text(encoding='utf-8'))
        if control.get('schema') != 'nasuraya-awake-offline/1' or type(control.get('enabled')) is not bool:
            raise ValueError('control invalid')
        if control['enabled']:
            if not report or control.get('import_id') != report.get('id'):
                raise ValueError('control import mismatch')
            gate = 'ENABLED'
    return {
        'paused': int(paused[0]), 'counts': counts, 'source': source, 'gate': gate,
        'timer': systemd_value(['is-active', 'nasuraya-awake.timer'], {'active', 'inactive', 'failed'}),
        'boot': systemd_value(['is-enabled', 'nasuraya-awake.timer'], {'enabled', 'disabled', 'static', 'masked'}),
        'last': systemd_value(['show', 'nasuraya-awake.service', '--property=Result', '--value'],
                              {'success', 'exit-code', 'timeout', 'signal', 'resources', 'dependency'}),
    }


def render(result):
    ev, q, tick, ledger = result['counts']
    return ('AWAKE_CURRENT=PAUSED:' + str(result['paused']) +
            ';EV=' + str(ev) + ';Q=' + str(q) + ';T=' + str(tick) + ';L=' + str(ledger) + '\n' +
            'AWAKE_HEALTH=OK;STATE=' + result['source'] + ';INTEGRITY=ok;GATE=' + result['gate'] +
            ';TIMER=' + result['timer'] + ';BOOT=' + result['boot'] + ';LAST=' + result['last'])


def main():
    try:
        print(render(health()))
        return 0
    except Exception as exc:
        # Exception messages can contain paths or private SQL data; emit a fixed class only.
        known = {'ValueError', 'OSError', 'FileNotFoundError', 'PermissionError', 'OperationalError',
                 'DatabaseError', 'JSONDecodeError'}
        name = type(exc).__name__
        print('AWAKE_HEALTH=UNKNOWN;CAUSE=' + (name if name in known else 'UNEXPECTED'))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
