"""Independent host/transport regressions using generated fixtures only."""
from copy import deepcopy
from types import SimpleNamespace
import json
import importlib.util
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .api_host import BodyAPIHost
from examples.nasuraya_agent_loop.agents_api import PendingCalls, run_api
from examples.nasuraya_agent_loop.local import ToolRejected
from examples.nasuraya_agent_loop.tests.test_agents_api import FakeSessions, call, requires, terminal


class BodyAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.sqlite'
        self.loop = BodyLoop.start(self.path, fixture='sleep', max_actions=3)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.loop.close)

    def host(self, **kwargs):
        return BodyAPIHost(self.loop, **kwargs)

    def invoke(self, host, name, args=None, identity='read', session='sess-1', turn='turn-1'):
        return host.handle_required(session, call(name, args, identity, turn))

    def observation(self, host, **kwargs):
        return json.loads(self.invoke(host, 'observe_body', **kwargs)['output'])

    def action_args(self, host, action='walk', **kwargs):
        return dict(action=action, duration_s=.1,
                    observed_checkpoint_sha256=self.observation(host, **kwargs)['checkpoint_sha256'])

    def test_read_only_tools_keep_body_revision_and_hide_private_payload(self):
        host = self.host()
        before = self.loop.body().checkpoint()['sha256']
        observation = self.observation(host)
        evaluated = json.loads(self.invoke(host, 'evaluate_body', identity='evaluate')['output'])
        self.assertEqual({t['name'] for t in host.definitions()}, {'observe_body', 'evaluate_body'})
        self.assertTrue(evaluated['goal_reached'])
        self.assertEqual(before, self.loop.body().checkpoint()['sha256'])
        self.assertNotIn('self_location', observation)
        self.assertNotIn('payload', observation)
        self.assertNotIn('body_memory', json.dumps(observation))
        self.assertFalse(self.invoke(host, 'request_body_action', {}, identity='forbidden')['success'])
        self.assertEqual(self.loop.status()['actions_reserved'], 0)

    def test_model_preference_passes_core_and_native_veto(self):
        host = self.host(mode='bounded', target_cycles=2)
        result = self.invoke(host, 'request_body_action', self.action_args(host), identity='action')
        receipt = json.loads(result['output'])
        self.assertEqual((receipt['model_preference'], receipt['requested_action'], receipt['actual_action']),
                         ('walk', 'walk', 'protect'))
        self.assertFalse(receipt['expected_outcome_matched'])
        args = self.action_args(host, identity='next-read')
        receipt = json.loads(self.invoke(host, 'request_body_action', args, identity='next-action')['output'])
        self.assertEqual((receipt['model_preference'], receipt['requested_action'], receipt['actual_action']),
                         ('walk', 'observe', 'observe'))
        self.assertEqual(self.loop.status()['completed_cycles'], 2)

    def test_explicit_observe_preference_and_conflicting_body_replay(self):
        host = self.host(mode='bounded', target_cycles=1)
        receipt = json.loads(self.invoke(host, 'request_body_action', self.action_args(host, 'observe'), identity='action')['output'])
        self.assertEqual((receipt['model_preference'], receipt['requested_action'], receipt['actual_action']),
                         ('observe', 'observe', 'observe'))
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            self.loop.step(decision_id=receipt['decision_id'], preferred_action='walk')

    def test_bad_parameters_never_spend_body_budget_or_leak_argument_text(self):
        host = self.host(mode='bounded', target_cycles=1)
        before = self.loop.body().checkpoint()['sha256']
        variants = [dict(action='shell', duration_s=.1, observed_checkpoint_sha256='0'*64),
                    dict(action='walk', duration_s=.15, observed_checkpoint_sha256='0'*64),
                    dict(action='walk', duration_s=.1, observed_checkpoint_sha256='PRIVATE-SENTINEL'),
                    dict(command='PRIVATE-SENTINEL')]
        for i, args in enumerate(variants):
            self.assertFalse(self.invoke(host, 'request_body_action', args, identity='bad-'+str(i))['success'])
        rows = [dict(row) for row in self.loop.engine.db.execute('SELECT * FROM body_api_calls')]
        self.assertNotIn('PRIVATE-SENTINEL', json.dumps(rows))
        self.assertEqual(self.loop.status()['actions_reserved'], 0)
        self.assertEqual(before, self.loop.body().checkpoint()['sha256'])

    def test_observation_cannot_be_borrowed_from_another_session_or_turn(self):
        host = self.host(mode='bounded', target_cycles=1)
        args = self.action_args(host)
        for session, turn in [('sess-2', 'turn-1'), ('sess-1', 'turn-2')]:
            self.assertFalse(self.invoke(host, 'request_body_action', args, identity='action', session=session, turn=turn)['success'])
        self.assertEqual(self.loop.status()['actions_reserved'], 0)

    def test_second_action_needs_fresh_observation_and_run_budget_is_enforced(self):
        host = self.host(mode='bounded', target_cycles=1)
        args = self.action_args(host)
        self.assertTrue(self.invoke(host, 'request_body_action', args, identity='first')['success'])
        args = self.action_args(host, identity='next-read')
        self.assertFalse(self.invoke(host, 'request_body_action', args, identity='over-budget')['success'])
        self.assertEqual(self.loop.status()['actions_reserved'], 1)

    def test_repeated_call_survives_reopen_and_changed_payload_is_rejected(self):
        host = self.host(mode='bounded', target_cycles=1)
        args = self.action_args(host)
        first = self.invoke(host, 'request_body_action', args, identity='action')
        before = self.loop.body().checkpoint()['sha256']
        self.loop.close(); self.loop = BodyLoop(self.path)
        self.addCleanup(self.loop.close)
        host = self.host(mode='bounded', target_cycles=1)
        self.assertEqual(first, self.invoke(host, 'request_body_action', args, identity='action'))
        with self.assertRaisesRegex(ToolRejected, 'different body payload'):
            self.invoke(host, 'request_body_action', {**args, 'action': 'observe'}, identity='action')
        self.assertEqual(before, self.loop.body().checkpoint()['sha256'])
        self.assertEqual(self.loop.status()['actions_reserved'], 1)

    def test_commit_before_result_save_recovers_completed_body_without_reexecution(self):
        host = self.host(mode='bounded', target_cycles=1)
        args = self.action_args(host)
        with patch.object(host, '_finish', side_effect=OSError('PRIVATE-SENTINEL')):
            with self.assertRaises(OSError): self.invoke(host, 'request_body_action', args, identity='action')
        before = self.loop.body().checkpoint()['sha256']
        self.loop.close(); self.loop = BodyLoop(self.path); self.addCleanup(self.loop.close)
        host = self.host(mode='bounded', target_cycles=1)
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('must not run')):
            recovered = self.invoke(host, 'request_body_action', args, identity='action')
        self.assertTrue(recovered['success'])
        self.assertEqual(before, self.loop.body().checkpoint()['sha256'])
        self.assertEqual(self.loop.status()['completed_cycles'], 1)

    def test_unresolved_reserved_call_blocks_new_mutation(self):
        host = self.host(mode='bounded', target_cycles=1)
        args = self.action_args(host)
        with patch.object(self.loop, 'step', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.invoke(host, 'request_body_action', args, identity='interrupted')
        with self.assertRaisesRegex(ToolRejected, 'unresolved'):
            self.invoke(host, 'request_body_action', args, identity='interrupted')
        self.assertFalse(self.invoke(host, 'request_body_action', args, identity='new')['success'])
        self.assertEqual(self.loop.status()['completed_cycles'], 0)
        self.assertTrue(host.evaluate()['unresolved'])

    def test_persistent_tool_budget_cannot_be_reset_on_reopen(self):
        host = self.host(max_calls=2)
        self.observation(host)
        self.invoke(host, 'evaluate_body', identity='evaluate')
        self.loop.close(); self.loop = BodyLoop(self.path); self.addCleanup(self.loop.close)
        host = self.host(max_calls=2)
        with self.assertRaisesRegex(ToolRejected, 'budget exhausted'):
            self.invoke(host, 'observe_body', identity='new-read')
        with self.assertRaisesRegex(ValueError, 'cannot be changed'): self.host(max_calls=3)

    def test_api_transport_uses_body_definitions_and_only_reduced_outputs(self):
        host = self.host(mode='bounded', target_cycles=1)
        snapshot = host.snapshot()
        args = dict(action='walk', duration_s=.1, observed_checkpoint_sha256=snapshot['checkpoint_sha256'])
        sessions = FakeSessions([requires(call('observe_body', call_id='read')),
                                 requires(call('request_body_action', args, call_id='act')),
                                 requires(call('request_body_action', args, call_id='act')),
                                 requires(call('evaluate_body', call_id='eval')), terminal()])
        client = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=sessions)))
        result = run_api(host, client, model='controlled-test-model')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['actions_used'], 1)
        self.assertFalse(result['live_api_verified'])
        names = {t['name'] for t in sessions.created[0]['agent']['tools']}
        self.assertEqual(names, {'observe_body', 'evaluate_body', 'request_body_action'})
        self.assertNotIn('pending jobs', sessions.created[0]['input'])
        self.assertNotIn('body_checkpoint', json.dumps(sessions.sent))
        self.assertNotIn('body_memory', json.dumps(sessions.sent))
        self.assertEqual(sessions.deleted, ['sess-1'])

    def test_wrong_session_and_turn_rejected_before_body_effect(self):
        host = self.host(mode='bounded', target_cycles=1)
        sessions = FakeSessions([requires(call('observe_body'), session_id='wrong')])
        client = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=sessions)))
        result = run_api(host, client, model='controlled-test-model')
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(self.loop.status()['actions_reserved'], 0)

    def test_completed_goal_and_run_budget_survive_reopen(self):
        host = self.host(mode='bounded', target_cycles=1)
        self.invoke(host, 'request_body_action', self.action_args(host, 'observe'), identity='act')
        self.invoke(host, 'evaluate_body', identity='eval')
        before = self.loop.body().checkpoint()['sha256']
        self.assertTrue(host.evaluate()['goal_reached'])
        self.loop.close(); self.loop = BodyLoop(self.path); self.addCleanup(self.loop.close)
        host = self.host(mode='bounded', target_cycles=1)
        self.assertTrue(host.evaluate()['goal_reached'])
        self.assertEqual(host.evaluate()['completed_cycles'], 1)
        self.assertEqual(host.evaluate()['run_actions_remaining'], 0)
        args = self.action_args(host, 'observe', identity='after-reopen-read')
        self.assertFalse(self.invoke(host, 'request_body_action', args, identity='duplicate-plan')['success'])
        self.assertEqual(self.loop.status()['completed_cycles'], 1)
        self.assertEqual(before, self.loop.body().checkpoint()['sha256'])

    def test_partial_goal_resumes_only_remaining_cycle(self):
        host = self.host(mode='bounded', target_cycles=2)
        self.invoke(host, 'request_body_action', self.action_args(host, 'observe'), identity='act')
        self.invoke(host, 'evaluate_body', identity='eval')
        self.loop.close(); self.loop = BodyLoop(self.path); self.addCleanup(self.loop.close)
        host = self.host(mode='bounded', target_cycles=2)
        self.assertFalse(host.evaluate()['goal_reached'])
        self.assertEqual(host.evaluate()['completed_cycles'], 1)
        self.assertEqual(host.max_actions, 1)
        args = self.action_args(host, 'observe', identity='second-read')
        self.assertTrue(self.invoke(host, 'request_body_action', args, identity='second-act')['success'])
        self.assertTrue(host.evaluate()['goal_reached'])
        self.assertEqual(host.max_actions, 0)
        self.assertEqual(self.loop.status()['actions_remaining'], 1)

    def test_goal_change_requires_explicit_new_run_and_old_goal_is_retained(self):
        self.host(mode='bounded', target_cycles=1, run_id='first')
        contract = self.loop.engine.db.execute("SELECT contract FROM body_api_runs WHERE id='first'").fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'goal cannot change'):
            self.host(mode='bounded', target_cycles=2, run_id='first')
        with self.assertRaisesRegex(ValueError, 'goal cannot change'):
            self.host(mode='observe', target_cycles=0, run_id='first')
        self.assertEqual(contract, self.loop.engine.db.execute("SELECT contract FROM body_api_runs WHERE id='first'").fetchone()[0])
        self.host(mode='bounded', target_cycles=2, run_id='second')
        self.assertEqual(self.loop.engine.db.execute('SELECT count(*) FROM body_api_runs').fetchone()[0], 2)

    def test_unrelated_local_cycle_cannot_fulfill_agent_goal(self):
        host = self.host(mode='bounded', target_cycles=1)
        self.loop.observe(); self.loop.step(decision_id='unrelated-local', preferred_action='observe')
        self.observation(host)
        self.invoke(host, 'evaluate_body', identity='eval')
        self.assertEqual(self.loop.status()['completed_cycles'], 1)
        self.assertEqual(host.evaluate()['completed_cycles'], 0)
        self.assertFalse(host.evaluate()['goal_reached'])
        args = self.action_args(host, 'observe', identity='own-read')
        self.assertTrue(self.invoke(host, 'request_body_action', args, identity='own-act')['success'])
        self.assertTrue(host.evaluate()['goal_reached'])
        self.assertEqual(host.evaluate()['completed_cycles'], 1)
        self.assertEqual(self.loop.status()['completed_cycles'], 2)

    def test_call_receipt_cannot_be_reassigned_to_another_goal(self):
        first = self.host(run_id='first')
        previous = self.observation(first)
        second = self.host(mode='bounded', target_cycles=1, run_id='second')
        with self.assertRaisesRegex(ToolRejected, 'another saved run'):
            self.observation(second)
        self.assertFalse(second.evaluate()['goal_reached'])
        args = dict(action='observe', duration_s=.1, observed_checkpoint_sha256=previous['checkpoint_sha256'])
        self.assertFalse(self.invoke(second, 'request_body_action', args, identity='borrowed-observation')['success'])
        self.assertEqual(self.loop.status()['actions_reserved'], 0)

    def test_unassociated_historical_receipt_replays_without_adopting_old_progress(self):
        host = self.host(mode='bounded', target_cycles=1)
        args = self.action_args(host, 'observe')
        old = self.invoke(host, 'request_body_action', args, identity='act')
        before = self.loop.body().checkpoint()['sha256']
        # Earlier releases stored call receipts but no run ownership/goal tables.
        self.loop.engine.db.execute('DELETE FROM body_api_run_calls')
        self.loop.engine.db.execute('DELETE FROM body_api_runs')
        resumed = self.host(mode='bounded', target_cycles=1)
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('must not replay body')):
            self.assertEqual(old, self.invoke(resumed, 'request_body_action', args, identity='act'))
        self.assertEqual(resumed.evaluate()['completed_cycles'], 0)
        self.assertFalse(resumed.evaluate()['goal_reached'])
        self.assertEqual(before, self.loop.body().checkpoint()['sha256'])

    def test_fresh_process_recovers_goal_without_sdk_or_api_calls(self):
        host = self.host(mode='bounded', target_cycles=1, run_id='cold-test')
        self.invoke(host, 'request_body_action', self.action_args(host, 'observe'), identity='act')
        self.invoke(host, 'evaluate_body', identity='eval')
        before = self.loop.body().checkpoint()['sha256']
        self.loop.close()
        code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.api_host import BodyAPIHost
