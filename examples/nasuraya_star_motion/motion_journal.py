"""Durable, single-owner tick boundary for the pinned MotionGoal simulator.

A committed goal and receipt move together in SQLite. A separate durable
intent precedes execution. An unresolved intent blocks ALL subsequent ticks;
it is never cleared by retrying the action or by assuming it did not execute.
This is a local software-model journal, not an external actuator protocol.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3

from motion_goal import MotionGoal


class UnknownMotionOutcome(RuntimeError):
    """An attempted tick has no atomically committed full goal/receipt pair."""


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class MotionJournal:
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
                PRAGMA user_version=1;
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
                if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise ValueError('unsupported motion journal')
                yield db

    @staticmethod
    def _pending(db):
        row = db.execute('SELECT request,before_sha FROM intent WHERE id=1').fetchone()
        if row:
            raise UnknownMotionOutcome(
                'motion outcome unknown; independent validation is required; '
                'no action retried: ' + json.loads(row[0])['event_id'])

    def load(self):
        with self.owner() as db:
            self._pending(db)
            raw, head = db.execute('SELECT goal,head FROM state WHERE id=1').fetchone()
            saved = json.loads(raw)
            if saved['sha256'] != head:
                raise ValueError('journal head mismatch')
            return MotionGoal.restore(saved)

    def step(self, *, event_id, expected_head, hook=None):
        """Deduplicate an explicit caller token; never turn a retry into next tick.

        hook is a local fault-injection seam for subprocess crash regression.
        No recovery path invokes it or clears an unresolved intent.
        """
        hook = hook or (lambda stage, goal: None)
        with self.owner() as db:
            self._pending(db)
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
            goal = MotionGoal.restore(saved)
            request = goal.request()
            if event_id != request['event_id']:
                raise ValueError('unexpected motion event')
            with db:
                db.execute('INSERT INTO intent VALUES (1,?,?)', (encode(request), head))
            hook('prepared', goal)
            receipt = goal.step()
            hook('executed', goal)
            after = goal.checkpoint()
            if receipt['event_id'] != event_id or goal.task['elapsed'] != saved['payload']['task']['elapsed'] + 1:
                raise ValueError('motion receipt transition mismatch')
            with db:
                changed = db.execute('UPDATE state SET goal=?,head=? WHERE id=1 AND head=?',
                    (encode(after), after['sha256'], head)).rowcount
                if changed != 1:
                    raise ValueError('motion head changed')
                hook('writing', goal)
                db.execute('INSERT INTO receipts VALUES (?,?,?,?,?)',
                    (event_id, encode(request), encode(receipt), head, after['sha256']))
                db.execute('DELETE FROM intent WHERE id=1')
            hook('committed', goal)
            return receipt

    def inspect(self):
        """Read metadata even while recovery is blocked; never issue a command."""
        with self.owner() as db:
            head = db.execute('SELECT head FROM state WHERE id=1').fetchone()[0]
            row = db.execute('SELECT request,before_sha FROM intent WHERE id=1').fetchone()
            return dict(head=head, pending=json.loads(row[0]) if row else None,
                        before_sha=row[1] if row else None,
                        receipts=db.execute('SELECT count(*) FROM receipts').fetchone()[0])
