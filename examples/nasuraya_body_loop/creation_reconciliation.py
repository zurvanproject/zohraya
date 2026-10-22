"""Explicit host review of an orphan creation reservation; never a model tool.

An empty project listing is current API evidence, not a claim about an unseen
past request. The host must attest that the previous request has finished and
that no external writer is creating sessions. No scheduler calls this function.
"""
from datetime import datetime, timezone
import json

from examples.nasuraya_agent_loop.api_recovery import RecoveryBlocked, as_dict
from .api_host import digest


def resolve_empty_project(host, sessions, *, previous_request_finished=False,
                          exclusive_project_writer=False, timeout=15):
    if previous_request_finished is not True or exclusive_project_writer is not True:
        raise RecoveryBlocked('explicit host attestations required')
    if not 1 <= timeout <= 30:
        raise ValueError('bounded read timeout required')
    db = host.loop.engine.db
    db.execute('''CREATE TABLE IF NOT EXISTS body_api_creation_reviews(
        run_id TEXT PRIMARY KEY, evidence TEXT NOT NULL)''')
    prior = db.execute('SELECT evidence FROM body_api_creation_reviews WHERE run_id=?',
                       (host.run_id,)).fetchone()
    if prior:
        return json.loads(prior[0])  # Review retries cannot clear a later transport.
    row = db.execute('SELECT * FROM body_api_transport WHERE run_id=?', (host.run_id,)).fetchone()
    if not row or row['state'] != 'creating' or any(row[k] is not None for k in
                                                  ('session_id', 'turn_id', 'terminal_status')):
        raise RecoveryBlocked('only an orphan creation reservation can be reviewed')
    if db.execute('SELECT 1 FROM body_api_run_calls WHERE run_id=?', (host.run_id,)).fetchone():
        raise RecoveryBlocked('local calls already exist; absence review forbidden')
    if host.reconcile_receipts()['unresolved']:
        raise RecoveryBlocked('body outcome unknown')
    checks = []
    for _ in range(2):
        # Omit agent_id and cursor: inspect the whole project, not a filtered view.
        page = as_dict(sessions.list(limit=100, order='desc', timeout=timeout))
        if page.get('data') != [] or page.get('has_more') is not False:
            raise RecoveryBlocked('complete empty project listing required')
        checks.append(dict(at_utc=datetime.now(timezone.utc).isoformat(),
                           data_count=0, has_more=False, sha256=digest(page)))
    evidence = dict(schema='nasuraya-creation-review/1', run_id=host.run_id,
                    resolution='host_reviewed_current_project_empty', checks=checks,
                    previous_request_finished=True, exclusive_project_writer=True,
                    historical_creation_outcome='not inferred',
                    grants_issued=0, budget_added=0, body_actions=0)
    # The durable review and removal of only the orphan reservation are atomic.
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('INSERT INTO body_api_creation_reviews VALUES(?,?)',
                   (host.run_id, json.dumps(evidence, sort_keys=True)))
        db.execute('DELETE FROM body_api_transport WHERE run_id=?', (host.run_id,))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    return evidence
