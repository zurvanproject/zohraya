"""Fault-injected API transport and cold SQLite reopen; no API key or network."""
import json
import importlib.util
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .api_host import BodyAPIHost
from examples.nasuraya_agent_loop.agents_api import run_api
from examples.nasuraya_agent_loop.tests.test_agents_api import FakeStream, call, requires


def ended(sid='sess-1', tid='turn-1', status='completed'):
    return dict(type='agent.session.turn.' + status,
                turn=dict(id=tid, session_id=sid, subagent_id=None, status=status))


class SimulatedAPI:
    """One root turn per session; result acknowledgement can be lost after effect."""
    def __init__(self, events=(), *, sid='sess-1', tid='turn-1'):
        self.sid, self.tid = sid, tid
        self.creation_events, self.reconnect_events = events, ()
        self.sent, self.deleted, self.created, self.requests = [], [], [], []
        self.required, self.remote_status, self.turn_status = [], 'in_progress', 'waiting'
        self.history, self.lose_ack, self.fail_delete = [], False, False
        self.submission_keys = []
        self.events = SimpleNamespace(create=self.send, stream=self.stream)
        self.items = SimpleNamespace(list=self.items_list)
        self.turns = SimpleNamespace(retrieve=self.turn, list=self.turns_list)

    @property
    def client(self):
        return SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=self)))

    def create(self, **kwargs):
        self.requests.append('create')
        self.created.append(kwargs)
        events = self.creation_events() if callable(self.creation_events) else self.creation_events
        def generate():
            yield dict(type='agent.session.created', session=dict(id=self.sid))
            yield dict(type='agent.session.turn.created', turn=dict(id=self.tid, subagent_id=None))
            yield from events
        return FakeStream(generate())

    def stream(self, sid, **kwargs):
        self.requests.append('stream')
        assert sid == self.sid
        events = self.reconnect_events() if callable(self.reconnect_events) else self.reconnect_events
        return FakeStream(events)

    def retrieve(self, sid, **kwargs):
        self.requests.append('retrieve')
        assert sid == self.sid
        return dict(id=sid, status=self.remote_status, required_actions=self.required)

    def items_list(self, sid, **kwargs):
        self.requests.append('items')
        offset = int(kwargs.get('after', '-1')) + 1
        data = [dict(item, id=str(i)) for i, item in enumerate(self.history)][offset:offset+100]
        return dict(data=data, has_more=offset+100 < len(self.history))

    def turns_list(self, sid, **kwargs):
        self.requests.append('turns')
        return dict(data=[self.turn(self.tid, session_id=sid)], has_more=False)

    def turn(self, tid, *, session_id, **kwargs):
        self.requests.append('turn')
        assert session_id == self.sid and tid == self.tid
        return dict(id=tid, session_id=session_id, subagent_id=None, status=self.turn_status)

    def send(self, sid, *, events, **kwargs):
        self.requests.append('send')
        self.sent.extend(events)
        self.submission_keys.append(kwargs.get('extra_headers', {}).get('Idempotency-Key'))
        if self.lose_ack and events[0].get('call_id') == 'act-1':
            self.lose_ack = False
            raise ConnectionError('PRIVATE-SENTINEL')

    def delete(self, sid, **kwargs):
        self.requests.append('delete')
        if self.fail_delete:
            raise ConnectionError('PRIVATE-SENTINEL')
        self.deleted.append(sid)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'body.sqlite'
        self.loop = BodyLoop.start(self.path, fixture='sleep', max_actions=3)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: self.loop.close())
        self.host = BodyAPIHost(self.loop, mode='bounded', target_cycles=2, run_id='recovery')

    def reopen(self):
        self.loop.close()
        self.loop = BodyLoop(self.path)
        self.host = BodyAPIHost.resume(self.loop, run_id='recovery')

    def action(self, sid='sess-1', tid='turn-1', number=1):
        return call('request_body_action', dict(action='observe', duration_s=.1,
            observed_checkpoint_sha256=self.host.snapshot()['checkpoint_sha256']),
            call_id='act-' + str(number), turn_id=tid)

    def cycle(self, sid='sess-1', tid='turn-1', number=1):
        yield requires(call('observe_body', call_id='read-' + str(number), turn_id=tid), session_id=sid)
        action = self.action(sid, tid, number)
        self.last_action = action
        yield requires(action, session_id=sid)

    def run_api(self, api, **kwargs):
        return run_api(self.host, api.client, model='simulator', **kwargs)

    def partial(self):
        api = SimulatedAPI(lambda: self.cycle())
        result = self.run_api(api, max_reconnects=0)
        self.assertEqual(result['status'], 'stream_incomplete')
        self.assertEqual(api.deleted, [])
        self.assertEqual(self.host.evaluate()['completed_cycles'], 1)
        return api

    def finish_events(self, sid='sess-1', tid='turn-1'):
        yield from self.cycle(sid, tid, 2)
        yield requires(call('evaluate_body', call_id='eval', turn_id=tid), session_id=sid)
        yield ended(sid, tid)

    def test_disconnect_and_cold_reopen_reconcile_duplicate_then_only_unfinished_cycle(self):
        api = self.partial()
        old_action = self.last_action
        before = self.host.snapshot()['checkpoint_sha256']
        self.reopen()
        self.assertEqual(before, self.host.snapshot()['checkpoint_sha256'])
        api.remote_status, api.required = 'requires_action', [old_action]
        api.reconnect_events = self.finish_events
        result = self.run_api(api)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['api_recovery']['kind'], 'same_session')
        self.assertEqual(api.requests[api.requests.index('stream'):][:4], ['stream', 'retrieve', 'items', 'turn'])
        self.assertEqual(len(api.created), 1)
        self.assertEqual(self.loop.status()['completed_cycles'], 2)
        duplicates = [r for r in api.sent if r.get('call_id') == 'act-1']
        self.assertEqual(duplicates[0], duplicates[1])
        keys = [k for k, r in zip(api.submission_keys, api.sent) if r.get('call_id') == 'act-1']
        self.assertEqual(keys[0], keys[1])
        self.assertFalse(result['live_api_verified'])

    def test_lost_result_ack_auto_reconnect_resends_receipt_without_body_reexecution(self):
        api = SimulatedAPI()
        def first():
            yield from self.cycle()
        api.creation_events, api.lose_ack = first, True
        original_send = api.send
        def send(sid, **kwargs):
            if kwargs['events'][0].get('call_id') == 'act-1':
                api.remote_status, api.required = 'requires_action', [self.last_action]
            return original_send(sid, **kwargs)
        api.events.create = send
        api.reconnect_events = self.finish_events
        result = self.run_api(api)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['api_recovery']['reconnect_attempts'], 1)
        self.assertEqual(self.loop.status()['completed_cycles'], 2)
        self.assertEqual(len(api.created), 1)
        self.assertNotIn('PRIVATE-SENTINEL', json.dumps(self.host.journal.events))

    def test_missed_terminal_is_recovered_from_saved_turn_not_idle(self):
        api = self.partial()
        # The second cycle completed locally before the terminal event was lost.
        for event in self.finish_events():
            if event['type'] == 'agent.session.requires_action':
                self.host.handle_required('sess-1', event['session']['required_actions'][0])
        self.reopen()
        api.remote_status, api.turn_status = 'idle', 'completed'
        api.history = [dict(type='function_call', name='request_body_action')]
        before = self.host.snapshot()['checkpoint_sha256']
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('no replay')):
            result = self.run_api(api)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(before, self.host.snapshot()['checkpoint_sha256'])
        self.assertEqual(len(api.created), 1)

    def test_idle_and_historical_call_do_not_claim_completion_or_execute(self):
        api = self.partial()
        api.remote_status = 'idle'
        api.history = [self.last_action]
        before = self.host.snapshot()['checkpoint_sha256']
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('no history execution')):
            result = self.run_api(api, max_reconnects=0)
        self.assertEqual(result['status'], 'stream_incomplete')
        self.assertEqual(before, self.host.snapshot()['checkpoint_sha256'])
        self.assertEqual(api.deleted, [])

    def test_unknown_body_result_blocks_resume_and_fresh_before_any_remote_request(self):
        api = SimulatedAPI(lambda: self.cycle())
        with patch.object(self.loop, 'step', side_effect=OSError('PRIVATE-SENTINEL')):
            result = self.run_api(api, max_reconnects=0)
        self.assertEqual(result['status'], 'api_error')
        self.reopen()
        for policy in ('resume', 'fresh'):
            probe = SimulatedAPI()
            with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('no unknown replay')):
                result = self.run_api(probe, recovery=policy)
            self.assertEqual(result['status'], 'recovery_blocked')
            self.assertEqual(probe.requests, [])
        self.assertTrue(self.host.evaluate()['unresolved'])

    def test_committed_effect_before_receipt_save_is_reconciled_on_restart(self):
        api = SimulatedAPI(lambda: self.cycle())
        finish = self.host._finish
        def interrupted(identity, result):
            if result.get('call_id') == 'act-1':
                raise OSError('PRIVATE-SENTINEL')
            finish(identity, result)
        with patch.object(self.host, '_finish', side_effect=interrupted):
            self.assertEqual(self.run_api(api, max_reconnects=0)['status'], 'api_error')
        self.assertEqual(self.loop.status()['completed_cycles'], 1)
        self.reopen()
        api.remote_status, api.required = 'requires_action', [self.last_action]
        # Reconcile/replay first action only; don't execute the second cycle here.
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('must use committed effect')):
            result = self.run_api(api, max_reconnects=0)
        self.assertEqual(result['status'], 'stream_incomplete')
        self.assertFalse(self.host.evaluate()['unresolved'])
        self.assertEqual(self.loop.status()['completed_cycles'], 1)
        self.assertTrue(any(e['kind'] == 'api_receipts_reconciled' and e['recovered_receipts'] == 1
                            for e in self.host.journal.events))

    def test_fresh_session_after_failed_turn_preserves_goal_and_remaining_budget(self):
        api = SimulatedAPI()
        def events():
            yield from self.cycle()
            yield ended(status='failed')
        api.creation_events = events
        self.assertEqual(self.run_api(api)['status'], 'api_failed')
        self.assertEqual(api.deleted, ['sess-1'])
        self.reopen()
        fresh = SimulatedAPI(lambda: self.finish_events('sess-2', 'turn-2'), sid='sess-2', tid='turn-2')
        result = self.run_api(fresh, recovery='fresh')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['api_recovery']['kind'], 'fresh_session_saved_goal')
        self.assertEqual(self.loop.status()['completed_cycles'], 2)
        self.assertIn("'completed_cycles': 1", fresh.created[0]['input'])
        self.assertNotIn('body_checkpoint', fresh.created[0]['input'])

    def test_fresh_session_blocked_while_old_turn_active(self):
        api = self.partial()
        self.reopen()
        result = self.run_api(api, recovery='fresh')
        self.assertEqual(result['status'], 'recovery_blocked')
        self.assertEqual(len(api.created), 1)
        self.assertEqual(api.deleted, [])

    def test_failed_remote_session_can_be_replaced_only_after_confirmed_delete(self):
        api = self.partial()
        api.remote_status = 'failed'
        api.fail_delete = True
        result = self.run_api(api, recovery='fresh', max_reconnects=0)
        self.assertEqual(result['status'], 'api_error')
        self.assertEqual(len(api.created), 1)
        api.fail_delete = False
        api.sid, api.tid = 'sess-2', 'turn-2'
        # Retrieve old ID with failed status until the fresh creation request.
        def retrieve(sid, **kwargs):
            return dict(id=sid, status='failed', required_actions=[])
        api.retrieve = retrieve
        api.creation_events = lambda: self.finish_events('sess-2', 'turn-2')
        result = self.run_api(api, recovery='fresh')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(api.deleted, ['sess-1', 'sess-2'])
        self.assertEqual(self.loop.status()['completed_cycles'], 2)

    def test_no_reconnect_method_does_not_silently_resend_initial_input(self):
        api = self.partial()
        api.events.stream = None
        result = self.run_api(api)
        self.assertEqual(result['status'], 'api_error')
        self.assertEqual(len(api.created), 1)
        self.assertEqual(self.loop.status()['completed_cycles'], 1)

    def test_creation_outcome_unknown_blocks_recreation_after_restart(self):
        api = SimulatedAPI()
        def create(**kwargs):
            api.created.append(kwargs)
            raise ConnectionError('PRIVATE-SENTINEL')
        api.create = create
        self.assertEqual(self.run_api(api)['status'], 'api_error')
        self.reopen()
        for policy in ('resume', 'fresh'):
            self.assertEqual(self.run_api(api, recovery=policy)['status'], 'recovery_blocked')
        self.assertEqual(len(api.created), 1)
        self.assertEqual(self.loop.status()['completed_cycles'], 0)

    def test_changed_duplicate_payload_rejected_after_restart(self):
        api = self.partial()
        changed = {**self.last_action, 'arguments': {**self.last_action['arguments'], 'action': 'walk'}}
        api.remote_status, api.required = 'requires_action', [changed]
        self.reopen()
        self.assertEqual(self.run_api(api)['status'], 'rejected')
        self.assertEqual(self.loop.status()['completed_cycles'], 1)

    def test_bounded_reconnect_attempts_and_history_limit(self):
        api = self.partial()
        self.assertEqual(self.run_api(api, max_reconnects=1)['status'], 'stream_incomplete')
        self.assertEqual(api.requests.count('stream'), 2)
        api.history = [dict(id=str(i)) for i in range(501)]
        self.assertEqual(self.run_api(api)['status'], 'recovery_blocked')
        self.assertEqual(self.loop.status()['completed_cycles'], 1)

    def test_terminal_restart_does_not_create_session_or_repeat_tools(self):
        api = SimulatedAPI()
        def events():
            yield from self.cycle()
            yield from self.finish_events()
        api.creation_events = events
        self.assertEqual(self.run_api(api)['status'], 'completed')
        self.reopen()
        probe = SimulatedAPI()
        cached = self.run_api(probe, live_service=True)
        self.assertEqual(cached['status'], 'completed')
        self.assertFalse(cached['live_api_verified'])
        self.assertEqual(probe.created, [])
        self.assertEqual(self.loop.status()['completed_cycles'], 2)

    def test_fresh_creation_failure_does_not_report_old_deleted_id_or_retry(self):
        api = SimulatedAPI()
        def events():
            yield from self.cycle()
            yield ended(status='failed')
        api.creation_events = events
        self.assertEqual(self.run_api(api)['status'], 'api_failed')
        probe = SimulatedAPI()
        def create(**kwargs):
            probe.created.append(kwargs)
            raise ConnectionError('PRIVATE-SENTINEL')
        probe.create = create
        result = self.run_api(probe, recovery='fresh')
        self.assertEqual(result['status'], 'api_error')
        self.assertIsNone(result['session_id'])
        self.assertEqual(result['cleanup_status'], 'not_created')
        self.assertEqual(self.run_api(probe)['status'], 'recovery_blocked')
        self.assertEqual(len(probe.created), 1)

    def test_missing_saved_turn_id_recovered_only_from_unique_root(self):
        api = self.partial()
        self.loop.engine.db.execute('UPDATE body_api_transport SET turn_id=NULL')
        api.turn_status = 'failed'
        self.assertEqual(self.run_api(api)['status'], 'api_failed')
        self.assertIn('turns', api.requests)

    def test_mismatched_retrieved_turn_blocks_body_and_new_session(self):
        api = self.partial()
        api.turns.retrieve = lambda *a, **kw: dict(id='wrong', session_id='sess-1', subagent_id=None, status='completed')
        self.assertEqual(self.run_api(api)['status'], 'recovery_blocked')
        self.assertEqual(self.loop.status()['completed_cycles'], 1)

    def test_failed_session_stops_auto_reconnect(self):
        api = SimulatedAPI([dict(type='agent.session.failed')])
        self.assertEqual(self.run_api(api)['status'], 'api_error')
        self.assertNotIn('stream', api.requests)
        self.assertEqual(self.run_api(api)['status'], 'recovery_blocked')
        self.assertEqual(len(api.created), 1)

    def test_transport_recovery_in_a_new_python_process(self):
        api = self.partial()
        action = self.last_action
        self.loop.close()
        script = '''
import json, sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from examples.nasuraya_body_loop.test_api_recovery import SimulatedAPI, ended, call, requires
from examples.nasuraya_agent_loop.agents_api import run_api
p = json.load(sys.stdin)
with BodyLoop(p['path']) as loop:
    host = BodyAPIHost.resume(loop, run_id='recovery')
    api = SimulatedAPI()
    api.remote_status, api.required = 'requires_action', [p['action']]
    def events():
        yield requires(call('observe_body', call_id='cold-read'))
        yield requires(call('request_body_action', dict(action='observe', duration_s=.1,
            observed_checkpoint_sha256=host.snapshot()['checkpoint_sha256']), call_id='cold-act'))
        yield requires(call('evaluate_body', call_id='cold-eval'))
        yield ended()
    api.reconnect_events = events
    result = run_api(host, api.client, model='simulator')
    print(json.dumps(dict(result=result, created=len(api.created), count=loop.status()['completed_cycles'])))
'''
        try:
            result = subprocess.run([sys.executable, '-c', script],
                input=json.dumps(dict(path=str(self.path), action=action)),
                text=True, capture_output=True, check=True)
        finally:
            self.loop = BodyLoop(self.path)
        data = json.loads(result.stdout)
        self.assertEqual(data['result']['status'], 'completed')
        self.assertEqual((data['created'], data['count']), (0, 2))
        self.assertEqual(data['result']['api_recovery']['kind'], 'same_session')

    def test_deadline_expired_before_open_makes_no_remote_request(self):
        api = SimulatedAPI()
        ticks = iter([0, 2, 2, 2, 2, 2, 2])
        result = self.run_api(api, timeout_seconds=1, clock=lambda: next(ticks))
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(api.requests, [])

    @unittest.skipUnless(importlib.util.find_spec('openai'), 'optional SDK not installed')
    def test_sdk_http_stream_disconnect_and_reconciliation_without_network(self):
        import httpx2
        from openai import OpenAI
        api = self.partial()
        self.reopen()
        old_action = self.last_action
        requests = []
        def encode(event):
            return ('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()
        class LostStream(httpx2.SyncByteStream):
            def __iter__(self):
                yield encode(dict(type='agent.session.idle'))
                raise httpx2.ReadError('PRIVATE-SENTINEL')
        streams = 0
        def respond(request):
            nonlocal streams
            requests.append((request.method, request.url.path))
            path = request.url.path
            if request.method == 'GET' and path.endswith('/events'):
                streams += 1
                if streams == 1:
                    return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, stream=LostStream())
                def live():
                    yield requires(call('observe_body', call_id='read-2'))
                    yield requires(self.action(number=2))
                    yield requires(call('evaluate_body', call_id='eval'))
                    yield ended()
                class DynamicStream(httpx2.SyncByteStream):
                    def __iter__(self):
                        for event in live(): yield encode(event)
                return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, stream=DynamicStream())
            if request.method == 'GET' and path.endswith('/items'):
                return httpx2.Response(200, json=dict(object='list', data=[old_action], has_more=False))
            if request.method == 'GET' and '/turns/' in path:
                return httpx2.Response(200, json=dict(id='turn-1', session_id='sess-1',
                    subagent_id=None, status='waiting'))
            if request.method == 'GET' and path.endswith('/sess-1'):
                return httpx2.Response(200, json=dict(id='sess-1', status='requires_action', required_actions=[old_action]))
            if request.method == 'POST' and path.endswith('/events'):
                return httpx2.Response(202)
            if request.method == 'DELETE':
                return httpx2.Response(200, json=dict(id='sess-1', deleted=True))
            raise AssertionError('unexpected HTTP request; new session forbidden')
        transport = httpx2.Client(transport=httpx2.MockTransport(respond), trust_env=False)
        with OpenAI(api_key='offline-simulator-only', http_client=transport, max_retries=0) as client:
            result = run_api(self.host, client, model='simulator')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(streams, 2)
        self.assertEqual(self.loop.status()['completed_cycles'], 2)
        self.assertFalse(result['live_api_verified'])
        self.assertNotIn(('POST', '/v1/agents/sessions'), requests)


if __name__ == '__main__':
    unittest.main()
