"""PR #7 + #14 integration: generated data, real process crashes, no service calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .api_host import BodyAPIHost
from .care import runner as care_runner, episodes
from .continuation import authorize, grants
from .decision_context import records
from .experience import packet
from .host import BodyLoop, UnifiedBody
from .recovery import recovery_step, recovery_status
from .scheduler import register, schedules, tick
from .test_api_recovery import SimulatedAPI, ended
from examples.nasuraya_agent_loop.agents_api import run_api
from examples.nasuraya_agent_loop.local import ToolRejected
from examples.nasuraya_agent_loop.tests.test_agents_api import call, requires


class SleepIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'body.sqlite'
        self.now = datetime(2026, 10, 14, tzinfo=timezone.utc)

    def setup(self, *, fixture='recovery-ready', actions=2, calls=8, backend='recovery'):
        with BodyLoop.start(self.path, fixture=fixture, max_actions=1) as loop:
            old = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=20, run_id='old')
            care_runner(old, {}, 30)
            self.old_records = deepcopy(loop.records())
            self.old_memory = deepcopy(episodes(loop, 'old'))
            self.old_config = deepcopy(loop.config)
            self.old_contract = loop.engine.db.execute("SELECT contract FROM body_api_runs WHERE id='old'").fetchone()[0]
            self.grant = authorize(loop, grant_id='sleep-grant', run_id='recovery',
                additional_actions=actions, additional_calls=calls,
                observed_checkpoint_sha256=old.snapshot()['checkpoint_sha256'])
            register(loop, wake_id='wake', run_id='recovery', due_at=self.now.isoformat(),
                expires_at=(self.now+timedelta(minutes=10)).isoformat(), model='fixture',
                backend=backend, retry_delay_seconds=1)

    def tick(self, **kwargs):
        return tick(self.path, wake_id='wake', clock=lambda:self.now, **kwargs)

    def snapshot(self):
        with BodyLoop(self.path) as loop:
            host = BodyAPIHost.resume(loop, run_id='recovery')
            return dict(body=host.snapshot(), history=loop.engine.export(), grants=grants(loop.engine.db),
                calls=[tuple(r) for r in loop.engine.db.execute('SELECT * FROM body_api_calls ORDER BY identity')],
                progress=host.evaluate(), intents=records(loop, 'recovery'), memory=episodes(loop, 'old'))

    def crash(self, hook):
        code = '''import os,signal,sys
from datetime import datetime
from unittest.mock import patch
from examples.nasuraya_body_loop.scheduler import tick
from examples.nasuraya_body_loop.recovery import runner as recovery_runner
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from examples.nasuraya_body_loop.host import UnifiedBody
def die(*a,**k):os.kill(os.getpid(),signal.SIGKILL)
''' + hook + '''
tick(sys.argv[1],wake_id='wake',clock=lambda:datetime.fromisoformat(sys.argv[2]),runner=runner)
'''
        result = subprocess.run([sys.executable,'-c',code,str(self.path),self.now.isoformat()],
                                capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)

    def test_scheduled_sleep_restart_walk_retains_all_prior_sources(self):
        self.setup()
        self.assertEqual(self.tick()['state'],'pending')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            self.assertEqual(recovery_status(host)['actions'],['sleep'])
            self.assertEqual(host.decision_context()['preferred_action'],'walk')
            p=packet(host)
            self.assertEqual(p['records'][-1]['preferred_action'],'sleep')
            self.assertFalse(p['replay_permission'])
        self.now += timedelta(seconds=1)
        result=subprocess.run([sys.executable,'-c', '''import json,sys
from datetime import datetime
from examples.nasuraya_body_loop.scheduler import tick
print(json.dumps(tick(sys.argv[1],wake_id='wake',clock=lambda:datetime.fromisoformat(sys.argv[2]))))
''',str(self.path),self.now.isoformat()],capture_output=True,text=True,check=True,timeout=60)
        self.assertEqual(json.loads(result.stdout)['state'],'completed')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            self.assertEqual(recovery_status(host)['actions'],['sleep','walk'])
            self.assertTrue(recovery_status(host)['completed'])
            self.assertEqual(self.old_records,loop.records()[:len(self.old_records)])
            self.assertEqual(self.old_memory,episodes(loop,'old'))
            self.assertEqual(self.old_config,loop.config)
            self.assertEqual(self.old_contract,loop.engine.db.execute("SELECT contract FROM body_api_runs WHERE id='old'").fetchone()[0])
            self.assertEqual(grants(loop.engine.db),[self.grant])
            self.assertEqual(host.evaluate()['tool_calls_remaining'],0)
            self.assertEqual(host.evaluate()['run_actions_remaining'],0)
            self.assertEqual([r['intent']['preferred_action'] for r in records(loop,'recovery')],['sleep','walk'])
        before=self.snapshot()
        self.assertFalse(self.tick(runner=lambda *a:self.fail('terminal replay'))['execution_started'])
        self.assertEqual(before,self.snapshot())

    def test_sigkill_after_sleep_commit_reconciles_without_second_sleep(self):
        self.setup()
        self.crash('''def runner(host,contract,timeout):
 original=BodyAPIHost._finish
 def finish(self,identity,result):
  if result.get('success') and 'decision_id' in result.get('output',''):die()
  return original(self,identity,result)
 with patch.object(BodyAPIHost,'_finish',finish):return recovery_runner(host,contract,timeout)
''')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            self.assertEqual(recovery_status(host)['actions'],['sleep'])
        self.assertEqual(self.tick()['state'],'completed')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            self.assertEqual(recovery_status(host)['actions'],['sleep','walk'])
            self.assertEqual(len(records(loop,'recovery')),2)

    def test_sigkill_inside_sleep_blocks_unknown_effect(self):
        self.setup()
        self.crash('''def runner(host,contract,timeout):
 with patch.object(UnifiedBody,'cycle',die):return recovery_runner(host,contract,timeout)
''')
        before=self.snapshot()
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('unknown replay')):
            self.assertEqual(self.tick()['state'],'blocked')
        self.assertEqual(before,self.snapshot())
        self.assertTrue(before['progress']['unresolved'])
        self.assertEqual(before['intents'][0]['intent']['model_preference'],'sleep')
        self.assertEqual(before['intents'][0]['outcome_state'],'unresolved')

    def test_sigkill_after_wake_claim_uses_same_grant(self):
        self.setup()
        self.crash('def runner(*args):die()')
        self.assertEqual(self.tick()['state'],'pending')
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.tick()['state'],'completed')
        self.assertEqual(self.snapshot()['grants'],[self.grant])

    def test_high_pressure_cycle_goal_is_not_full_recovery(self):
        self.setup(fixture='sleep',actions=1,calls=4)
        before=self.snapshot()['body']['minimum_state']['sleep_pressure']
        self.assertEqual(self.tick()['state'],'completed')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            r=recovery_status(host)
            self.assertEqual(r['actions'],['sleep'])
            self.assertTrue(host.evaluate()['goal_reached'])
            self.assertTrue(r['pending_recovery'])
            self.assertFalse(r['completed'])
            self.assertLess(r['sleep_pressure'],before)

    def test_three_remaining_calls_cannot_begin_partial_step(self):
        self.setup(actions=1,calls=4)
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            host.handle_required('s',call('observe_body',call_id='spent'))
            before=host.snapshot()
            self.assertEqual(host.evaluate()['tool_calls_remaining'],3)
            self.assertFalse(recovery_step(host)['executed'])
            self.assertEqual(before,host.snapshot())
            self.assertEqual(host.evaluate()['tool_calls_remaining'],3)

    def test_expired_recovery_window_never_mutates_or_refills(self):
        self.setup()
        before=self.snapshot()
        self.now+=timedelta(minutes=10)
        self.assertEqual(self.tick(runner=lambda *a:self.fail('expired'))['state'],'expired')
        self.assertEqual(before,self.snapshot())

    def test_expiry_after_observation_prevents_sleep_reservation(self):
        self.setup()
        def runner(host,contract,timeout):
            host.handle_required('s',call('observe_body',call_id='o'))
            before=host.evaluate()['tool_calls_remaining']
            self.now+=timedelta(minutes=10)
            with self.assertRaises(ToolRejected):
                host.handle_required('s',call('request_body_action',dict(action='sleep',duration_s=1.,
                    observed_checkpoint_sha256=host.snapshot()['checkpoint_sha256']),call_id='a'))
            self.assertEqual(before,host.evaluate()['tool_calls_remaining'])
            return dict(status='timeout')
        self.assertEqual(self.tick(runner=runner)['state'],'expired')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],0)

    def test_unknown_api_creation_stops_local_recovery_before_calls(self):
        from examples.nasuraya_agent_loop.api_recovery import APIRecovery
        self.setup(backend='api')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            APIRecovery(host,'fixture','resume')
            loop.engine.db.execute("INSERT INTO body_api_transport VALUES('recovery','fixture','creating',NULL,NULL,NULL)")
            before=host.snapshot(),host.evaluate()
            self.assertFalse(recovery_step(host)['executed'])
            self.assertEqual(before,(host.snapshot(),host.evaluate()))
        self.assertEqual(self.tick()['state'],'blocked')

    def test_observe_mode_never_exposes_sleep_or_rest(self):
        with BodyLoop.start(self.path,mode='observe',fixture='sleep') as loop:
            host=BodyAPIHost(loop)
            before=host.snapshot()
            result=host.handle_required('s',call('request_body_action',dict(action='sleep',duration_s=1.,
                observed_checkpoint_sha256=before['checkpoint_sha256'])))
            self.assertFalse(result['success'])
            self.assertEqual(before,host.snapshot())
            self.assertEqual(len(host.definitions()),2)

    def test_mock_api_disconnect_sleep_duplicate_then_walk_same_session(self):
        self.setup(backend='api',calls=10)
        active=[]
        saved=[]
        def cycle(n,action):
            yield requires(call('observe_body',call_id='o'+str(n)))
            yield requires(call('evaluate_body',call_id='e'+str(n)))
            c=call('request_body_action',dict(action=action,duration_s=1.,
                observed_checkpoint_sha256=active[0].snapshot()['checkpoint_sha256']),call_id='a'+str(n))
            saved[:]=[c]
            yield requires(c)
        api=SimulatedAPI(lambda:cycle(1,'sleep'))
        def runner(host,contract,timeout):
            active[:]=[host]
            return run_api(host,api.client,model='fixture',timeout_seconds=timeout,max_reconnects=0)
        self.assertEqual(self.tick(runner=runner)['state'],'pending')
        sleep_call=saved[0]
        api.remote_status,api.required='requires_action',[sleep_call]
        def finish():
            yield from cycle(2,'walk')
            yield requires(call('evaluate_body',call_id='final'))
            yield ended()
        api.reconnect_events=finish
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.tick(runner=runner)['state'],'completed')
        self.assertEqual(api.requests.count('create'),1)
        self.assertEqual(api.requests.count('stream'),1)
        duplicate=[r for r in api.sent if r['call_id']=='a1']
        self.assertEqual(len(duplicate),2)
        self.assertEqual(*duplicate)
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='recovery')
            self.assertEqual(recovery_status(host)['actions'],['sleep','walk'])
            self.assertTrue(host.evaluate()['goal_reached'])
            self.assertEqual(packet(host)['records'][-2]['preferred_action'],'sleep')
            self.assertNotIn('body_checkpoint',json.dumps(api.sent))
            self.assertEqual(episodes(loop,'old'),self.old_memory)
        before=self.snapshot()
        self.tick(runner=lambda *a:self.fail('terminal API'))
        self.assertEqual(before,self.snapshot())

    def test_rest_experience_reopens_with_rest_intent(self):
        with BodyLoop.start(self.path,max_actions=1) as loop:
            host=BodyAPIHost(loop,mode='bounded',target_cycles=1,max_calls=5)
            o=host.handle_required('s',call('observe_body',call_id='o'))
            before=json.loads(o['output'])
            r=host.handle_required('s',call('request_body_action',dict(action='rest',duration_s=1.,
                observed_checkpoint_sha256=before['checkpoint_sha256']),call_id='r'))
            self.assertTrue(r['success'])
            p=packet(host)
            self.assertEqual(p['records'][-1]['body_actual'],'rest')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop)
            self.assertEqual(packet(host),p)
            self.assertEqual(records(loop,'main')[0]['intent']['model_preference'],'rest')
