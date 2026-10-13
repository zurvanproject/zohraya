"""Durable transport metadata, separate from BodyAPIHost's logical goal/receipts.

No raw items, arguments, prompts, keys or reasoning are persisted here. Reconnect
does not resend initial input. Historical items are evidence, never instructions
to execute tools. The body database's existing exclusive lock serializes workers.
"""
from contextlib import nullcontext
import re

from .local import ToolRejected


class RecoveryBlocked(ToolRejected):
    pass


def as_dict(value):
    return value if isinstance(value, dict) else value.to_dict()


class APIRecovery:
    def __init__(self, host, model, policy):
        if not hasattr(host, 'reconcile_receipts'):
            raise ValueError('recovery requires a durable body host')
        self.host, self.db, self.policy = host, host.loop.engine.db, policy
        self.model, self.reconnecting, self.kind = model, False, 'new_session'
        self.db.execute('''CREATE TABLE IF NOT EXISTS body_api_transport(
            run_id TEXT PRIMARY KEY, model TEXT NOT NULL, state TEXT NOT NULL,
            session_id TEXT, turn_id TEXT, terminal_status TEXT)''')
        row = self.saved
        if row and row['model'] != model:
            raise ValueError('saved API model cannot change during recovery')

    @property
    def saved(self):
        row = self.db.execute('SELECT * FROM body_api_transport WHERE run_id=?', (self.host.run_id,)).fetchone()
        return dict(row) if row else None

    def update(self, **fields):
        # Only internal fixed column names enter SQL.
        if set(fields) - {'state', 'session_id', 'turn_id', 'terminal_status'}:
            raise ValueError('invalid transport metadata')
        self.db.execute('UPDATE body_api_transport SET ' + ','.join(k+'=?' for k in fields)
                        + ' WHERE run_id=?', (*fields.values(), self.host.run_id))

    @staticmethod
    def identity(value):
        if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}', value):
            raise RecoveryBlocked('invalid saved API identity')
        return value

    def session(self, identity):
        identity = self.identity(identity)
        row = self.saved
        if row['session_id'] is not None and row['session_id'] != identity:
            raise RecoveryBlocked('saved API session mismatch')
        # Do not allow two logical goals to drive one remote session.
        other = self.db.execute('SELECT 1 FROM body_api_transport WHERE session_id=? AND run_id!=?',
                                (identity, self.host.run_id)).fetchone()
        if other:
            raise RecoveryBlocked('API session belongs to another logical goal')
        self.update(session_id=identity, state='attached')

    def turn(self, identity):
        identity = self.identity(identity)
        row = self.saved
        if row['turn_id'] is not None and row['turn_id'] != identity:
            raise RecoveryBlocked('saved API turn mismatch')
        self.update(turn_id=identity)

    def open(self, sessions, create_kwargs, remaining):
        remaining()
        local = self.host.reconcile_receipts()
        self.host.journal.emit('api_receipts_reconciled', **local)
        if local['unresolved']:
            raise RecoveryBlocked('body outcome unknown; no API input or body replay permitted')
        row = self.saved
        if row and row['session_id'] is None:
            raise RecoveryBlocked('session creation outcome unknown; resolve resource before retry')
        if row and self.policy == 'fresh':
            # A failed/missing stream alone does not establish that work stopped.
            # Require a known terminal turn or failed session, then confirmed deletion.
            if row['state'] != 'deleted':
                events = list(self.inspect(sessions, remaining))
                if not any(e['type'] in ('agent.session.failed', 'agent.session.turn.completed',
                                        'agent.session.turn.failed', 'agent.session.turn.cancelled') for e in events):
                    raise RecoveryBlocked('old API turn still active; fresh session blocked')
                sessions.delete(row['session_id'], timeout=remaining())
                self.update(state='deleted')
            self.db.execute('DELETE FROM body_api_transport WHERE run_id=?', (self.host.run_id,))
            row = None
            self.kind = 'fresh_session_saved_goal'
        if row:
            if row['terminal_status']:
                self.kind = 'saved_terminal'
                return nullcontext(())
            if row['state'] == 'deleted':
                raise RecoveryBlocked('remote session deleted; explicit fresh policy required')
            if row['state'] == 'failed':
                raise RecoveryBlocked('remote session failed; explicit fresh policy required')
            self.reconnecting, self.kind = True, 'same_session'
            return sessions.events.stream(row['session_id'], timeout=remaining())
        # Reserve before sending initial input. A crash before learning the remote
        # ID is ambiguous and must never automatically create a second session.
        remaining()
        self.db.execute('INSERT INTO body_api_transport VALUES(?,?,?,NULL,NULL,NULL)',
                        (self.host.run_id, self.model, 'creating'))
        self.host.initial_input = (
            f'Continue saved logical goal {self.host.run_id}. '
            f'Host evaluation: {self.host.evaluate()}. '
            'Completed cycles are already applied. Observe afresh and do only unfinished work.')
        create_kwargs['input'] = self.host.initial_input
        create_kwargs['timeout'] = remaining()
        return sessions.create(**create_kwargs)

    def inspect(self, sessions, remaining):
        row = self.saved
        sid = self.identity(row['session_id'])
        snapshot = as_dict(sessions.retrieve(sid, timeout=remaining()))
        if snapshot.get('id') != sid or snapshot.get('status') not in ('idle', 'in_progress', 'requires_action', 'failed'):
            raise RecoveryBlocked('invalid retrieved API session')
        # Fully drain bounded history to check that retrieval succeeded. Contents
        # are deliberately discarded; no historical tool item can execute an effect.
        count = 0
        for _ in self.history(sessions.items, sid, remaining, maximum=500, order='asc'):
            count += 1
        self.host.journal.emit('api_history_reconciled', item_count=count)
        if snapshot['status'] == 'failed':
            yield {'type': 'agent.session.failed'}
            return
        tid = row['turn_id']
        if tid is None:
            # This runner sends exactly one initial message per remote session.
            # More than one root turn is evidence of an external writer, not a guess.
            roots = []
            for raw in self.history(sessions.turns, sid, remaining, maximum=100, order='desc'):
                turn = as_dict(raw)
                if 'subagent_id' not in turn:
                    raise RecoveryBlocked('malformed recovered turn')
                if turn['subagent_id'] is None:
                    roots.append(turn)
            if len(roots) != 1:
                raise RecoveryBlocked('cannot identify original API root turn')
            tid = roots[0]['id']
            self.turn(tid)
        turn = as_dict(sessions.turns.retrieve(tid, session_id=sid, timeout=remaining()))
        if (turn.get('id') != tid or turn.get('session_id') != sid
                or 'subagent_id' not in turn or turn['subagent_id'] is not None):
            raise RecoveryBlocked('recovered API turn identity mismatch')
        if turn.get('status') in ('completed', 'failed', 'cancelled'):
            yield {'type': 'agent.session.turn.' + turn['status'], 'turn': turn}
        elif turn.get('status') in ('queued', 'in_progress', 'waiting'):
            yield {'type': 'agent.session.turn.created', 'turn': turn}
            if snapshot['status'] == 'requires_action':
                yield {'type': 'agent.session.requires_action', 'session': snapshot}
        else:
            raise RecoveryBlocked('unknown recovered API turn outcome')

    @staticmethod
    def history(resource, sid, remaining, *, maximum, order):
        """Fetch each page with the remaining deadline, avoiding SDK auto-pagination
        reusing the original (now stale) timeout on later pages.
        """
        after, count, cursors = None, 0, set()
        while True:
            kwargs = dict(order=order, limit=100, timeout=remaining())
            if after is not None: kwargs['after'] = after
            page = as_dict(resource.list(sid, **kwargs))
            data = page.get('data')
            if not isinstance(data, list) or len(data) > 100 or type(page.get('has_more')) is not bool:
                raise RecoveryBlocked('malformed API reconciliation page')
            count += len(data)
            if count > maximum:
                raise RecoveryBlocked('API history reconciliation limit exceeded')
            for item in data:
                remaining()
                yield item
            if not page['has_more']:
                return
            after = as_dict(data[-1]).get('id') if data else None
            if not isinstance(after, str) or not after or after in cursors or count >= maximum:
                raise RecoveryBlocked('API history incomplete or cursor stalled')
            cursors.add(after)

    def initial_events(self, sessions, remaining):
        row = self.saved
        if row['terminal_status']:
            return iter([{'type': 'agent.session.turn.' + row['terminal_status'],
                          'turn': {'id': row['turn_id'], 'subagent_id': None}}])
        return self.inspect(sessions, remaining) if self.reconnecting else iter(())

    def terminal(self, kind):
        self.update(state='terminal', terminal_status=kind)

    def finish(self, cleanup):
        row = self.saved
        if row and cleanup == 'deleted':
            self.update(state='deleted')
        elif row and row['session_id'] and not row['terminal_status'] and row['state'] != 'failed':
            self.update(state='disconnected')

    def can_reconnect(self):
        row = self.saved
        return bool(row and row['session_id'] and not row['terminal_status'] and row['state'] not in ('deleted', 'failed'))
