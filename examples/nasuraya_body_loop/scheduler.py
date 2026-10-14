"""Host-only one-shot wakeups. Existing grants, goals, receipts and locks own effects."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
import time

from reflection_cycle import canonical
from examples.nasuraya_agent_loop.local import ToolRejected
from .api_host import BodyAPIHost
from .continuation import grant_for_run
from .host import BodyLoop

TERMINAL = {'completed', 'expired', 'budget_exhausted', 'blocked', 'attempts_exhausted'}


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('ISO timestamp with timezone required')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('explicit timezone required')
    return parsed.astimezone(timezone.utc)


def checked_now(clock):
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('aware host clock required')
    return value.astimezone(timezone.utc)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


def schedules(loop):
    db = loop.engine.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='body_wakeups' AND type='table'").fetchone():
        return []
    return [dict(row) | {'contract': json.loads(row['contract'])}
            for row in db.execute('SELECT * FROM body_wakeups ORDER BY id')]


def register(loop, *, wake_id, run_id, due_at, expires_at, model, backend='synthetic',
             max_attempts=3, timeout_seconds=60, retry_delay_seconds=30):
    """Bind an existing explicit grant to a finite host window; never authorize().

    One schedule per run, immutable and idempotent even after consumption. This
    local operation is not a model tool and trusts the same OS host as PR #6.
    """
    if not isinstance(wake_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', wake_id):
        raise ValueError('bounded wake identifier required')
    due, expiry = timestamp(due_at), timestamp(expires_at)
    if due >= expiry:
        raise ValueError('due time must precede expiry')
    if backend not in ('synthetic', 'api'):
        raise ValueError('explicit synthetic or api backend required')
    if not isinstance(model, str) or not re.fullmatch('[A-Za-z0-9_.-]{1,100}', model):
        raise ValueError('bounded fixed model required')
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError('1..3 finite wake attempts required')
    for value, low, high in ((timeout_seconds, 1, 300), (retry_delay_seconds, 1, 3600)):
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('bounded timeout and retry delay required')
    db = loop.engine.db
    grant = grant_for_run(db, run_id)
    if grant is None:
        raise ValueError('existing explicit continuation grant required')
    contract = dict(schema='nasuraya-scheduled-wakeup/1', wake_id=wake_id, run_id=run_id,
                    grant_id=grant['grant_id'], grant_sha256=fingerprint(grant),
                    due_at_utc=due.isoformat(), expires_at_utc=expiry.isoformat(), model=model,
                    backend=backend, max_attempts=max_attempts, timeout_seconds=timeout_seconds,
                    retry_delay_seconds=retry_delay_seconds)
    for row in schedules(loop):
        if row['id'] == wake_id:
            if row['contract'] != contract:
                raise ValueError('scheduled contract cannot change or extend')
            return row
        if row['run_id'] == run_id:
            raise ValueError('run already has its one-shot wakeup')
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'body_api_transport' in names:
        transport = db.execute('SELECT model FROM body_api_transport WHERE run_id=?', (run_id,)).fetchone()
        if transport and (backend != 'api' or transport[0] != model):
            raise ValueError('saved transport backend/model must be preserved')
    # PR #6 owns the run contract and caps. Registration creates only this goal,
    # not a body action, transport session or additional grant.
    BodyAPIHost(loop, mode='bounded', target_cycles=grant['additional_actions'],
                max_calls=grant['base_api_call_limit'], run_id=run_id)
    with loop.engine.transaction():
        db.execute('''CREATE TABLE IF NOT EXISTS body_wakeups(
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, contract TEXT NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL, last_checked_at TEXT, last_status TEXT)''')
        db.execute('INSERT INTO body_wakeups(id,run_id,contract,state,next_attempt_at) VALUES(?,?,?,?,?)',
                   (wake_id, run_id, canonical(contract), 'pending', due.isoformat()))
    return next(r for r in schedules(loop) if r['id'] == wake_id)


class WindowHost:
    """Adds only an expiry gate; delegates receipts, reservation and recovery."""
    def __init__(self, host, contract, *, clock=utcnow, monotonic=time.monotonic):
        self._host, self.contract, self.clock, self.monotonic = host, contract, clock, monotonic
        now = checked_now(clock)
        self.last_now = now
        self.deadline = monotonic() + (timestamp(contract['expires_at_utc']) - now).total_seconds()

    def __getattr__(self, name):
        return getattr(self._host, name)

    def handle_required(self, session_id, action):
        now = checked_now(self.clock)
        if now < self.last_now:
            raise ToolRejected('host clock moved backwards')
        self.last_now = now
        if (now < timestamp(self.contract['due_at_utc'])
                or now >= timestamp(self.contract['expires_at_utc'])
                or self.monotonic() >= self.deadline):
            raise ToolRejected('scheduled authorization window closed')
        return self._host.handle_required(session_id, action)


def synthetic_runner(host, contract, timeout_seconds):
    """Deterministic generated-fixture actions, no model or network. IDs survive restart."""
    def invoke(name, identity, arguments=None):
        result = host.handle_required('wake-' + host.run_id, dict(type='function_call', name=name,
            arguments=arguments or {}, call_id=identity, turn_id='wake-turn'))
        if not result['success']:
            raise ToolRejected('synthetic fixture tool rejected')
        return json.loads(result['output'])
    while not host.evaluate()['goal_reached']:
        index = host.run_progress()['completed_cycles']
        observed = invoke('observe_body', 'observe-' + str(index))
        invoke('evaluate_body', 'evaluate-' + str(index))
        invoke('request_body_action', 'action-' + str(index), dict(action='observe', duration_s=.1,
               observed_checkpoint_sha256=observed['checkpoint_sha256']))
        invoke('evaluate_body', 'finish-' + str(index))
    return dict(status='completed', live_api_verified=False, backend='synthetic')


def api_runner(host, contract, timeout_seconds):
    from examples.nasuraya_agent_loop.agents_api import make_client, run_api
    with make_client() as client:
        return run_api(host, client, model=contract['model'], max_calls=host.max_calls,
                       timeout_seconds=timeout_seconds, recovery='resume', max_reconnects=0,
                       live_service=True)


def tick(path, *, wake_id, clock=utcnow, runner=None):
    """Acquire the existing inode lock across claim, recovery and execution.

    A running row after a crash is retried under that lock with the SAME goal and
    transport, within the original window/attempt cap. Unknown effects stop here.
    No lease can expire while a different process still holds the body lock.
    """
    try:
        loop = BodyLoop(path)
    except BlockingIOError:
        return dict(state='busy', wake_id=wake_id, execution_started=False)
    with loop:
        row = next((r for r in schedules(loop) if r['id'] == wake_id), None)
        if row is None:
            raise ValueError('saved wakeup required')
        if row['state'] in TERMINAL:
            return row | {'execution_started': False}
        contract = row['contract']
        now = checked_now(clock)
        def save(state, status, *, attempted=False):
            from datetime import timedelta
            next_at = (now + timedelta(seconds=contract['retry_delay_seconds'])).isoformat()
            loop.engine.db.execute('UPDATE body_wakeups SET state=?,last_status=?,last_checked_at=?, '
                'next_attempt_at=? WHERE id=?', (state, status, now.isoformat(), next_at, wake_id))
            return next(r for r in schedules(loop) if r['id'] == wake_id) | {'execution_started': attempted}
        if row['last_checked_at'] and now < timestamp(row['last_checked_at']):
            return save('blocked', 'clock_rollback')
        grant = grant_for_run(loop.engine.db, contract['run_id'])
        if grant is None or fingerprint(grant) != contract['grant_sha256']:
            return save('blocked', 'grant_binding_changed')
        host = BodyAPIHost.resume(loop, run_id=contract['run_id'])
        host.reconcile_receipts()  # Existing recovery; no new effect or API request.
        evaluation = host.evaluate()
        names = {r[0] for r in loop.engine.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        transport = (loop.engine.db.execute('SELECT * FROM body_api_transport WHERE run_id=?',
                     (host.run_id,)).fetchone() if 'body_api_transport' in names else None)
        if evaluation['goal_reached'] and (not transport or
                (transport['state'] == 'deleted' and transport['terminal_status'] == 'completed')):
            return save('completed', 'saved_goal_complete')
        if now >= timestamp(contract['expires_at_utc']):
            return save('expired', 'window_closed')
        pending = loop.engine.db.execute("SELECT 1 FROM body_api_calls WHERE status='pending'").fetchone()
        if not evaluation['safe'] or pending or loop.status()['failed_cycles']:
            return save('blocked', 'unresolved_or_failed_effect')
        if transport and (transport['session_id'] is None or transport['state'] in ('failed', 'deleted')):
            return save('blocked', 'transport_requires_explicit_reconciliation')
        if (evaluation['tool_calls_remaining'] == 0 or
                (evaluation['run_actions_remaining'] == 0 and
                 evaluation['completed_cycles'] < host.target_cycles)):
            return save('budget_exhausted', 'persistent_budget_empty')
        if row['attempts'] >= contract['max_attempts']:
            return save('attempts_exhausted', 'finite_attempt_cap')
        if now < timestamp(contract['due_at_utc']) or (row['state'] != 'running' and
                now < timestamp(row['next_attempt_at'])):
            # Record clock evidence without changing the due/retry instant.
            loop.engine.db.execute('UPDATE body_wakeups SET last_checked_at=? WHERE id=?', (now.isoformat(), wake_id))
            return row | {'execution_started': False}
        remaining = (timestamp(contract['expires_at_utc']) - now).total_seconds()
        if remaining < 1:  # Existing API runner requires >= 1 second.
            return save('expired', 'insufficient_window')
        with loop.engine.transaction():
            loop.engine.db.execute("UPDATE body_wakeups SET state='running',attempts=attempts+1,"
                "last_checked_at=?,last_status='claimed' WHERE id=?", (now.isoformat(), wake_id))
        guarded = WindowHost(host, contract, clock=clock)
        execute = runner or (api_runner if contract['backend'] == 'api' else synthetic_runner)
        try:
            result = execute(guarded, contract, min(contract['timeout_seconds'], remaining))
        except Exception as exc:
            # Keep exception messages/keys/payloads out of persisted state.
            after = checked_now(clock)
            if after < now or after < guarded.last_now:
                return save('blocked', 'clock_rollback', attempted=True)
            now = after
            if now >= timestamp(contract['expires_at_utc']) or guarded.monotonic() >= guarded.deadline:
                return save('expired', 'window_closed', attempted=True)
            return save('blocked', 'runner_exception_' + type(exc).__name__, attempted=True)
        after = checked_now(clock)
        if after < now or after < guarded.last_now:
            return save('blocked', 'clock_rollback', attempted=True)
        now = after
        evaluation = host.evaluate()
        status = result.get('status', 'invalid_runner_result')
        if status == 'completed' and evaluation['goal_reached']:
            return save('completed', 'completed', attempted=True)
        if now >= timestamp(contract['expires_at_utc']) or guarded.monotonic() >= guarded.deadline:
            return save('expired', 'window_closed', attempted=True)
        if status in ('stream_incomplete', 'timeout', 'api_error'):
            return save('pending', status, attempted=True)
        return save('blocked', status, attempted=True)
