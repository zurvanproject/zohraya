"""One bounded local effect: a deterministic integrity report stored in SQLite.

No shell, callbacks, scheduler, arbitrary file output or external actions.
Trusted local operators share the Store's time/authorization boundary.
"""
import hashlib
import json

from continuity.gate import timestamp
from .store import Store

MAX_INPUT_BYTES = 65536


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _records(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_INPUT_BYTES:
        raise ValueError('input must be bytes, at most 65536 bytes')
    try:
        records = json.loads(raw.decode('utf-8'))
    except RecursionError as exc:
        raise ValueError('input JSON nesting is excessive') from exc
    if (not isinstance(records, list) or len(records) > 256 or
            any(not isinstance(r, str) or len(r) > 256 for r in records)):
        raise ValueError('input must be a JSON list of at most 256 strings, each at most 256 characters')
    for record in records:
        record.encode('utf-8')  # Reject lone surrogates before consuming a claim.
    return records


def integrity_report(raw):
    """Hash exact input bytes and each UTF-8 string, preserving record order."""
    encoded = [r.encode('utf-8') for r in _records(raw)]
    return dict(schema='nasuraya-local-integrity/1', input_sha256=hashlib.sha256(raw).hexdigest(),
                input_bytes=len(raw), record_count=len(encoded),
                utf8_bytes=sum(map(len, encoded)),
                record_sha256=[hashlib.sha256(r).hexdigest() for r in encoded])


class LocalJobs:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.db
        # Additive optional extension; original control, budget and receipts stay intact.
        self.db.execute('''CREATE TABLE IF NOT EXISTS local_jobs(
            run_id TEXT PRIMARY KEY REFERENCES runs(id), request_id TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, input BLOB NOT NULL, status TEXT NOT NULL,
            result TEXT, resolution TEXT)''')

    def inspect(self, run_id):
        row = self.db.execute('SELECT request_id,status,result,resolution FROM local_jobs WHERE run_id=?',
                              (run_id,)).fetchone()
        if row is None:
            raise ValueError('unknown local run')
        return dict(run_id=run_id, request_id=row[0], status=row[1],
                    result=json.loads(row[2]) if row[2] else None,
                    resolution=json.loads(row[3]) if row[3] else None)

    def start(self, request_id, run_id, now, raw):
        # Validate BEFORE consuming budget; no report is published yet.
        _records(raw)
        digest = hashlib.sha256(canonical(dict(kind='integrity-v1', now=now, run_id=run_id,
                                  input_sha256=hashlib.sha256(raw).hexdigest())).encode()).hexdigest()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            prior = self.db.execute('SELECT run_id,digest FROM local_jobs WHERE request_id=?',
                                    (request_id,)).fetchone()
            if prior:
                if prior[1] != digest:
                    raise ValueError('request id already bound to different local parameters')
                # Replayed admission is NEVER execution authority, even after a crash.
                job = self.inspect(prior[0])
                if job['status'] == 'running':
                    raise ValueError('local outcome unknown; host reconciliation required')
                return dict(execute=False, job=job)
            if self.db.execute('SELECT 1 FROM requests WHERE id=?', (request_id,)).fetchone():
                raise ValueError('existing admission has no local binding; host review required')
            self.store._apply_in_transaction('claim', request_id, now, run_id)
            self.db.execute('INSERT INTO local_jobs VALUES(?,?,?,?,?,NULL,NULL)',
                            (run_id, request_id, digest, raw, 'running'))
        return dict(execute=True, job=self.inspect(run_id))

    def run(self, request_id, run_id, now, raw):
        admission = self.start(request_id, run_id, now, raw)
        if not admission['execute']:
            return admission['job']
        # Only the process that just won the claim may enter this private step.
        return self._complete(run_id, now)

    def _complete(self, run_id, now):
        row = self.db.execute('SELECT input,status FROM local_jobs WHERE run_id=?', (run_id,)).fetchone()
        if row is None or row[1] != 'running':
            raise ValueError('local job is not running')
        result = integrity_report(row[0])
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            changed = self.db.execute("UPDATE local_jobs SET status='completed',result=? WHERE run_id=? AND status='running'",
                                      (canonical(result), run_id)).rowcount
            if changed != 1:
                raise ValueError('run already reconciled; result will not be published')
            self.store._apply_in_transaction('finish', 'local-finish-'+hashlib.sha256(run_id.encode()).hexdigest(), now, run_id)
        return self.inspect(run_id)

    def abandon(self, request_id, run_id, now, operator, evidence, worker_stopped=False):
        """Host-only attestation: process stopped, discard unpublished computation.

        Never reexecutes, refunds budget or marks a lost result successful.
        """
        timestamp(now)
        if worker_stopped is not True or not operator or not evidence or len(operator) > 128 or len(evidence) > 2048:
            raise ValueError('host operator, evidence and explicit worker-stopped attestation required')
        resolution = dict(operator=operator, evidence=evidence, now=now, worker_stopped=True)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            job = self.inspect(run_id)
            if job['status'] == 'abandoned' and job['resolution'] == resolution:
                self.store._apply_in_transaction('finish', request_id, now, run_id)
                return job
            if job['status'] != 'running':
                raise ValueError('only an unresolved local job can be abandoned')
            self.db.execute("UPDATE local_jobs SET status='abandoned',resolution=? WHERE run_id=?",
                            (canonical(resolution), run_id))
            self.store._apply_in_transaction('finish', request_id, now, run_id)
        return self.inspect(run_id)
