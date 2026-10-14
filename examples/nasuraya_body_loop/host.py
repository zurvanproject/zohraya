"""Sequential host for a source-pinned synthetic body; no model or actuator."""
from copy import deepcopy
from datetime import datetime, timedelta
import fcntl
import json
import math
import os
import sqlite3
import stat
from pathlib import Path

from reflection_cycle import ReflectionCycle, ReflectiveBody, InterruptedExecution, canonical
from unified_body_v2 import UnifiedBody
from run_reflection_demo import sleep_fixture
from synthetic_fixture import prepare_defaults, synthetic_body


KEY = 'nasuraya-body-loop'
SCHEMA = 'nasuraya-bounded-body-loop/1'
BODY_ACTIONS = ('walk', 'observe', 'sleep', 'rest')


def session_lock(path, *, create=False):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    lock = os.fdopen(fd, 'r+b')
    try:
        info = os.fstat(fd)
        # SQLite WAL sidecars are path-based; aliases must never share a ledger.
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('owned regular session without hard links required')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except BaseException:
        lock.close()
        raise


def validate_duration(duration_s):
    if (isinstance(duration_s, bool) or not isinstance(duration_s, (int, float))
            or not math.isfinite(duration_s) or not .1 <= duration_s <= 1.
            or abs(duration_s * 10 - round(duration_s * 10)) > 1e-8):
        raise ValueError('duration_s must be .1..1 in .1-second increments')


def executed_body(record):
    actual = record.get('actual_outcome') or {}
    return (record['status'] == 'complete' and actual.get('status') == 'completed'
            and 'body_receipt' in actual and 'body_checkpoint' in actual)


def describe(body):
    return {'checkpoint_sha256': body.checkpoint()['sha256'], 'revision': body.revision,
            'simulated_wall_utc': body.owner.wall_utc,
            'minimum_state': deepcopy(body.owner.body()['minimum_state']),
            'self_location': body.owner.self_location(),
            'interoceptive_summary': body.owner.interoceptive_summary(),
            'scope': 'existing software body; generated fixture, not biological measurement'}


