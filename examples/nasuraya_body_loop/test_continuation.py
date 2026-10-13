"""Continuation budgets, goal isolation and fresh-process replay regressions."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .api_host import BodyAPIHost
from .continuation import authorize, grants
from examples.nasuraya_agent_loop.agents_api import run_api
from examples.nasuraya_agent_loop.local import ToolRejected
from examples.nasuraya_agent_loop.tests.test_agents_api import call


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.sqlite'
        self.loop = BodyLoop.start(self.path, fixture='sleep', max_actions=1)
        self.old = BodyAPIHost(self.loop, mode='bounded', target_cycles=1, max_calls=4, run_id='old')
        self.invoke(self.old, 'observe_body', 'old-observe')
        self.invoke(self.old, 'evaluate_body', 'old-evaluate')
        self.first = self.invoke(self.old, 'request_body_action', 'old-action', dict(
            action='walk', duration_s=.1, observed_checkpoint_sha256=self.old.snapshot()['checkpoint_sha256']))
        self.invoke(self.old, 'evaluate_body', 'old-finish')
        self.sha = self.old.snapshot()['checkpoint_sha256']
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: self.loop.close())

    def invoke(self, host, name, identity, args=None):
        return host.handle_required('session-' + host.run_id, call(name, args, identity, 'turn-' + host.run_id))

    def authorize(self, **kwargs):
        return authorize(self.loop, **(dict(grant_id='grant-1', run_id='next', additional_actions=1,
            additional_calls=4, observed_checkpoint_sha256=self.sha) | kwargs))

    def next_host(self, run_id='next', target_cycles=1):
        return BodyAPIHost(self.loop, mode='bounded', target_cycles=target_cycles, max_calls=4, run_id=run_id)

    def finish(self, host):
        snapshot = json.loads(self.invoke(host, 'observe_body', 'observe')['output'])
        self.invoke(host, 'evaluate_body', 'evaluate')
        result = self.invoke(host, 'request_body_action', 'action', dict(action='observe', duration_s=.1,
                            observed_checkpoint_sha256=snapshot['checkpoint_sha256']))
        self.invoke(host, 'evaluate_body', 'finish')
        return result

    def test_grant_preserves_original_budget_body_history_and_goal(self):
        before = deepcopy(self.loop.engine.export())
        config = deepcopy(self.loop.config)
        receipt = self.authorize()
        self.assertEqual(before, self.loop.engine.export())
        self.assertEqual(config, self.loop.config)
        self.assertEqual(receipt['previous_completed_cycles'], 1)
        self.assertEqual(self.loop.status()['actions_remaining'], 1)
        self.assertTrue(self.old.evaluate()['goal_reached'])
        self.assertEqual(self.old.evaluate()['run_actions_remaining'], 0)

    def test_identical_grant_survives_reopen_and_never_refills_consumed_budget(self):
        receipt = self.authorize()
        self.assertEqual(receipt, self.authorize())
        self.finish(self.next_host())
        self.loop.close(); self.loop = BodyLoop(self.path)
        self.assertEqual(receipt, self.authorize())
        self.assertEqual(len(grants(self.loop.engine.db)), 1)
        self.assertEqual(self.loop.status()['actions_remaining'], 0)
        self.assertEqual(BodyAPIHost.resume(self.loop,run_id='next').evaluate()['tool_calls_remaining'], 0)

    def test_changed_grant_parameters_and_duplicate_run_are_rejected(self):
        self.authorize()
        for kwargs in ({'additional_actions':2}, {'additional_calls':5},
                       {'observed_checkpoint_sha256':'0'*64}, {'run_id':'other'},
                       {'grant_id':'second-grant'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.authorize(**kwargs)
        self.assertEqual(len(grants(self.loop.engine.db)), 1)
        self.assertEqual(self.loop.status()['actions_remaining'], 1)

    def test_stale_or_invalid_grants_do_not_create_any_budget(self):
        for kwargs in ({'additional_actions':True},{'additional_actions':0},{'additional_actions':4},
                       {'additional_calls':True},{'additional_calls':3},{'additional_calls':21},
                       {'grant_id':'invalid/path'},{'observed_checkpoint_sha256':'0'*64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.authorize(**kwargs)
        self.assertEqual(grants(self.loop.engine.db), [])
        self.assertEqual(self.loop.status()['actions_remaining'], 0)

    def test_unfinished_goal_blocks_authorization_even_with_exhausted_body(self):
        self.loop.engine.db.execute("UPDATE body_api_runs SET evaluated=0 WHERE id='old'")
        self.old.evaluated = False
        with self.assertRaisesRegex(ValueError,'unfinished'): self.authorize()
        self.assertEqual(grants(self.loop.engine.db), [])

    def test_unknown_tool_outcome_blocks_authorization(self):
        self.loop.engine.db.execute("UPDATE body_api_calls SET status='pending' WHERE tool='request_body_action'")
        with self.assertRaisesRegex(ValueError,'unresolved'): self.authorize()
        self.assertEqual(grants(self.loop.engine.db), [])

    def test_active_remote_session_blocks_authorization(self):
        self.loop.engine.db.execute('CREATE TABLE body_api_transport(run_id TEXT PRIMARY KEY, state TEXT)')
        self.loop.engine.db.execute("INSERT INTO body_api_transport VALUES('old','disconnected')")
        with self.assertRaisesRegex(ValueError,'remote sessions'): self.authorize()

    def test_new_mission_must_match_its_grant_and_cannot_borrow_another(self):
        self.authorize()
        with self.assertRaisesRegex(ValueError,'own continuation grant'): self.next_host(run_id='unapproved')
        with self.assertRaisesRegex(ValueError,'match'): self.next_host(target_cycles=0)
        with self.assertRaisesRegex(ValueError,'match'): self.next_host(target_cycles=2)
        self.assertEqual(self.next_host().max_actions, 1)

    def test_new_tool_budget_is_usable_when_old_budget_is_exhausted(self):
        self.assertEqual(self.old.evaluate()['tool_calls_remaining'],0)
        self.authorize()
        host = self.next_host()
        with self.assertRaisesRegex(ToolRejected,'budget exhausted'):
            self.invoke(self.old,'observe_body','steal-new-calls')
        self.assertEqual(host.evaluate()['tool_calls_remaining'],4)
        result = self.finish(host)
        self.assertTrue(result['success'])
        self.assertTrue(host.evaluate()['goal_reached'])
        self.assertEqual(self.loop.engine.db.execute('SELECT count(*) FROM body_api_calls').fetchone()[0],8)
        with self.assertRaisesRegex(ToolRejected,'budget exhausted'):
            self.invoke(host,'observe_body','extra')

    def test_inherited_veto_feedback_is_recalled_in_the_new_mission(self):
        self.authorize()
        result = self.finish(self.next_host())
        receipt = json.loads(result['output'])
        record = self.loop.engine.get(receipt['decision_id'])
        first = json.loads(self.first['output'])
        self.assertIn(first['decision_id'],record['recalled_feedback_ids'])
        self.assertEqual(receipt['actual_action'],'observe')

    def test_long_model_duration_is_rejected_without_spending_the_new_action(self):
        self.authorize(); host = self.next_host()
        observation = json.loads(self.invoke(host,'observe_body','observe')['output'])
        self.invoke(host,'evaluate_body','evaluate')
        before = host.snapshot()
        result = self.invoke(host,'request_body_action','too-long',dict(action='observe',duration_s=10.,
                    observed_checkpoint_sha256=observation['checkpoint_sha256']))
        self.assertFalse(result['success'])
        self.assertEqual(before,host.snapshot())
        self.assertEqual(host.evaluate()['run_actions_remaining'],1)

    def test_completed_call_replay_after_reopen_keeps_effect_and_call_counts(self):
        self.authorize(); host = self.next_host()
        snapshot = json.loads(self.invoke(host,'observe_body','observe')['output'])
        self.invoke(host,'evaluate_body','evaluate')
        args=dict(action='observe',duration_s=.1,observed_checkpoint_sha256=snapshot['checkpoint_sha256'])
        first=self.invoke(host,'request_body_action','action',args)
        self.invoke(host,'evaluate_body','finish')
        self.loop.close(); self.loop=BodyLoop(self.path)
        host=BodyAPIHost.resume(self.loop,run_id='next')
        before=host.snapshot()
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('no effect replay')):
            self.assertEqual(first,self.invoke(host,'request_body_action','action',args))
        self.assertEqual(before,host.snapshot())
        self.assertEqual(host.evaluate()['tool_calls_remaining'],0)

    def test_second_explicit_grant_requires_first_completed_and_keeps_both(self):
        self.authorize()
        with self.assertRaisesRegex(ValueError,'exhausted'): self.authorize(grant_id='grant-2',run_id='third')
        self.finish(self.next_host())
        sha=self.loop.status()['self_model']['checkpoint_sha256']
        self.authorize(grant_id='grant-2',run_id='third',observed_checkpoint_sha256=sha)
        self.assertEqual(len(grants(self.loop.engine.db)),2)
        self.assertTrue(BodyAPIHost.resume(self.loop,run_id='next').evaluate()['goal_reached'])
        self.assertTrue(self.finish(self.next_host(run_id='third'))['success'])
        self.assertEqual(self.loop.status()['completed_cycles'],3)

    def test_fresh_process_reads_completed_granted_goal_with_no_network(self):
        self.authorize(); self.finish(self.next_host())
        # Transport's committed terminal marker is the real runner's replay gate.
        self.loop.engine.db.execute('''CREATE TABLE body_api_transport(
            run_id TEXT PRIMARY KEY,model TEXT,state TEXT,session_id TEXT,turn_id TEXT,terminal_status TEXT)''')
        self.loop.engine.db.execute("INSERT INTO body_api_transport VALUES('next','test-model','deleted','sess-next','turn-next','completed')")
        self.loop.close()
        code='''import json,sys
from types import SimpleNamespace
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from examples.nasuraya_agent_loop.agents_api import run_api
def forbidden(*a,**k):raise AssertionError('network call')
client=SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=SimpleNamespace(
 create=forbidden,delete=forbidden,retrieve=forbidden,events=SimpleNamespace(stream=forbidden,create=forbidden)))))
with BodyLoop(sys.argv[1]) as loop:
 host=BodyAPIHost.resume(loop,run_id='next');before=host.snapshot()
 result=run_api(host,client,model='test-model')
 assert host.snapshot()==before and result['actions_this_process']==0
 print(json.dumps({'status':result['status'],'evaluation':host.evaluate()}))
'''
        proc=subprocess.run([sys.executable,'-c',code,str(self.path)],text=True,capture_output=True)
        self.loop=BodyLoop(self.path)
        self.assertEqual(proc.returncode,0,proc.stderr)
        result=json.loads(proc.stdout)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['evaluation']['goal_reached'])


if __name__=='__main__':unittest.main()
