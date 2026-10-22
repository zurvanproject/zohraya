"""Native recovery effects, return to motion and durable goals; no model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .host import BodyLoop
from .api_host import BodyAPIHost
from .recovery import recommended_action, recovery_status, recovery_step
from .continuation import authorize
from examples.nasuraya_agent_loop.tests.test_agents_api import call


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.sqlite'
        self.addCleanup(self.temp.cleanup)

    def invoke(self, host, name, args=None, identity='call'):
        return host.handle_required('test-session', call(name, args, identity, 'test-turn'))

    def test_sleep_traverses_tool_core_and_native_body(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=1) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=6)
            before = host.snapshot()['minimum_state']['sleep_pressure']
            result = recovery_step(host)
            receipt = result['receipt']
            self.assertEqual((result['proposed_action'], receipt['requested_action'], receipt['actual_action']),
                             ('sleep', 'sleep', 'sleep'))
            self.assertLess(result['recovery']['sleep_pressure'], before)
            self.assertTrue(result['evaluation']['goal_reached'])
            self.assertFalse(result['recovery']['completed'], 'cycle target is not full recovery')
            self.assertTrue(result['recovery']['pending_recovery'])
            self.assertLess(receipt['body_audit']['energy_error_J'], 1e-6)
            self.assertLess(receipt['body_audit']['water_error_L'], 1e-9)
            checkpoint = host.snapshot()['checkpoint_sha256']
            self.assertFalse(recovery_step(host)['executed'])
            self.assertEqual(host.snapshot()['checkpoint_sha256'], checkpoint)

    def test_sleep_then_cold_restart_returns_to_native_motion(self):
        with BodyLoop.start(self.path, fixture='recovery-ready', max_actions=2) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=2, max_calls=9, run_id='return')
            first = recovery_step(host)
            self.assertEqual(first['receipt']['actual_action'], 'sleep')
            self.assertEqual(first['recovery']['next_recommendation'], 'walk')
            self.assertFalse(first['recovery']['completed'])
            goal = loop.engine.db.execute("SELECT value FROM meta WHERE key='body-recovery-goal/return'").fetchone()[0]
        code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from examples.nasuraya_body_loop.recovery import recovery_step
with BodyLoop(sys.argv[1]) as loop:
 host=BodyAPIHost.resume(loop,run_id='return')
 print(json.dumps(recovery_step(host)))
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.path)],
                                check=True, capture_output=True, text=True)
        second = json.loads(result.stdout)
        self.assertEqual(second['receipt']['actual_action'], 'walk')
        self.assertTrue(second['recovery']['completed'])
        self.assertEqual(second['recovery']['actions'], ['sleep', 'walk'])
        self.assertTrue(second['evaluation']['goal_reached'])
        with BodyLoop(self.path) as loop:
            host = BodyAPIHost.resume(loop, run_id='return')
            self.assertEqual(goal, loop.engine.db.execute("SELECT value FROM meta WHERE key='body-recovery-goal/return'").fetchone()[0])
            self.assertTrue(recovery_status(host)['completed'])
            before = host.snapshot()['checkpoint_sha256']
            self.assertFalse(recovery_step(host)['executed'])
            self.assertEqual(before, host.snapshot()['checkpoint_sha256'])

    def test_rest_is_available_and_not_reported_as_sleep(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=6)
            snapshot = json.loads(self.invoke(host, 'observe_body', identity='observe')['output'])
            args = dict(action='rest', duration_s=1., observed_checkpoint_sha256=snapshot['checkpoint_sha256'])
            response = self.invoke(host, 'request_body_action', args, identity='rest')
            receipt = json.loads(response['output'])
            self.assertEqual(receipt['actual_action'], 'rest')
            self.assertGreater(host.snapshot()['minimum_state']['sleep_pressure'], snapshot['minimum_state']['sleep_pressure'])
            self.assertEqual(loop.status()['completed_cycles'], 1)

    def test_sleep_replay_never_spends_second_action(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=2) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=2, max_calls=9)
            before = json.loads(self.invoke(host, 'observe_body', identity='observe')['output'])
            args = dict(action='sleep', duration_s=1., observed_checkpoint_sha256=before['checkpoint_sha256'])
            first = self.invoke(host, 'request_body_action', args, identity='sleep')
            sha = host.snapshot()['checkpoint_sha256']
        with BodyLoop(self.path) as loop:
            host = BodyAPIHost.resume(loop)
            self.assertEqual(first, self.invoke(host, 'request_body_action', args, identity='sleep'))
            self.assertEqual(sha, host.snapshot()['checkpoint_sha256'])
            self.assertEqual(loop.status()['actions_remaining'], 1)

    def test_sleep_duration_and_stale_sha_are_rejected_before_body_effect(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=2) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=2, max_calls=9)
            snapshot = json.loads(self.invoke(host, 'observe_body', identity='observe')['output'])
            args = dict(action='sleep', duration_s=10., observed_checkpoint_sha256=snapshot['checkpoint_sha256'])
            self.assertFalse(self.invoke(host, 'request_body_action', args, identity='long')['success'])
            self.assertEqual(snapshot['checkpoint_sha256'], host.snapshot()['checkpoint_sha256'])
            args['duration_s'] = 1.
            self.assertTrue(self.invoke(host, 'request_body_action', args, identity='sleep')['success'])
            after = host.snapshot()['checkpoint_sha256']
            self.assertFalse(self.invoke(host, 'request_body_action', args, identity='stale')['success'])
            self.assertEqual(after, host.snapshot()['checkpoint_sha256'])
            self.assertEqual(loop.status()['completed_cycles'], 1)

    def test_observation_and_reopen_do_not_invent_recovery(self):
        with BodyLoop.start(self.path, fixture='sleep', mode='observe') as loop:
            host = BodyAPIHost(loop)
            before = host.snapshot()
            loop.observe(); loop.observe()
            self.assertFalse(recovery_step(host)['executed'])
            self.assertEqual(before, host.snapshot())
        with BodyLoop(self.path) as loop:
            self.assertEqual(before, BodyAPIHost.resume(loop).snapshot())

    def test_low_call_budget_cannot_start_half_a_recovery_step(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=1) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=2)
            before = host.snapshot()
            self.assertFalse(recovery_step(host)['executed'])
            self.assertEqual(before, host.snapshot())
            self.assertEqual(host.evaluate()['tool_calls_remaining'], 2)

    def test_new_recovery_mission_preserves_completed_goal_and_history(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=1) as loop:
            old = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=6, run_id='old')
            recovery_step(old)
            old_records = loop.records()
            config = dict(loop.config)
            sha = old.snapshot()['checkpoint_sha256']
            grant = authorize(loop, grant_id='new-recovery', run_id='next', additional_actions=1,
                              additional_calls=4, observed_checkpoint_sha256=sha)
            new = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=6, run_id='next')
            self.assertEqual(recovery_step(new)['receipt']['actual_action'], 'sleep')
            self.assertEqual(old_records, loop.records()[:1])
            self.assertEqual(config, loop.config)
            self.assertTrue(old.evaluate()['goal_reached'])
            self.assertEqual(grant, authorize(loop, grant_id='new-recovery', run_id='next', additional_actions=1,
                               additional_calls=4, observed_checkpoint_sha256=sha))
            self.assertEqual(loop.status()['actions_remaining'], 0)

    def test_ready_motion_has_a_new_evidence_context_but_sleepy_recall_is_retained(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=2) as loop:
            first_snapshot = loop.observe()
            self.assertEqual(loop.make_request('sleepy', first_snapshot, .1)['topic'], 'optional-motion')
            first = loop.step()
            loop.observe(); second = loop.step()
            self.assertIn(first['decision_id'], second['recalled_feedback_ids'])
        with BodyLoop.start(Path(self.temp.name)/'ready.sqlite', fixture='recovery-ready') as loop:
            loop.observe(); loop.step(preferred_action='sleep', duration_s=1.)
            snapshot = loop.observe()
            self.assertEqual(loop.make_request('ready', snapshot, .1)['topic'], 'optional-motion/ready')

    def test_recovery_policy_and_public_tool_contract(self):
        self.assertEqual(recommended_action(dict(sleep_pressure=.9, fatigue=.9)), 'sleep')
        self.assertEqual(recommended_action(dict(sleep_pressure=.65, fatigue=.6)), 'rest')
        self.assertEqual(recommended_action(dict(sleep_pressure=.65, fatigue=.45)), 'walk')
        for value in (True, -1., 1.1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                recommended_action(dict(sleep_pressure=value, fatigue=.1))
        with BodyLoop.start(self.path) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=1)
            action = next(t for t in host.definitions() if t['name']=='request_body_action')
            self.assertEqual(action['parameters']['properties']['action']['enum'], ['walk','observe','sleep','rest'])
            self.assertEqual(action['parameters']['properties']['duration_s']['maximum'], 1.)
            self.assertIn('request sleep', host.instructions)
