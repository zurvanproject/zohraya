"""Read-only, bounded observer and offline visual report. Python 3.11+.

Run only this reviewed observer/template from a trusted checkout. It imports no
project code, never admits work, and never creates or repairs a sentinel store.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat

SCHEMA = 'nasuraya.visual-status.v2'
TTL_SECONDS = 120
HEX = re.compile(r'[0-9a-f]{64}\Z')
CODES = {'admitted': 'info', 'allowed': 'info', 'invalid_request': 'warning',
         'input_burst': 'high', 'source_integrity': 'critical',
         'receipt_integrity': 'high', 'execution_error': 'high', 'latched': 'critical'}


def read_file(path, limit):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('file bound')
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('file grew')
        return data


def parse_json(data):
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('nonfinite')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def check_sources(root, manifest, expected):
    data = read_file(manifest, 128 * 1024)
    if hashlib.sha256(data).hexdigest() != expected:
        return False
    entries = parse_json(data)
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 256:
        return False
    for name, wanted in entries.items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or not relative.parts
                or not isinstance(wanted, str) or not HEX.fullmatch(wanted)):
            return False
        if hashlib.sha256(read_file(Path(root) / relative, 3 * 1024 * 1024)).hexdigest() != wanted:
            return False
    return True


def read_audit(path, now):
    # Work on a bounded in-memory copy: no SQLite writes/sidecars in the store.
    path = Path(path)
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise OSError('busy or unsupported journal')
    data = read_file(path, 16 * 1024 * 1024)
    if data != read_file(path, 16 * 1024 * 1024):
        raise OSError('store changed during capture')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(data)
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.set_progress_handler(lambda: 1, 200000)
        schema = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if sorted(schema) != [('control', 'table'), ('events', 'table')]:
            raise ValueError('unexpected schema')
        controls = db.execute('SELECT singleton,latched,head,seq FROM control LIMIT 2').fetchall()
        if len(controls) != 1:
            raise ValueError('control')
        singleton, latched, saved_head, saved_seq = controls[0]
        if singleton != 1 or type(latched) is not int or latched not in (0, 1):
            raise ValueError('latch')
        rows = db.execute('SELECT seq,record,hash FROM events ORDER BY seq LIMIT 2049').fetchall()
    head = '0' * 64
    recent = []
    warnings = 0
    previous_time = None
    for seq, (n, encoded, stored_hash) in enumerate(rows, 1):
        if seq > 2048 or n != seq or not isinstance(encoded, str) or len(encoded) > 2048:
            raise ValueError('event bound')
        event = parse_json(encoded)
        if (not isinstance(event, dict) or set(event) != {'seq', 'previous', 'at_utc', 'code', 'severity'}
                or type(event['seq']) is not int or event['seq'] != seq or event['previous'] != head
                or not isinstance(event['code'], str) or CODES.get(event['code']) != event['severity']
                or stored_hash != digest(event)):
            raise ValueError('event integrity')
        at = datetime.fromisoformat(event['at_utc'])
        if at.tzinfo is None or at.timestamp() > now.timestamp() + 5 or (previous_time and at < previous_time):
            raise ValueError('event time')
        previous_time = at
        warnings += event['severity'] != 'info'
        head = stored_hash
        # Export only fixed codes, validated times and sequence numbers.
        recent.append(dict(seq=seq, code=event['code'], severity=event['severity'], at_utc=at.isoformat()))
    if type(saved_seq) is not int or saved_seq != len(rows) or saved_head != head:
        raise ValueError('audit head')
    return dict(latched=bool(latched), events=len(rows), warnings=warnings,
                capacity_stop=len(rows) >= 2047, recent=recent[-8:])


def observe(root, manifest, expected, alerts, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('timezone required')
    checks = dict(source='unknown', audit='unknown')
    reasons = []
    audit = dict(latched=None, events=None, warnings=None, capacity_stop=False, recent=[])
    if not isinstance(expected, str) or not HEX.fullmatch(expected):
        reasons.append('trusted_digest_missing')
        expected = None
    else:
        try:
            checks['source'] = 'pass' if check_sources(root, manifest, expected) else 'fail'
            if checks['source'] == 'fail':
                reasons.append('source_integrity')
        except Exception:
            reasons.append('source_unavailable')
    try:
        audit = read_audit(alerts, now)
        checks['audit'] = 'pass'
        if audit['latched']:
            reasons.append('latched')
        if audit['capacity_stop']:
            reasons.append('audit_capacity')
        if audit['warnings']:
            reasons.append('warning_history')
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        checks['audit'] = 'fail'
        reasons.append('audit_integrity')
    except Exception:
        reasons.append('audit_unavailable')
    if 'fail' in checks.values() or audit['latched'] or audit['capacity_stop']:
        state = 'blocked'
    elif 'unknown' in checks.values():
        state = 'unknown'
    elif audit['warnings']:
        state = 'warning'
    else:
        state = 'healthy'
    return dict(schema=SCHEMA, observed_at=now.isoformat(), ttl_seconds=TTL_SECONDS,
                state=state, checks=checks, reasons=reasons, audit=audit,
                expected_manifest_sha256=expected, scope='local_guard_sources_and_audit_only')


def render(snapshot):
    template = read_file(Path(__file__).with_name('visual_console.html'), 64 * 1024).decode('utf-8')
    # Only the reviewed, unchanged UI script and stylesheet may run. No inline
    # event handlers, network resources, forms or dynamically fetched data.
    for tag, token in [('script', '__SCRIPT_HASH__'), ('style', '__STYLE_HASH__')]:
        content = re.search(r'<' + tag + r'>(.*?)</' + tag + r'>', template, re.S).group(1)
        fingerprint = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
        template = template.replace(token, fingerprint)
    # Prevent script termination even if this helper is later given hostile text.
    data = json.dumps(snapshot, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    if template.count('__SNAPSHOT__') != 1:
        raise ValueError('template contract')
    return template.replace('__SNAPSHOT__', data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--alerts', required=True)
    parser.add_argument('--output', required=True, help='new directory; existing evidence is never overwritten')
    args = parser.parse_args()
    snapshot = observe(args.repo_root, args.manifest, args.expected_manifest_sha256, args.alerts)
    output = Path(args.output)
    output.mkdir(parents=False, exist_ok=False)
    (output / 'status.json').write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
    (output / 'index.html').write_text(render(snapshot), encoding='utf-8')
    print(json.dumps(dict(state=snapshot['state'], events=snapshot['audit']['events'], ttl_seconds=TTL_SECONDS)))
    return 0 if snapshot['state'] == 'healthy' else 2


if __name__ == '__main__':
    raise SystemExit(main())