with BodyLoop(sys.argv[1]) as loop:
 host=BodyAPIHost.resume(loop,run_id='cold-test')
 print(json.dumps(dict(evaluation=host.evaluate(),sha=loop.body().checkpoint()['sha256'])))
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], capture_output=True, text=True, check=True)
        recovered = json.loads(result.stdout)
        self.assertTrue(recovered['evaluation']['goal_reached'])
        self.assertEqual(recovered['evaluation']['completed_cycles'], 1)
        self.assertEqual(recovered['evaluation']['run_actions_remaining'], 0)
        self.assertEqual(recovered['sha'], before)

    @unittest.skipUnless(importlib.util.find_spec('openai') and importlib.util.find_spec('httpx2'), 'optional SDK not installed')
    def test_installed_sdk_serializes_actual_body_tools_and_durable_results(self):
        import httpx2
        from openai import OpenAI
        host = self.host(mode='bounded', target_cycles=1)
        args = dict(action='observe', duration_s=.1, observed_checkpoint_sha256=host.snapshot()['checkpoint_sha256'])
        events = [dict(type='agent.session.created', session=dict(id='sess-1')),
                  requires(call('observe_body', call_id='read')),
                  requires(call('request_body_action', args, call_id='act')),
                  requires(call('request_body_action', args, call_id='act')),
                  requires(call('evaluate_body', call_id='eval')), terminal()]
        stream = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()
        captured = []
        def respond(request):
            data = json.loads(request.content) if request.content else None
            captured.append((request.method, request.url.path, data))
            if request.method == 'POST' and request.url.path == '/v1/agents/sessions':
                return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=stream)
            if request.method == 'POST' and request.url.path.endswith('/events'):
                return httpx2.Response(202)
            if request.method == 'DELETE':
                return httpx2.Response(200, json={'id': 'sess-1', 'deleted': True})
            raise AssertionError('unexpected transport request')
        transport = httpx2.Client(transport=httpx2.MockTransport(respond), trust_env=False)
        with OpenAI(api_key='controlled-body-transport-only', http_client=transport, max_retries=0) as client:
            result = run_api(host, client, model='controlled-test-model')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['actions_used'], 1)
        self.assertFalse(result['live_api_verified'])
        self.assertEqual({t['name'] for t in captured[0][2]['agent']['tools']},
                         {'observe_body', 'evaluate_body', 'request_body_action'})
        outputs = [row[2]['events'][0] for row in captured if row[0] == 'POST' and row[1].endswith('/events')]
        self.assertEqual(len(outputs), 4)
        self.assertEqual(outputs[1], outputs[2])
        self.assertNotIn('body_checkpoint', json.dumps(outputs))


if __name__ == '__main__': unittest.main()
