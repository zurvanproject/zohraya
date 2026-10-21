"""Durable, single-owner tick boundary for the pinned MotionGoal simulator.

A committed goal and receipt move together in SQLite. A separate durable
intent precedes execution. An unresolved intent blocks ALL subsequent ticks;
it is never cleared by retrying the action or by assuming it did not execute.
This is a local software-model journal, not an external actuator protocol.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from motion_goal import MotionGoal
from persistent_embodiment_v1 import digest, instant


class UnknownMotionOutcome(RuntimeError):
    """An attempted tick has no atomically committed full goal/receipt pair."""


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def outcome_source():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def validate_outcome(before, request, candidate, goal_type=MotionGoal):
    """Validate a locally recorded result without simulating a native action.

    Reuse MotionGoal's original bookkeeping with a receipt-only cycle adapter.
    The adapter installs the already-restored post-body and returns its cached
    receipt. No native cycle, model forecast, actuator or API is executed.
    """
    if set(candidate) != {'payload', 'sha256'} or digest(candidate['payload']) != candidate['sha256']:
        raise ValueError('outcome checksum mismatch')
    p = candidate['payload']
    if set(p) != {'schema', 'source', 'before_sha', 'request', 'after', 'receipt'}:
        raise ValueError('outcome fields')
    if p['schema'] != 'nasuraya-local-motion-outcome/1' or p['source'] != outcome_source():
        raise ValueError('outcome source/version')
    if p['before_sha'] != before['sha256'] or p['request'] != request:
        raise ValueError('outcome intent mismatch')
    prior = goal_type.restore(before)
    after = goal_type.restore(p['after'])
    if hasattr(prior, 'prepare_receipt_replay'):
        prior.prepare_receipt_replay(p['after'], request)
    if prior.request() != request:
        raise ValueError('stored intent differs from current goal')
    receipt = p['receipt']
    event = request['event_id']
    request_hash = digest(dict(external=request['external'], duration_s=request['duration_s'],
        requested=request['requested'], expected_revision=request['expected_revision'],
        at_utc=instant(request['at_utc']).isoformat()))
    if (after.body.requests.get(event) != request_hash or
        after.body.results.get(event) != receipt or receipt.get('event_id') != event or
        receipt.get('revision') != prior.body.revision + 1 or
        after.body.revision != prior.body.revision + 1):
        raise ValueError('outcome native receipt mismatch')

    def receipt_only(**actual_request):
        if actual_request != request:
            raise ValueError('outcome replay request mismatch')
        # Swap the in-memory copy only. This is not an invocation of cycle().
        prior.body.__dict__ = after.body.__dict__
        return receipt

    prior.body.cycle = receipt_only
    prior.step()
    if prior.checkpoint() != p['after']:
        raise ValueError('outcome goal transition mismatch')
    return after, receipt


class MotionJournal:
    goal_type = MotionGoal

    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

    @classmethod
    def create(cls, path, goal):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = goal.checkpoint()
        # Never replace a prior practice state, even accidentally.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), goal TEXT NOT NULL, head TEXT NOT NULL);
                CREATE TABLE intent (id INTEGER PRIMARY KEY CHECK(id=1), request TEXT NOT NULL, before_sha TEXT NOT NULL);
                CREATE TABLE receipts (event_id TEXT PRIMARY KEY, request TEXT NOT NULL,
                    receipt TEXT NOT NULL, before_sha TEXT NOT NULL, after_sha TEXT NOT NULL);
                CREATE TABLE outcome (id INTEGER PRIMARY KEY CHECK(id=1), candidate TEXT NOT NULL);
                PRAGMA user_version=2;
            ''')
            db.execute('INSERT INTO state VALUES (1,?,?)', (encode(saved), saved['sha256']))
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return cls(path)

    @contextmanager
    def owner(self):
        # Serialize readers that intend to execute, including different Python
        # processes. Keep the lock from load through the final commit/response.
        with Path(str(self.path) + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True) as db:
                db.execute('PRAGMA synchronous=FULL')
                if db.execute('PRAGMA user_version').fetchone()[0] != 2:
                    raise ValueError('unsupported motion journal')
                yield db

    @staticmethod
    def _publish(db, before_sha, after, request, receipt, hook=None, goal=None):
        with db:
            changed = db.execute('UPDATE state SET goal=?,head=? WHERE id=1 AND head=?',
                (encode(after), after['sha256'], before_sha)).rowcount
            if changed != 1:
                raise ValueError('motion head changed')
            if hook:
                hook('writing', goal)
            db.execute('INSERT INTO receipts VALUES (?,?,?,?,?)',
                (request['event_id'], encode(request), encode(receipt), before_sha, after['sha256']))
            db.execute('DELETE FROM intent WHERE id=1')
            db.execute('DELETE FROM outcome WHERE id=1')

    def _recover(self, db):
        pending = db.execute('SELECT request,before_sha FROM intent WHERE id=1').fetchone()
        row = db.execute('SELECT candidate FROM outcome WHERE id=1').fetchone()
        if not pending:
            if row:
                raise ValueError('orphan motion outcome')
            return dict(status='clean')
        if not row:
            self._pending(db)
        raw, head = db.execute('SELECT goal,head FROM state WHERE id=1').fetchone()
        before = json.loads(raw)
        if head != pending[1] or before['sha256'] != head:
            raise ValueError('outcome prior head mismatch')
        request = json.loads(pending[0])
        goal, receipt = validate_outcome(before, request, json.loads(row[0]), self.goal_type)
        self._publish(db, head, goal.checkpoint(), request, receipt)
        return dict(status='recovered', event_id=request['event_id'],
                    receipt_sha256=digest(receipt), native_actions_executed=0)

    def recover(self):
        """Publish only a validated durable local outcome; never retry a tick."""
        with self.owner() as db:
            return self._recover(db)

    @staticmethod
    def _pending(db):
        row = db.execute('SELECT request,before_sha FROM intent WHERE id=1').fetchone()
        if row:
            raise UnknownMotionOutcome(
                'motion outcome unknown; independent validation is required; '
                'no action retried: ' + json.loads(row[0])['event_id'])

    def load(self):
        with self.owner() as db:
            self._recover(db)
            raw, head = db.execute('SELECT goal,head FROM state WHERE id=1').fetchone()
            saved = json.loads(raw)
            if saved['sha256'] != head:
                raise ValueError('journal head mismatch')
            return self.goal_type.restore(saved)

    def step(self, *, event_id, expected_head, hook=None, current_goal=None):
        """Deduplicate an explicit caller token; never turn a retry into next tick.

        hook is a local fault-injection seam for subprocess crash regression.
        No recovery path invokes it or clears an unresolved intent.
        """
        hook = hook or (lambda stage, goal: None)
        with self.owner() as db:
            self._recover(db)
            prior = db.execute('SELECT receipt,before_sha FROM receipts WHERE event_id=?', (event_id,)).fetchone()
            if prior:
                if prior[1] != expected_head:
                    raise ValueError('conflicting retry token')
                return json.loads(prior[0])
            raw, head = db.execute('SELECT goal,head FROM state WHERE id=1').fetchone()
            if head != expected_head:
                raise ValueError('stale motion writer')
            saved = json.loads(raw)
            if saved['sha256'] != head:
                raise ValueError('journal head mismatch')
            if current_goal is None:
                goal = self.goal_type.restore(saved)
            else:
                # A process-local owner may avoid another expensive restore.
                # Verify the complete state while holding the same owner lock.
                if type(current_goal) is not self.goal_type or current_goal.checkpoint() != saved:
                    raise ValueError('cached goal differs from committed head; reload required')
                goal = current_goal
            request = goal.request()
            if event_id != request['event_id']:
                raise ValueError('unexpected motion event')
            with db:
                db.execute('INSERT INTO intent VALUES (1,?,?)', (encode(request), head))
            hook('prepared', goal)
            before_elapsed = goal.task['elapsed']
            receipt = goal.step()
            hook('executed', goal)
            after = goal.checkpoint()
            if receipt['event_id'] != event_id or goal.task['elapsed'] != before_elapsed + 1:
                raise ValueError('motion receipt transition mismatch')
            payload = dict(schema='nasuraya-local-motion-outcome/1', source=outcome_source(),
                before_sha=head, request=request, after=after, receipt=receipt)
            candidate = dict(payload=payload, sha256=digest(payload))
            with db:
                db.execute('INSERT INTO outcome VALUES (1,?)', (encode(candidate),))
            hook('outcome_saved', goal)
            self._publish(db, head, after, request, receipt, hook, goal)
            hook('committed', goal)
            return receipt

    def inspect(self):
        """Read metadata even while recovery is blocked; never issue a command."""
        with self.owner() as db:
            head = db.execute('SELECT head FROM state WHERE id=1').fetchone()[0]
            row = db.execute('SELECT request,before_sha FROM intent WHERE id=1').fetchone()
            return dict(head=head, pending=json.loads(row[0]) if row else None,
                        before_sha=row[1] if row else None,
                        durable_outcome=db.execute('SELECT count(*) FROM outcome').fetchone()[0] == 1,
                        receipts=db.execute('SELECT count(*) FROM receipts').fetchone()[0])
