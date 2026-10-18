"""Explicit, finite authority over the existing synthetic BodyLoop only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .adapters import digest
from .body_observer import observe_native_body
from .native_snapshot import snapshot

KEY = 'nasuraya-research-authority/1'
MAX_ACTIONS = 3


class ResearchBlocked(RuntimeError):
    pass


def source_sha256():
    root = Path(__file__).resolve().parents[2]
    names = ('examples/nasuraya_research/controller.py',
             'examples/nasuraya_research/body_observer.py',
             'examples/nasuraya_research/native_snapshot.py',
             'examples/nasuraya_research/adapters.py',
             'examples/nasuraya_body_loop/host.py')
    return digest({name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                   for name in names})


class BoundedResearchController:
    """Reuse native budget, locking, DecisionCore, receipts and vetoes.

    A separate small provenance record reserves each research request before
    execution. It never resets/refills the native action budget. This pilot
    accepts only sessions whose original total budget is at most three.
    """
    def __init__(self, loop):
        from examples.nasuraya_body_loop.host import BodyLoop
        if not isinstance(loop, BodyLoop):
            raise ValueError('existing BodyLoop required')
        self.loop = loop
        self._load()

    @classmethod
    def enable(cls, loop):
        from examples.nasuraya_body_loop.host import BodyLoop
        if (not isinstance(loop, BodyLoop) or loop.config['mode'] != 'bounded' or
                not 1 <= loop.config['max_actions'] <= MAX_ACTIONS):
            raise ValueError('bounded native session with original budget 1..3 required')
        state = dict(schema=KEY, source_sha256=source_sha256(),
                     native_config=deepcopy(loop.config), enabled=True, intents={})
        envelope = dict(value=state, sha256=digest(state))
        # INSERT, never REPLACE: repeated enable cannot reset a budget or intent.
        try:
            loop.engine.db.execute('INSERT INTO meta VALUES(?,?)',
                                   (KEY, json.dumps(envelope, sort_keys=True, allow_nan=False)))
        except Exception as exc:
            raise ResearchBlocked('authority already exists or cannot be recorded') from exc
        return cls(loop)

    def _load(self):
        row = self.loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if row is None:
            raise ResearchBlocked('explicit enable required')
        envelope = json.loads(row[0]); state = envelope['value']
        if (digest(state) != envelope['sha256'] or state['schema'] != KEY or
                state['source_sha256'] != source_sha256() or
                state['native_config'] != self.loop.config or
                self.loop.config['mode'] != 'bounded' or
                not 1 <= self.loop.config['max_actions'] <= MAX_ACTIONS or
                type(state['enabled']) is not bool or not isinstance(state['intents'], dict) or
                len(state['intents']) > MAX_ACTIONS):
            raise ResearchBlocked('authority source/contract/history mismatch')
        return state

    def _save(self, state):
        envelope = dict(value=state, sha256=digest(state))
        self.loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?',
            (json.dumps(envelope, sort_keys=True, allow_nan=False), KEY))

    def pause(self):
        state = self._load(); state['enabled'] = False; self._save(state)

    def resume(self):
        state = self._load(); state['enabled'] = True; self._save(state)

    def status(self):
        state = self._load()
        return dict(authority='bounded_native_simulation', enabled=state['enabled'],
                    original_total_budget=self.loop.config['max_actions'],
                    native=self.loop.status(),
                    pending=[k for k,v in state['intents'].items() if v['result'] is None],
                    requests=len(state['intents']), model_api_calls=0)

    def _complete(self, state, request_id, record, *, replayed):
        from examples.nasuraya_body_loop.host import executed_body
        from unified_body_v2 import UnifiedBody
        intent = state['intents'][request_id]
        request = record['request']
        execution = request.get('execution', {})
        from examples.nasuraya_body_loop.host import KEY as NATIVE_KEY
        if ({k:v for k,v in request.items() if k != 'execution'} != intent['native_request'] or
                execution.get('duration_s') != intent['duration_s'] or
                execution.get('at_utc') != intent['native_request']['at_utc'] or
                execution.get('runtime_key') != NATIVE_KEY or execution.get('external') != {}):
            raise ResearchBlocked('native receipt does not match the reserved research intent')
        receipt = self.loop.receipt(record, replayed=replayed)
        actual = record.get('actual_outcome') or {}
        body = (UnifiedBody.restore(actual['body_checkpoint'])
                if 'body_checkpoint' in actual else self.loop.body())
        ran = executed_body(record)
        result = dict(request_id=request_id, research_before=intent['observation'],
                      preferred_action=intent['preferred_action'], reasons=intent['reasons'],
                      native_receipt=receipt, research_after=observe_native_body(body),
                      historical_native_cycles=int(ran),
                      this_call_native_cycles=0 if replayed else int(ran),
                      replayed=replayed, model_api_calls=0)
        intent['result'] = result
        if not ran:
            state['enabled'] = False
        self._save(state)
        return deepcopy(result)

    def step(self, request_id, *, duration_s=.1):
        from examples.nasuraya_body_loop.host import validate_duration
        validate_duration(duration_s)
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', request_id):
            raise ValueError('bounded research request ID required')
        state = self._load(); old = state['intents'].get(request_id)
        if old is not None:
            if old['duration_s'] != duration_s:
                raise ValueError('conflicting research replay')
            if old['result'] is not None:
                result = deepcopy(old['result']); result['replayed'] = True
                result['this_call_native_cycles'] = 0
                return result
            record = self.loop.engine.get(old['native_id'])
            if record is not None and record['status'] == 'complete':
                return self._complete(state, request_id, record, replayed=True)
            raise ResearchBlocked('unresolved research request; no automatic reexecution')
        if not state['enabled']:
            raise ResearchBlocked('research authority paused')
        if any(v['result'] is None for v in state['intents'].values()):
            raise ResearchBlocked('unresolved research request blocks new work')
        native = self.loop.status()
        if native['unresolved_running']:
            raise ResearchBlocked('native execution unresolved')
        if native['actions_remaining'] <= 0 or len(state['intents']) >= MAX_ACTIONS:
            raise ResearchBlocked('persistent native action budget exhausted')
        native_id = 'research-authority:' + request_id
        if self.loop.engine.get(native_id) is not None:
            raise ResearchBlocked('native ID already belongs to another request')
        body = self.loop.body()
        observed = observe_native_body(body)
        audited = snapshot(body)
        if observed['source_checkpoint_sha256'] != audited['native_sha']:
            raise ResearchBlocked('observation mismatch')
        # Reuse main's audited capability check; no new learned policy or scores.
        audit = audited['audit']
        preferred = 'walk' if audit['upper_controller_walk_guard_allows'] else 'observe'
        fresh = self.loop.observe()
        if fresh['checkpoint_sha256'] != observed['source_checkpoint_sha256']:
            raise ResearchBlocked('stale research observation')
        state['intents'][request_id] = dict(native_id=native_id, duration_s=duration_s,
            native_request=self.loop.make_request(native_id, fresh, duration_s, preferred),
            observation=observed, preferred_action=preferred,
            reasons=deepcopy(audit['walking_restrictions']), result=None)
        self._save(state)  # reservation precedes every potential effect
        self.loop.step(decision_id=native_id, duration_s=duration_s, preferred_action=preferred)
        record = self.loop.engine.get(native_id)
        if record is None or record['status'] != 'complete':
            raise ResearchBlocked('native outcome unresolved')
        return self._complete(state, request_id, record, replayed=False)

    def run(self, *, steps=1, duration_s=.1):
        if type(steps) is not int or not 1 <= steps <= MAX_ACTIONS:
            raise ValueError('finite run of 1..3 requests required')
        from examples.nasuraya_body_loop.host import validate_duration
        validate_duration(duration_s)
        state = self._load()
        if not state['enabled'] or self.status()['pending']:
            raise ResearchBlocked('paused or unresolved research authority')
        if steps > self.loop.status()['actions_remaining']:
            raise ResearchBlocked('run exceeds remaining native budget')
        if steps + len(state['intents']) > MAX_ACTIONS:
            raise ResearchBlocked('run exceeds remaining research capacity')
        results = []
        for _ in range(steps):
            current = self._load()['intents']
            index = len(current) + 1
            while 'step-' + str(index) in current:
                index += 1
            request_id = 'step-' + str(index)
            result = self.step(request_id, duration_s=duration_s)
            results.append(result)
            if not self._load()['enabled']:
                break
        return dict(results=results, status=self.status())