class BodyLoop:
    def __init__(self, path, *, _lock=None):
        self.path = Path(path)
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError('existing regular body-loop session required; use start')
        # Lock the database inode, not a separately replaceable sidecar.
        self.lock = _lock if _lock is not None else session_lock(self.path)
        try:
            # Validate our own marker read-only before the legacy engine can
            # create tables or migrate its derived feedback index.
            with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as probe:
                names = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                row = probe.execute('SELECT value FROM meta WHERE key=?', (SCHEMA,)).fetchone() if 'meta' in names else None
                if row is None:
                    raise ValueError('not a body-loop session; original ledger left unchanged')
                self.config = json.loads(row[0])
            # Only an identified body-loop session may have permissions tightened.
            os.fchmod(self.lock.fileno(), 0o600)
            self.engine = ReflectionCycle(self.path)
            self.adapter = ReflectiveBody(self.engine, key=KEY)
        except BaseException:
            if hasattr(self, 'engine'): self.engine.close()
            self.lock.close()
            raise

    @classmethod
    def start(cls, path, *, fixture='normal', mode='bounded', max_actions=3):
        if fixture not in ('normal', 'sleep', 'recovery-ready') or mode not in ('observe', 'bounded'):
            raise ValueError('explicit fixture and bounded mode required')
        if type(max_actions) is not int or not 0 <= max_actions <= 100:
            raise ValueError('max_actions must be 0..100')
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive reservation prevents accidental reset of an earlier ledger.
        lock = session_lock(path, create=True)
        try:
            prepare_defaults()
            if fixture == 'recovery-ready':
                from .recovery import recovery_ready_fixture
                body = recovery_ready_fixture()
            else:
                body = sleep_fixture() if fixture == 'sleep' else synthetic_body()
            config = {'fixture': fixture, 'mode': mode, 'max_actions': max_actions,
                      'context': 'bounded-body-loop/' + fixture,
                      'initial_checkpoint_sha256': body.checkpoint()['sha256']}
            with ReflectionCycle(path) as e:
                e.attach_runtime(KEY, body.checkpoint())
                e.db.execute('INSERT INTO meta VALUES(?,?)', (SCHEMA, canonical(config)))
            return cls(path, _lock=lock)
        except BaseException:
            lock.close()
            raise

    def close(self):
        self.engine.close()
        self.lock.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def body(self):
        return UnifiedBody.restore(self.engine.runtime(KEY))

    def records(self):
        return [r for r in self.engine.export()['decisions'] if r['context'] == self.config['context']]

    def status(self):
        from .continuation import action_limit
        records = self.records()
        reserved = sum(r['selected_action'] is not None for r in records)
        maximum = action_limit(self)
        return {'schema': SCHEMA, 'fixture': self.config['fixture'], 'mode': self.config['mode'],
                'max_actions': maximum, 'actions_reserved': reserved,
                'actions_remaining': max(0, maximum - reserved),
                'completed_cycles': sum(executed_body(r) for r in records),
                'failed_cycles': sum(r['status'] == 'complete' and not executed_body(r) for r in records),
                'unresolved_running': [r['id'] for r in records if r['status'] == 'running'],
                'self_model': describe(self.body()), 'external_model_api_used': False}

    def observe(self):
        snapshot = describe(self.body())
        self.engine.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',
                               ('body-loop-observation', canonical(snapshot)))
        return snapshot

    def make_request(self, decision_id, snapshot, duration_s, preferred_action='walk'):
        at = (datetime.fromisoformat(snapshot['simulated_wall_utc']) + timedelta(seconds=duration_s)).isoformat()
        evidence = {'id': 'body', 'kind': 'observed', 'source_ref': 'runtime://UnifiedBody.checkpoint',
                    'locator': 'revision/' + str(snapshot['revision']),
                    'source_sha256': snapshot['checkpoint_sha256'],
                    'claim': {'key': 'body_revision', 'value': snapshot['revision']}, 'expires_at': at}
        actions = []
        for action in BODY_ACTIONS:
            preference = .9 if action == preferred_action else .6
            actions.append({'id': action, 'body_action': action,
                'score': dict(respect=preference, honesty=preference, balance=preference,
                    dignity=preference, compassion=preference, disharmony=0., evidence_confidence=1.,
                    consequences=[dict(probability=1., harm=.01, benefit=.5, cost=0., confidence=1.)]),
                # Revision belongs to the current observation, not the stable
                # semantic action contract used for scoped feedback retrieval.
                'claims': [], 'requires_evidence': ['body'],
                'requires_tools': ['body_cycle'], 'violates_goals': [],
                'expected_outcome': {'status': 'completed', 'selected_action': action}})
        # A high-sleep veto belongs to recovery-needed motion. Once a fresh
        # observation is ready for work, do not apply that stale condition's
        # penalty to the changed context. Existing sleepy ledgers retain recall.
        from .recovery import recommended_action
        recovered = recommended_action(snapshot['minimum_state']) == 'walk' and any(
            executed_body(r) and r['actual_outcome']['selected_action'] in ('sleep', 'rest')
            for r in self.records())
        topic = 'optional-motion/ready' if recovered else 'optional-motion'
        return {'id': decision_id, 'context': self.config['context'], 'topic': topic,
                'goal': 'Exercise local body decisions while preserving its native protection',
                'goals': [{'id': 'native_protection', 'required': True}],
                'at_utc': at, 'evidence': [evidence], 'tools': {'body_cycle': 'ok'}, 'actions': actions}

    def step(self, *, decision_id=None, duration_s=.1, preferred_action='walk'):
        validate_duration(duration_s)
        if preferred_action not in BODY_ACTIONS:
            raise ValueError('preferred_action must be walk, observe, sleep or rest')
        records = self.records()
        if decision_id is None:
            decision_id = 'body-loop-step-' + str(len(records) + 1)
        if not isinstance(decision_id, str) or not decision_id.strip() or len(decision_id) > 109:
            raise ValueError('decision_id must be a nonempty string of at most 109 characters')
        previous = self.engine.get(decision_id)
        if previous is not None:
            old_preference = max(previous['request']['actions'], key=lambda c: c['score']['respect'])['id']
            if (previous['context'] != self.config['context']
                    or previous['request'].get('execution', {}).get('duration_s') != duration_s
                    or old_preference != preferred_action):
                raise ValueError('conflicting body-loop replay')
            if previous['status'] == 'complete':
                return self.receipt(previous, replayed=True)
            if previous['status'] == 'running':
                raise InterruptedExecution('unresolved previous body execution')
        if any(r['status'] == 'running' for r in records):
            raise InterruptedExecution('reconcile the running operation before new body work')
        if self.config['mode'] != 'bounded':
            raise ValueError('body mutation disabled in observe mode')
        if self.status()['actions_remaining'] <= 0 and previous is None:
            raise ValueError('persistent action budget exhausted')
        row = self.engine.db.execute('SELECT value FROM meta WHERE key=?', ('body-loop-observation',)).fetchone()
        if row is None:
            raise ValueError('fresh observe required before body execution')
        snapshot = json.loads(row[0])
        if snapshot['checkpoint_sha256'] != self.body().checkpoint()['sha256']:
            raise ValueError('stale body observation')
        request = self.make_request(decision_id, snapshot, duration_s, preferred_action)
        # A crash can lose this token, but cannot regain budget or replay a running effect.
        self.engine.db.execute('DELETE FROM meta WHERE key=?', ('body-loop-observation',))
        record = self.adapter.cycle(request, at_utc=request['at_utc'], duration_s=duration_s)
        return self.receipt(record, replayed=False)

    def receipt(self, record, *, replayed):
        actual = record.get('actual_outcome') or {}
        receipt = actual.get('body_receipt', {})
        recorded_body = UnifiedBody.restore(actual['body_checkpoint']) if 'body_checkpoint' in actual else self.body()
        status = record['status'] if executed_body(record) else actual.get('status', record['status'])
        return {'decision_id': record['id'], 'status': status, 'ledger_status': record['status'], 'replayed': replayed,
                'requested_action': record['selected_action'], 'actual_action': actual.get('selected_action'),
                'expected_outcome_matched': (record.get('feedback') or {}).get('success'),
                'recalled_feedback_ids': record['recalled_feedback_ids'],
                'body_audit': receipt.get('whole_body_audit'),
                'prediction_scope': 'declared outcome contract; exact action match, not calibrated forecasting',
                'self_model_after': describe(recorded_body)}
