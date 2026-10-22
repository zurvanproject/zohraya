"""Durable local adapter for the existing, unchanged continuity.gate rules."""
import hashlib
import json
from pathlib import Path
import sqlite3

from continuity.gate import SCHEMA, claim, evaluate, finish, operator_contact, timestamp

APPLICATION_ID = 0x4e415355


class Store:
    def __init__(self, path):
        uri = Path(path).resolve().as_uri() + '?mode=rw'
        self.db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
        try:
            if self.db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise ValueError('not a Continuity Kit database; no migration or reset')
            row = self.db.execute('SELECT payload FROM control WHERE singleton=1').fetchone()
            if row is None or not isinstance(json.loads(row[0]), dict):
                raise ValueError('missing or invalid control state; no reset')
        except Exception:
            self.db.close()
            raise

    @classmethod
    def create(cls, path, now):
        when = timestamp(now).isoformat()
        path = Path(path)
        with path.open('xb'):
            pass  # Refuse every existing file, including foreign/empty databases.
        db = sqlite3.connect(path)
        try:
            with db:
                db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                db.execute('CREATE TABLE control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload TEXT NOT NULL)')
                db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,digest TEXT NOT NULL,receipt TEXT NOT NULL)')
                db.execute('CREATE TABLE runs(id TEXT PRIMARY KEY,claimed_at TEXT NOT NULL,finished_at TEXT)')
                state = dict(schema=SCHEMA, enabled=True, last_contact_at=when,
                    contact_source='Explicit local operator initialization', last_claimed_at=None,
                    inflight_run_id=None, last_completed_run_id=None)
                db.execute('INSERT INTO control VALUES(1,?)', (json.dumps(state),))
        finally:
            db.close()
        return cls(path)

    def close(self):
        self.db.close()

    def status(self, now):
        # One statement gives control and both counts the same SQLite snapshot,
        # without committing or rolling back any caller-owned transaction.
        row = self.db.execute('''SELECT payload,
            (SELECT count(*) FROM requests), (SELECT count(*) FROM runs)
            FROM control WHERE singleton=1''').fetchone()
        state = json.loads(row[0])
        return dict(state=state, decision=evaluate(state, now),
                    request_count=row[1], run_count=row[2])

    def apply(self, operation, request_id, now, run_id=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            return self._apply_in_transaction(operation, request_id, now, run_id)

    def _apply_in_transaction(self, operation, request_id, now, run_id=None):
        """Internal composition point; caller must own the write transaction."""
        if not self.db.in_transaction:
            raise ValueError('write transaction required')
        if not isinstance(request_id, str) or not 0 < len(request_id) <= 80:
            raise ValueError('request id required, at most 80 characters')
        if operation not in ('claim', 'finish', 'heartbeat', 'pause'):
            raise ValueError('unknown operation')
        payload = dict(operation=operation, now=now, run_id=run_id)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        previous = self.db.execute('SELECT digest,receipt FROM requests WHERE id=?', (request_id,)).fetchone()
        if previous:
            if previous[0] != digest:
                raise ValueError('request id already bound to different parameters')
            return json.loads(previous[1])
        state = json.loads(self.db.execute('SELECT payload FROM control WHERE singleton=1').fetchone()[0])
        if operation == 'claim':
            updated = claim(state, now, run_id)
            if self.db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise ValueError('run id cannot be reused, including historical completed runs')
            self.db.execute('INSERT INTO runs VALUES(?,?,NULL)', (run_id, timestamp(now).isoformat()))
        elif operation == 'finish':
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='local_jobs'").fetchone():
                job = self.db.execute('SELECT status FROM local_jobs WHERE run_id=?', (run_id,)).fetchone()
                if job and job[0] not in ('completed', 'abandoned'):
                    raise ValueError('local job unresolved; host reconciliation required')
            updated = finish(state, now, run_id)
            if not self.db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise ValueError('claimed run history missing')
            self.db.execute('UPDATE runs SET finished_at=? WHERE id=?', (timestamp(now).isoformat(), run_id))
        else:
            if run_id is not None:
                raise ValueError('run id is only accepted for claim or finish')
            updated = operator_contact(state, now, pause=operation == 'pause')
        receipt = dict(request_id=request_id, operation=operation, state_after=updated)
        self.db.execute('UPDATE control SET payload=? WHERE singleton=1', (json.dumps(updated),))
        self.db.execute('INSERT INTO requests VALUES(?,?,?)', (request_id, digest, json.dumps(receipt)))
        return receipt
