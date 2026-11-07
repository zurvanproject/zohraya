"""Nasurayaza v0.1: a persistent, read-only adversarial review observer.

Uses deterministic questions rather than pretending to be a thinking model.
No credentials, code writes, model calls, money movement or actuator control.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

REPO = 'zurvanproject/zohraya'
URL = 'https://api.github.com/repos/' + REPO + '/pulls?state=all&sort=updated&direction=desc&per_page=30'
MAX_RESPONSE = 1_500_000
MIN_INTERVAL = 300
MAX_INTERVAL = 86_400


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def parse_interval(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError('POLL_SECONDS must be an integer') from exc
    if not MIN_INTERVAL <= value <= MAX_INTERVAL:
        raise ValueError('POLL_SECONDS outside 300..86400 seconds')
    return value


def fetch_pulls() -> list[dict]:
    # This endpoint is fixed at source; fetched text is untrusted evidence, not instructions.
    req = Request(URL, headers={'Accept': 'application/vnd.github+json',
                                'User-Agent': 'nasurayaza-readonly-observer-v01',
                                'X-GitHub-Api-Version': '2022-11-28'})
    with build_opener(ProxyHandler({})).open(req, timeout=20) as res:
        raw = res.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('GitHub response too large')
    data = json.loads(raw)
    if not isinstance(data, list) or len(data) > 30:
        raise ValueError('Invalid GitHub pull list')
    return data


def extract(item: dict) -> dict:
    """Minimal allowlist avoids writing arbitrary PR payloads to local storage."""
    number = item['number']
    title = item['title']
    body = item.get('body') or ''
    updated = item['updated_at']
    state = item['state']
    head_sha = item['head']['sha']
    if type(number) is not int or not (1 <= number <= 2_000_000):
        raise ValueError('Invalid pull number')
    if not (isinstance(title, str) and 0 < len(title) <= 500):
        raise ValueError('Invalid pull title')
    if not (isinstance(body, str) and len(body) <= 100_000):
        raise ValueError('Invalid pull body')
    if state not in ('open', 'closed') or type(item['draft']) is not bool:
        raise ValueError('Invalid pull state')
    if not (isinstance(head_sha, str) and len(head_sha) == 40 and
            all(c in '0123456789abcdef' for c in head_sha)):
        raise ValueError('Invalid head sha')
    if not isinstance(updated, str) or len(updated) > 60:
        raise ValueError('Invalid timestamp')
    return {'number': number, 'title': title, 'body': body[:12_000],
            'updated_at': updated, 'state': state, 'draft': item['draft'],
            'merged': bool(item.get('merged_at')), 'head_sha': head_sha}


def critique(item: dict) -> dict:
    """Rule-based, falsifiable audit questions; never declares a PR safe to merge."""
    text = (item['title'] + '\n' + item['body']).lower()
    q = ['What independent test could falsify the principal improvement claim?',
         'What negative result or regression would block promotion to main?']
    observations = ['Draft review only; evidence has not been independently audited.']
    if item['draft']:
        q.append('Which explicit exit criteria are still missing before draft status is lifted?')
    if not any(s in text for s in ('test', 'آزمون', 'validation', 'verified')):
        q.append('Where are executable tests and the exact reproduction command?')
    if any(s in text for s in ('dreamer', 'forecast', 'predict', 'پیش‌بینی')):
        q.append('Does the predictor beat persistence and a simple linear baseline on disjoint trajectories?')
    if any(s in text for s in ('body', 'tadash', 'muscle', 'pelvic', 'بدن')):
        q.append('Are the 78 kg articulated atlas and 195 kg reduced native physiology kept distinct?')
    if any(s in text for s in ('memory', 'sqlite', 'checkpoint', 'replay', 'حافظه')):
        q.append('Does a cold-process restart reproduce state without duplicate effects?')
    if any(s in text for s in ('api', 'token', 'billing', 'cost', 'gpu')):
        q.append('What are the hard credential, budget and resource limits?')
    if any(s in text for s in ('conscious', 'feeling', 'subjective', 'خودآگاه', 'احساس')):
        q.append('Which measured property is being tested, and what subjective claim is not supported?')
    if item['merged']:
        observations.append('Merged status is deployment evidence, not performance evidence.')
    return {'observations': observations, 'questions': q[:9],
            'conclusion': 'needs-evidence-review'}


def database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=15)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS reviews (
      id INTEGER PRIMARY KEY, pull_number INTEGER NOT NULL, fingerprint TEXT NOT NULL,
      observed_at TEXT NOT NULL, title TEXT NOT NULL, head_sha TEXT NOT NULL,
      state TEXT NOT NULL, review_json TEXT NOT NULL,
      UNIQUE(pull_number, fingerprint))''')
    con.execute('''CREATE TABLE IF NOT EXISTS polls (
      id INTEGER PRIMARY KEY, at TEXT NOT NULL, ok INTEGER NOT NULL,
      new_reviews INTEGER NOT NULL, problem TEXT)''')
    con.commit()
    return con


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(canonical(data) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def poll(con: sqlite3.Connection, incoming: list[dict], status_file: Path, at=None) -> dict:
    at = at or timestamp()
    records = []
    with con:
        for raw in incoming:
            item = extract(raw)
            identity = {k: v for k, v in item.items() if k != 'body'}
            identity['body_digest'] = hashlib.sha256(item['body'].encode('utf-8')).hexdigest()
            fingerprint = digest(identity)
            if con.execute('SELECT 1 FROM reviews WHERE pull_number=? AND fingerprint=?',
                           (item['number'], fingerprint)).fetchone():
                continue
            review = critique(item)
            con.execute('''INSERT INTO reviews
                (pull_number,fingerprint,observed_at,title,head_sha,state,review_json)
                VALUES (?,?,?,?,?,?,?)''',
                (item['number'], fingerprint, at, item['title'], item['head_sha'],
                 item['state'], canonical(review)))
            records.append({'pr': item['number'], 'title': item['title'],
                            'head_sha': item['head_sha'], 'review': review})
        con.execute('INSERT INTO polls(at,ok,new_reviews,problem) VALUES (?,?,?,?)',
                    (at, 1, len(records), None))
    receipt = {'schema': 'nasurayaza-watch/1', 'at': at, 'repository': REPO,
               'new_reviews': len(records), 'reviews': records,
               'mode': 'read-only deterministic critic', 'model_api_calls': 0,
               'repo_writes': 0, 'subjective_experience_claim': False}
    atomic_json(status_file, receipt)
    return receipt


def error_poll(con: sqlite3.Connection, status_file: Path, error: Exception) -> None:
    # Persist failure class only: avoids inadvertent credential/text leakage.
    at = timestamp()
    with con:
        con.execute('INSERT INTO polls(at,ok,new_reviews,problem) VALUES (?,?,?,?)',
                    (at, 0, 0, type(error).__name__))
    atomic_json(status_file, {'schema': 'nasurayaza-watch/1', 'at': at,
                              'repository': REPO, 'ok': False,
                              'error_class': type(error).__name__,
                              'mode': 'read-only deterministic critic'})


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Poll once; useful for smoke tests')
    args = parser.parse_args(argv)
    interval = parse_interval(os.environ.get('POLL_SECONDS', '900'))
    data_dir = Path(os.environ.get('NASURAYAZA_DATA', '/data'))
    if not data_dir.is_absolute():
        parser.error('NASURAYAZA_DATA must be an absolute path')
    con = database(data_dir / 'reviews.sqlite3')
    status_file = data_dir / 'status.json'
    stopping = False

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                report = poll(con, fetch_pulls(), status_file)
                print(canonical({'at': report['at'], 'new_reviews': report['new_reviews']}), flush=True)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
                error_poll(con, status_file, exc)
                print('Poll failed: ' + type(exc).__name__, file=sys.stderr, flush=True)
                if args.once:
                    return 1
            if args.once:
                break
            # Interruptible wait, without busy loops.
            for _ in range(interval):
                if stopping:
                    break
                time.sleep(1)
    finally:
        con.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
