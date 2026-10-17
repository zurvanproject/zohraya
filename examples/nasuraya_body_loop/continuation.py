"""Explicit host-side grants for completed synthetic missions; no auto-refill."""
from datetime import datetime, timezone
import json
import re

from reflection_cycle import canonical


def grants(db):
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_continuation_grants'").fetchone()
    if not present:
        return []
    return [json.loads(r[0]) for r in db.execute('SELECT contract FROM body_continuation_grants ORDER BY rowid')]


def action_limit(loop):
    return loop.config['max_actions'] + sum(g['additional_actions'] for g in grants(loop.engine.db))


def grant_for_run(db, run_id):
    return next((g for g in grants(db) if g['run_id'] == run_id), None)


def calls_remaining(host):
    """Legacy calls share their unchanged base cap; each grant owns its new cap."""
    db = host.loop.engine.db
    grant = grant_for_run(db, host.run_id)
    if grant:
        used = db.execute('SELECT count(*) FROM body_api_run_calls WHERE run_id=?', (host.run_id,)).fetchone()[0]
        return max(0, min(host.max_calls, grant['additional_calls']) - used)
    ids = [g['run_id'] for g in grants(db)]
    if ids:
        placeholders = ','.join('?' for _ in ids)
        used = db.execute('SELECT count(*) FROM body_api_calls c LEFT JOIN body_api_run_calls r '
                          'ON r.identity=c.identity WHERE r.run_id IS NULL OR r.run_id NOT IN ('
                          + placeholders + ')', ids).fetchone()[0]
    else:
        used = db.execute('SELECT count(*) FROM body_api_calls').fetchone()[0]
    return max(0, host.max_calls - used)


def authorize(loop, *, grant_id, run_id, additional_actions, additional_calls, observed_checkpoint_sha256):
    """Called by the trusted CLI/application host, never exposed as a model tool.

    Retries of an identical grant return its receipt even after consumption.
    Altered retries, active/unfinished goals, stale observations and unknown
    effects fail before inserting a grant. The base config and counters remain.
    """
    for value in (grant_id, run_id):
        if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', value):
            raise ValueError('bounded grant and run identifiers required')
    if type(additional_actions) is not int or not 1 <= additional_actions <= 3:
        raise ValueError('explicit grant must authorize 1..3 actions')
    if type(additional_calls) is not int or not 4 <= additional_calls <= 20:
        raise ValueError('explicit grant must authorize 4..20 calls')
    if not isinstance(observed_checkpoint_sha256, str) or not re.fullmatch('[0-9a-f]{64}', observed_checkpoint_sha256):
        raise ValueError('observed checkpoint SHA required')
    params = dict(grant_id=grant_id, run_id=run_id, additional_actions=additional_actions,
                  additional_calls=additional_calls, observed_checkpoint_sha256=observed_checkpoint_sha256)
    db = loop.engine.db
    saved = grants(db)
    for prior in saved:
        if prior['grant_id'] == grant_id:
            if any(prior[k] != v for k, v in params.items()):
                raise ValueError('conflicting continuation grant')
            return prior
        if prior['run_id'] == run_id:
            raise ValueError('run already has a continuation grant')
    status = loop.status()
    if loop.config['mode'] != 'bounded' or status['actions_remaining'] != 0:
        raise ValueError('continuation requires an exhausted bounded body budget')
    if status['failed_cycles'] or status['unresolved_running']:
        raise ValueError('failed or unresolved effects block new grants')
    if status['self_model']['checkpoint_sha256'] != observed_checkpoint_sha256:
        raise ValueError('stale continuation observation')
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'body_api_runs' not in names or 'body_api_calls' not in names:
        raise ValueError('a completed body API mission is required')
    if db.execute("SELECT 1 FROM body_api_calls WHERE status='pending'").fetchone():
        raise ValueError('unresolved tool calls block new grants')
    ids = [r[0] for r in db.execute('SELECT id FROM body_api_runs ORDER BY id')]
    if run_id in ids:
        raise ValueError('new grant requires a new logical run')
    if not ids or any(g['run_id'] not in ids for g in saved):
        raise ValueError('previous grant has no completed mission')
    from .api_host import BodyAPIHost
    for old in ids:
        if not BodyAPIHost.resume(loop, run_id=old).evaluate()['goal_reached']:
            raise ValueError('unfinished earlier goals block new grants')
    if 'body_api_transport' in names and db.execute("SELECT 1 FROM body_api_transport WHERE state!='deleted'").fetchone():
        raise ValueError('finish and delete earlier remote sessions before a new grant')
    base_calls = int(db.execute("SELECT value FROM meta WHERE key='body-api-call-limit'").fetchone()[0])
    if action_limit(loop) + additional_actions > 100 or base_calls + sum(g['additional_calls'] for g in saved) + additional_calls > 100:
        raise ValueError('bounded lifetime session limit exceeded')
    receipt = params | dict(schema='nasuraya-body-continuation-grant/1',
        authorized_at_utc=datetime.now(timezone.utc).isoformat(),
        previous_completed_cycles=status['completed_cycles'], previous_action_limit=status['max_actions'],
        previous_run_ids=ids, base_api_call_limit=base_calls)
    with loop.engine.transaction():
        db.execute('''CREATE TABLE IF NOT EXISTS body_continuation_grants(
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, contract TEXT NOT NULL)''')
        db.execute('INSERT INTO body_continuation_grants VALUES(?,?,?)', (grant_id, run_id, canonical(receipt)))
    return receipt
