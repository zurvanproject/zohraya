#!/usr/bin/env python3
"""Nasuraya Frontier Lab: bounded rootless offline evidence and hypothesis loop.

No mutation of Awake, original backups, models, SSH, GitHub, or operating system.
Model text is untrusted draft data. Observations are limited to local scalars.
Each UTC day has at most one reservation, even after interruption/reboot.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request

HOME = Path('/var/lib/nasuraya/frontier-lab')
MODEL = 'qwen3:0.6b'
GEN_URL = 'http://127.0.0.1:11434/api/generate'
METRICS = ('load_1min', 'memory_available_pct', 'disk_available_pct')
ZERO = '0' * 64
MAX_DAYS = 180


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def observation():
    # OS-controlled numeric scalar data only. No secrets, patient data or logs.
    with open('/proc/loadavg', encoding='ascii') as fh:
        load = float(fh.read().split()[0])
    memory = {}
    with open('/proc/meminfo', encoding='ascii') as fh:
        for line in fh:
            key, sep, rest = line.partition(':')
            if sep and key in ('MemTotal', 'MemAvailable'):
                memory[key] = int(rest.strip().split()[0])
    disk = os.statvfs('/')
    if memory['MemTotal'] <= 0 or disk.f_blocks <= 0:
        raise ValueError('Invalid system metrics')
    return {
        'load_1min': round(load, 4),
        'memory_available_pct': round(100 * memory['MemAvailable']/memory['MemTotal'], 3),
        'disk_available_pct': round(100 * disk.f_bavail / disk.f_blocks, 3),
    }


def connect(path):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Symlinked state rejected')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=6, isolation_level=None)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=6000')
    db.executescript("""
    CREATE TABLE IF NOT EXISTS days (
      day TEXT PRIMARY KEY, state TEXT NOT NULL, at_utc TEXT NOT NULL,
      obs_json TEXT NOT NULL, forecast_json TEXT NOT NULL,
      score_json TEXT NOT NULL, frontier TEXT NOT NULL,
      model_status TEXT NOT NULL, model_question TEXT NOT NULL,
      previous TEXT NOT NULL, digest TEXT NOT NULL
    );""")
    return db


def score_and_frontier(rows, current):
    """Prequential forecast: prediction precedes observation, no holdout leakage.

    Estimates medians from past scalar observations, then scores only against
    the *new* sample. The largest surprise becomes tomorrow's research frontier.
    This measures adaptation to *host telemetry*, not general intelligence.
    """
    old = [json.loads(x[0]) for x in rows[-MAX_DAYS:]]
    forecast = {}
    scores = {}
    for key in METRICS:
        hist = sorted(float(x[key]) for x in old if key in x)
        if hist:
            middle = len(hist) // 2
            median = (hist[middle] if len(hist) % 2 else
                      (hist[middle-1] + hist[middle]) / 2)
            errors = sorted(abs(v-median) for v in hist)
            mad = errors[len(errors)//2] if errors else 0.0
            spread = max(mad, 1.0 if key == 'load_1min' else 2.0)
            forecast[key] = round(median, 4)
            scores[key] = round(abs(current[key] - median) / spread, 3)
        else:
            forecast[key] = None
            scores[key] = None
    known_scores = {k:v for k,v in scores.items() if v is not None}
    focus = max(known_scores, key=lambda k: (known_scores[k], k)) if known_scores else 'baseline'
    return forecast, scores, focus


def local_question(focus, forecast, current, *, opener=urllib.request.urlopen):
    """Optional localhost-only Qwen. Never executes output as an instruction."""
    safe = {
        'model': MODEL, 'stream': False, 'think': False, 'keep_alive': '2m',
        'prompt': ('/no_think Provide ONE brief Persian falsifiable question about '
                   'the following bounded host telemetry. This is only a hypothesis. '
                   'Do not assert you tested it or request commands/credentials. '
                   + canonical({'topic':focus, 'previous_prediction':forecast.get(focus),
                                'observation':current.get(focus)})),
        'options': {'num_ctx':512, 'num_predict':95},
    }
    req = urllib.request.Request(GEN_URL, data=canonical(safe).encode('utf-8'),
                                 headers={'Content-Type':'application/json'})
    with opener(req, timeout=35) as response:
        result = json.load(response)
    ans = result.get('response')
    if result.get('done') is not True or not isinstance(ans, str) or not ans.strip():
        raise ValueError('LLM generated no completed answer')
    return ans.strip()[:700]


def run(db, *, now=None, sample=None, questioner=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() != dt.timedelta(0):
        raise ValueError('UTC time required')
    day = now.date().isoformat()
    sample = observation() if sample is None else sample
    if (not isinstance(sample, dict) or set(sample) != set(METRICS)
            or any(type(sample[k]) not in (float, int) or not (0 <= sample[k] <= 1e6)
                   for k in METRICS)):
        raise ValueError('Unexpected observation schema')
    db.execute('BEGIN IMMEDIATE')
    try:
        previous = db.execute('SELECT day,digest FROM days ORDER BY day DESC LIMIT 1').fetchone()
        if previous and day < previous[0]:
            raise ValueError('Cannot backfill earlier days')
        if db.execute('SELECT 1 FROM days WHERE day=?', (day,)).fetchone():
            db.commit()
            return {'status':'already_recorded','day':day}
        prior = db.execute('SELECT obs_json FROM days ORDER BY day DESC LIMIT ?',
                           (MAX_DAYS,)).fetchall()
        forecast, score, focus = score_and_frontier(prior, sample)
        # Reserve BEFORE the model call. Crash/timeout leaves only bounded draft.
        prev = previous[1] if previous else ZERO
        record = {'day':day, 'at_utc':now.isoformat(), 'observation':sample,
                  'forecast':forecast, 'score':score, 'frontier':focus,
                  'model_status':'not_attempted', 'model_question':'',
                  'previous':prev}
        hash_value = digest(record)
        db.execute('INSERT INTO days VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (day,'reserved',record['at_utc'],canonical(sample),canonical(forecast),
                   canonical(score),focus,'not_attempted','',prev,hash_value))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    model_status = 'unavailable'
    question = ''
    if questioner is not False:
        try:
            question = (questioner or local_question)(focus, forecast, sample)
            if not isinstance(question, str) or not question.strip():
                raise ValueError('Empty hypothesis')
            model_status = 'UNVERIFIED_DRAFT'
            question = question[:700]
        except Exception as e:
            model_status = 'unavailable:' + type(e).__name__
    record['model_status'] = model_status
    record['model_question'] = question
    checksum = digest(record)
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('UPDATE days SET state=?,model_status=?,model_question=?,digest=? '
                   'WHERE day=? AND state=?',
                   ('completed',model_status,question,checksum,day,'reserved'))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {'status':'completed','day':day,'samples_before':len(prior),
            'frontier':focus,'predictions_scored':sum(x is not None for x in score.values()),
            'model':model_status,'network_external':False,'privileged_actions':0}


def verify(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('SQLite integrity failed')
    previous = ZERO
    count = 0
    for rec in db.execute('SELECT day,state,at_utc,obs_json,forecast_json,score_json,'
                          'frontier,model_status,model_question,previous,digest '
                          'FROM days ORDER BY day'):
        day,state,stamp,obs,forecast,scores,focus,mstatus,question,parent,checksum = rec
        if parent != previous or state != 'completed':
            raise ValueError('Incomplete or broken chain')
        body = {'day':day,'at_utc':stamp,'observation':json.loads(obs),
                'forecast':json.loads(forecast),'score':json.loads(scores),
                'frontier':focus,'model_status':mstatus,'model_question':question,
                'previous':parent}
        if checksum != digest(body):
            raise ValueError('Receipt mismatch')
        previous = checksum
        count += 1
    return {'status':'ok','days':count,'last_hash':previous}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1,3) or argv[0] not in ('run','verify','status'):
        raise SystemExit('usage: nasu_frontier_lab.py run|verify|status [--db PATH]')
    dbpath = HOME/'frontier.sqlite3'
    if len(argv) == 3:
        if argv[1] != '--db':
            raise SystemExit('Unrecognized argument')
        dbpath = Path(argv[2])
    if os.geteuid() == 0 and dbpath == HOME/'frontier.sqlite3':
        raise SystemExit('Refusing production execution as root')
    os.umask(0o077)
    with connect(dbpath) as db:
        result = run(db) if argv[0] == 'run' else verify(db)
    print(canonical(result))


if __name__ == '__main__':
    main()
