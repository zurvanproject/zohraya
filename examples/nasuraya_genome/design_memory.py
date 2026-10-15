"""Bounded external design experience using the project's intent/result pattern.

An unresolved simulator call is never retried implicitly. Decisions and metrics
are replay-validated against their historical evidence prefix. Hashes assume a
trusted host; they are not signatures of physical-world observations.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3

from .chromosomes import digest
from .design_decision import SCHEMA, choose, contract, evidence, intent, verify_evidence


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identifier(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,70}', value):
        raise ValueError('bounded stable identifier required')
    return value


def replay(c, events):
    if c != contract():
        raise ValueError('experience source/policy/context contract mismatch')
    if len(events) > c['policy']['max_events']:
        raise ValueError('experience event budget exceeded')
    head = digest(c)
    state = dict(observations={}, trials={}, decisions={}, pending=[], events=0, head_sha256=head)
    ids = set()
    for seq, envelope in enumerate(events, 1):
        p = envelope['payload']
        if (set(envelope) != {'payload', 'sha256'} or
                set(p) != {'sequence', 'event_id', 'previous_sha256', 'kind', 'body'} or
                type(p['sequence']) is not int or p['sequence'] != seq or
                p['previous_sha256'] != head or p['event_id'] in ids or envelope['sha256'] != digest(p)):
            raise ValueError('damaged, reordered or conflicting experience event')
        ids.add(p['event_id'])
        b = p['body']
        if p['kind'] == 'trial_begin':
            if set(b) != {'trial_id', 'candidate', 'intent'}:
                raise ValueError('invalid trial intent fields')
            identifier(b['trial_id'])
            if (p['event_id'] != 'trial.' + b['trial_id'] + '.begin' or
                    state['pending'] or b['trial_id'] in state['trials'] or
                    b['candidate'] in state['observations'] or b['intent'] != intent(c, b['candidate'])):
                raise ValueError('unresolved, duplicate or mismatched trial intent')
            state['trials'][b['trial_id']] = dict(intent=deepcopy(b), result=None)
            state['pending'] = [b['trial_id']]
        elif p['kind'] == 'trial_finish':
            if set(b) != {'trial_id', 'candidate', 'evidence'}:
                raise ValueError('invalid trial result fields')
            prior = state['trials'].get(b['trial_id'])
            if (p['event_id'] != 'trial.' + b['trial_id'] + '.finish' or
                    state['pending'] != [b['trial_id']] or prior is None or prior['result'] is not None or
                    b['candidate'] != prior['intent']['candidate']):
                raise ValueError('unmatched or repeated trial result')
            verify_evidence(c, b['candidate'], b['evidence'])
            source = b['evidence']['source']
            if source['kind'] == 'fresh_sandbox_execution' and source['physical_trial_id'] != b['trial_id']:
                raise ValueError('fresh result belongs to a different trial')
            prior['result'] = deepcopy(b['evidence'])
            state['observations'][b['candidate']] = deepcopy(b['evidence'])
            state['pending'] = []
        elif p['kind'] == 'choice':
            if set(b) != {'decision_id', 'requested_context', 'use_memory', 'recommendation'}:
                raise ValueError('invalid choice fields')
            identifier(b['decision_id'])
            if p['event_id'] != 'choice.' + b['decision_id']:
                raise ValueError('choice event identity mismatch')
            expected = choose(c, state['observations'], pending=state['pending'],
                              requested_context=b['requested_context'], use_memory=b['use_memory'])
            if b['recommendation'] != expected:
                raise ValueError('choice does not match prior evidence and frozen policy')
            state['decisions'][b['decision_id']] = deepcopy(b)
        else:
            raise ValueError('unsupported experience event kind')
        head = envelope['sha256']
    state.update(events=len(events), head_sha256=head)
    return state


class DesignMemory:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.verify()

    @classmethod
    def create(cls, path):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        c = contract()
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('CREATE TABLE contract(value TEXT NOT NULL);'
                             'CREATE TABLE events(seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, value TEXT NOT NULL);')
            db.execute('INSERT INTO contract VALUES (?)', (encode(c),))
        return cls(path)

    def connection(self):
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _read(self, db):
        rows = db.execute('SELECT value FROM contract').fetchall()
        if len(rows) != 1:
            raise ValueError('ambiguous experience contract')
        c = json.loads(rows[0][0])
        events = []
        for seq, eid, raw in db.execute('SELECT seq,event_id,value FROM events ORDER BY seq'):
            event = json.loads(raw)
            if seq != event['payload']['sequence'] or eid != event['payload']['event_id']:
                raise ValueError('event index mismatch')
            events.append(event)
        return c, events, replay(c, events)

    def verify(self):
        with self.connection() as db:
            return self._read(db)[2]

    def _append(self, db, c, events, kind, eid, body):
        p = dict(sequence=len(events)+1, event_id=eid,
                 previous_sha256=events[-1]['sha256'] if events else digest(c), kind=kind, body=body)
        envelope = dict(payload=p, sha256=digest(p))
        state = replay(c, events + [envelope])
        db.execute('INSERT INTO events VALUES (?,?,?)', (p['sequence'], eid, encode(envelope)))
        return state

    def begin(self, name, trial_id):
        identifier(trial_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            c, events, state = self._read(db)
            desired = dict(trial_id=trial_id, candidate=name, intent=intent(c, name))
            prior = state['trials'].get(trial_id)
            if prior:
                if prior['intent'] != desired:
                    raise ValueError('conflicting trial replay')
                return dict(status='completed' if prior['result'] is not None else 'unresolved',
                            evidence=prior['result'])
            state = self._append(db, c, events, 'trial_begin', 'trial.' + trial_id + '.begin', desired)
            return dict(status='created', intent=desired)

    def finish(self, trial_id, receipt, source):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            c, events, state = self._read(db)
            prior = state['trials'].get(trial_id)
            if prior is None:
                raise ValueError('no prior intent')
            name = prior['intent']['candidate']
            obs = evidence(c, name, receipt, source)
            if prior['result'] is not None:
                if obs != prior['result']:
                    raise ValueError('conflicting result replay')
                return deepcopy(obs)
            self._append(db, c, events, 'trial_finish', 'trial.' + trial_id + '.finish',
                         dict(trial_id=trial_id, candidate=name, evidence=obs))
            return obs

    def recommend(self, *, requested_context=None, use_memory=True):
        with self.connection() as db:
            c, _, state = self._read(db)
            return choose(c, state['observations'], pending=state['pending'],
                          requested_context=requested_context, use_memory=use_memory)

    def record_choice(self, decision_id, *, requested_context=None, use_memory=True):
        identifier(decision_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            c, events, state = self._read(db)
            prior = state['decisions'].get(decision_id)
            if prior:
                if prior['requested_context'] != requested_context or prior['use_memory'] != use_memory:
                    raise ValueError('conflicting decision replay')
                return deepcopy(prior['recommendation'])
            result = choose(c, state['observations'], pending=state['pending'],
                            requested_context=requested_context, use_memory=use_memory)
            self._append(db, c, events, 'choice', 'choice.' + decision_id,
                         dict(decision_id=decision_id, requested_context=requested_context,
                              use_memory=use_memory, recommendation=result))
            return result

    def export(self):
        with self.connection() as db:
            c, events, _ = self._read(db)
            p = dict(schema=SCHEMA, contract=c, events=events)
            return dict(payload=p, sha256=digest(p))

    @classmethod
    def restore(cls, path, saved):
        if (set(saved) != {'payload', 'sha256'} or saved['sha256'] != digest(saved['payload']) or
                set(saved['payload']) != {'schema', 'contract', 'events'} or saved['payload']['schema'] != SCHEMA):
            raise ValueError('invalid portable experience checkpoint')
        p = saved['payload']
        replay(p['contract'], p['events'])  # Validate fully before creating any destination.
        memory = cls.create(path)
        with memory.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for event in p['events']:
                row = event['payload']
                db.execute('INSERT INTO events VALUES (?,?,?)', (row['sequence'], row['event_id'], encode(event)))
        return cls(path)
