"""Authored engineering model inspired by CPM, Sentipolis and affective memory.

No copied research implementation, trained emotion vectors, network calls or
actuator execution. Caller supplies appraisals; this is not a text classifier.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from runtimes.tadash_body.decision_core import Action, Consequence, DecisionCore
from runtimes.tadash_body import decision_core

SCHEMA = 'nasuraya-affective-continuity/1'
CHANNELS = ('joy', 'sadness', 'contentment', 'excitement', 'fear', 'frustration')
CHECKS = ('relevance', 'goal_congruence', 'controllability', 'novelty',
          'certainty', 'progress', 'loss', 'threat', 'norm_conflict')
TENDENCIES = ('explore', 'repair', 'verify', 'consolidate')
CAPACITY = 10000
NEAR_TIE = .08
MAX_BONUS = .04


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value, name, low=0., high=1.):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high):
        raise ValueError(f'{name}: finite number in [{low}, {high}] required')
    return float(value)


def text(value, name, limit=512):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name}: nonempty string up to {limit} characters required')
    return value


def validate_event(event):
    required = {'id', 'context', 'topic', 'summary', 'source', 'cues',
                'elapsed_hours', 'appraisal'}
    if not isinstance(event, dict) or set(event) != required:
        raise ValueError('exact event fields required')
    e = json.loads(canonical(event))
    for key in ('id', 'context', 'topic'):
        text(e[key], key, 128)
    text(e['summary'], 'summary', 2048)
    source = e['source']
    if (not isinstance(source, dict) or set(source) != {'kind', 'locator'}
            or source['kind'] not in ('observed', 'inference', 'authored')):
        raise ValueError('source kind and locator required')
    text(source['locator'], 'source locator', 2048)
    cues = e['cues']
    if not isinstance(cues, list) or not 1 <= len(cues) <= 16:
        raise ValueError('1..16 explicit retrieval cues required')
    e['cues'] = sorted(set(text(c, 'cue', 80).strip().casefold() for c in cues))
    e['elapsed_hours'] = number(e['elapsed_hours'], 'elapsed_hours', 0, 8760)
    if not isinstance(e['appraisal'], dict) or set(e['appraisal']) != set(CHECKS):
        raise ValueError('all appraisal checks must be explicit')
    e['appraisal'] = {k: number(v, k, -1 if k == 'goal_congruence' else 0)
                      for k, v in e['appraisal'].items()}
    return e


def initial_state():
    return dict(schema=SCHEMA, clock_hours=0., revision=0,
                fast=dict.fromkeys(CHANNELS, 0.), mood=dict.fromkeys(CHANNELS, 0.))


def effective(state):
    return {k: .8 * state['fast'][k] + .2 * state['mood'][k] for k in CHANNELS}


def valence(values):
    return max(values[k] for k in ('joy', 'contentment', 'excitement')) - max(
        values[k] for k in ('sadness', 'fear', 'frustration'))


def evolve(state, event):
    a = event['appraisal']
    gain = a['relevance'] * a['certainty']
    positive, negative = max(0., a['goal_congruence']), max(0., -a['goal_congruence'])
    pulse = dict(
        joy=positive * (.6 + .4*a['progress']),
        contentment=positive * a['progress'] * (1-a['novelty']),
        excitement=positive * a['novelty'],
        sadness=min(1., negative * (1-.6*a['controllability']) + .5*a['loss']),
        fear=a['threat'] * (1-.5*a['controllability']),
        frustration=min(1., negative*a['controllability']*(1-a['progress']) + .3*a['norm_conflict']))
    after = json.loads(canonical(state))
    for k in CHANNELS:
        # Two independently decaying stores: one-hour response, 24-hour mood.
        fast = state['fast'][k] * 2**(-event['elapsed_hours'])
        slow = state['mood'][k] * 2**(-event['elapsed_hours']/24)
        after['fast'][k] = fast + .6*gain*pulse[k]*(1-fast)
        after['mood'][k] = slow + .1*gain*pulse[k]*(1-slow)
    after['clock_hours'] += event['elapsed_hours']
    after['revision'] += 1
    return after, {k: gain*v for k, v in pulse.items()}


def validate_options(options):
    if not isinstance(options, list) or not 1 <= len(options) <= 32:
        raise ValueError('1..32 options required')
    parsed = []
    for option in options:
        if not isinstance(option, dict) or set(option) != {'action', 'tendencies'}:
            raise ValueError('native action and explicit tendencies required')
        a = dict(option['action'])
        a['consequences'] = tuple(Consequence(**c) for c in a['consequences'])
        action = Action(**a)
        if set(option['tendencies']) != set(TENDENCIES):
            raise ValueError('all tendencies must be explicit')
        tendencies = {k: number(v, k) for k, v in option['tendencies'].items()}
        parsed.append((action, tendencies))
    if len({a.id for a, _ in parsed}) != len(parsed):
        raise ValueError('unique action IDs required')
    return sorted(parsed, key=lambda pair: pair[0].id)


def rank(state, parsed, memories, *, use_affect=True):
    """Native ethics/risk first; affect may reorder only near-equal candidates.

    Retrieval supplies context to the caller, never extra factual confidence.
    Recalled verified corrections can boost verification, not evidence scores.
    """
    baseline = DecisionCore().decide([a for a, _ in parsed]).to_dict()
    values = effective(state)
    arousal = max(values[k] for k in ('excitement', 'fear', 'frustration'))
    drives = dict(explore=values['excitement']*(1-arousal),
                  repair=max(values['sadness'], values['frustration']),
                  verify=max(values['fear'], max(0., arousal-.45)),
                  consolidate=max(values['joy'], values['contentment']))
    # A remembered adverse observed event asks for checking, not presumed failure.
    if any(m['source']['kind'] == 'observed' and m['valence'] < -.1 for m in memories):
        drives['verify'] = max(drives['verify'], .5)
    tendencies = {a.id: t for a, t in parsed}
    allowed = [o for o in baseline['options'] if o['eligible']]
    best = max((o['score'] for o in allowed), default=0.)
    rows = []
    for row in baseline['options']:
        eligible = row['eligible'] and best-row['score'] <= NEAR_TIE
        # Positive affect never contributes more than MAX_BONUS to any score.
        bonus = MAX_BONUS * max(drives[k]*tendencies[row['action_id']][k]
                                for k in TENDENCIES) if use_affect and eligible else 0.
        rows.append(dict(row, affective_bonus=bonus, adjusted_score=row['score']+bonus,
                         within_affective_window=eligible))
    ranked = sorted((r for r in rows if r['within_affective_window']),
                    key=lambda r: (-r['adjusted_score'], r['uncertainty'], r['action_id']))
    return dict(selected_action=ranked[0]['action_id'] if ranked else None,
                baseline_selected_action=baseline['selected_action'], options=rows,
                affect_enabled=use_affect, tendencies=drives,
                disposition='plan_only', arousal=arousal)


class AffectiveAgent:
    """Atomic state/episode/decision ledger; safe to reopen in a fresh process."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.engine_hash = digest({str(p.name): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(__file__), Path(decision_core.__file__))})
        try:
            names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if names and names != {'meta', 'events'}:
                raise ValueError('not an affective-continuity ledger; no implicit migration')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            with self.transaction():
                self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, seq INTEGER UNIQUE NOT NULL, context TEXT NOT NULL, topic TEXT NOT NULL, request_sha TEXT NOT NULL, record TEXT NOT NULL)')
                self.db.execute('CREATE INDEX IF NOT EXISTS scoped_memory ON events(context,topic,seq)')
                row = self.db.execute("SELECT value FROM meta WHERE key='contract'").fetchone()
                contract = canonical(dict(schema=SCHEMA, engine_hash=self.engine_hash))
                if row is None:
                    if names:
                        raise ValueError('missing ledger contract')
                    self.db.execute('INSERT INTO meta VALUES(?,?)', ('contract', contract))
                    self._save_state(initial_state())
                elif row[0] != contract:
                    raise ValueError('source/version changed; explicit migration required')
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def state(self):
        envelope = json.loads(self.db.execute("SELECT value FROM meta WHERE key='state'").fetchone()[0])
        if digest(envelope['value']) != envelope['sha256']:
            raise ValueError('state integrity mismatch')
        return envelope['value']

    def _save_state(self, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',
                        ('state', canonical(dict(value=value, sha256=digest(value)))))

    def recall(self, context, topic, cues, state=None):
        state = self.state() if state is None else state
        values = effective(state)
        query = {text(c, 'cue', 80).strip().casefold() for c in cues}
        rows = self.db.execute('SELECT record FROM events WHERE context=? AND topic=? ORDER BY seq DESC LIMIT 256',
                               (context, topic)).fetchall()
        ranked = []
        for row in rows:
            envelope = json.loads(row[0])
            record = envelope['value']
            if digest(record) != envelope['sha256']:
                raise ValueError('memory integrity mismatch')
            event = record['event']
            old_cues = set(event['cues'])
            overlap = len(query & old_cues) / max(1, len(query | old_cues))
            if not overlap:
                continue  # emotional similarity alone is insufficient relevance
            old = effective(record['state_after'])
            congruence = 1 - sum(abs(old[k]-values[k]) for k in CHANNELS)/len(CHANNELS)
            ranked.append(dict(event_id=event['id'], summary=event['summary'],
                               source=event['source'], valence=valence(old),
                               retrieval_score=.8*overlap+.2*congruence,
                               cues=event['cues'], historical=True))
        ranked.sort(key=lambda r: (-r['retrieval_score'], r['event_id']))
        selected = ranked[:3]
        # Include a relevant contrasting memory when available to limit one-sided recall.
        contrast = next((r for r in ranked if r['valence']*valence(values) < -.01), None)
        if contrast and contrast not in selected:
            selected = selected[:2] + [contrast]
        return selected

    def step(self, event, options, *, use_affect=True, use_memory=True):
        if type(use_affect) is not bool or type(use_memory) is not bool:
            raise ValueError('explicit boolean ablation switches required')
        event = validate_event(event)
        parsed = validate_options(options)
        normalized_options = [dict(action=asdict(a), tendencies=t) for a, t in parsed]
        request_sha = digest(dict(event=event, options=normalized_options,
                                  use_affect=use_affect, use_memory=use_memory))
        with self.transaction():
            old = self.db.execute('SELECT request_sha,record FROM events WHERE id=?', (event['id'],)).fetchone()
            if old:
                if old['request_sha'] != request_sha:
                    raise ValueError('conflicting replay; event already applied')
                envelope = json.loads(old['record'])
                if digest(envelope['value']) != envelope['sha256']:
                    raise ValueError('receipt integrity mismatch')
                return dict(envelope['value'], replayed=True)
            before = self.state()
            if before['revision'] >= CAPACITY:
                raise ValueError('ledger capacity reached; explicit archival required')
            after, pulse = evolve(before, event)
            memories = self.recall(event['context'], event['topic'], event['cues'], after) if use_memory else []
            decision = rank(after, parsed, memories, use_affect=use_affect)
            now = datetime.now(timezone.utc)
            record = dict(event=event, state_before=before, state_after=after, pulse=pulse,
                          recalled=memories, decision=decision, options=normalized_options,
                          use_memory=use_memory, replayed=False, engine_hash=self.engine_hash,
                          recorded_at_utc=now.isoformat(),
                          recorded_at_tehran=now.astimezone(ZoneInfo('Asia/Tehran')).isoformat())
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                            (event['id'], after['revision'], event['context'], event['topic'],
                             request_sha, canonical(dict(value=record, sha256=digest(record)))))
            self._save_state(after)
        return record
