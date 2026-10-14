"""Synthetic data only: real process crashes/locks and injected API recovery."""
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

from .host import BodyLoop, UnifiedBody
from .api_host import BodyAPIHost
from .continuation import authorize, grants
from .scheduler import register, schedules, tick, synthetic_runner, WindowHost
from .test_api_recovery import SimulatedAPI, ended
from examples.nasuraya_agent_loop.agents_api import run_api
from examples.nasuraya_agent_loop.local import ToolRejected
from examples.nasuraya_agent_loop.tests.test_agents_api import call, requires


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.sqlite'
        self.now = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
        with BodyLoop.start(self.path, fixture='sleep', max_actions=1) as loop:
            host = BodyAPIHost(loop, mode='bounded', target_cycles=1, max_calls=20, run_id='old')
            synthetic_runner(host, {}, 30)
            self.sha = host.snapshot()['checkpoint_sha256']
        self.addCleanup(self.temp.cleanup)

    def setup_wake(self, *, actions=1, calls=8, backend='synthetic', **changes):
        with BodyLoop(self.path) as loop:
            self.grant = authorize(loop, grant_id='grant', run_id='next', additional_actions=actions,
                additional_calls=calls, observed_checkpoint_sha256=self.sha)
            options = dict(wake_id='wake', run_id='next', due_at=self.now.isoformat(),
                expires_at=(self.now + timedelta(minutes=10)).isoformat(), model='fixture', backend=backend,
                retry_delay_seconds=1)
            options.update(changes)
            self.register_options = options
            return register(loop, **options)

    def run_tick(self, **kwargs):
        return tick(self.path, wake_id='wake', clock=lambda: self.now, **kwargs)

    def snapshot(self):
        with BodyLoop(self.path) as loop:
            host = BodyAPIHost.resume(loop, run_id='next')
            return dict(body=host.snapshot(), progress=host.evaluate(), history=loop.engine.export(),
                        grants=grants(loop.engine.db), config=deepcopy(loop.config),
                        calls=loop.engine.db.execute('SELECT count(*) FROM body_api_calls').fetchone()[0])

    def process(self, code):
        proc = subprocess.run([sys.executable, '-c', code, str(self.path), self.now.isoformat()],
                              capture_output=True, text=True)
        return proc

    def crash(self, operation):
        code = '''import os,signal,sys
from datetime import datetime
from examples.nasuraya_body_loop.scheduler import tick,synthetic_runner
from examples.nasuraya_body_loop.host import UnifiedBody
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from unittest.mock import patch
def die(*a,**k): os.kill(os.getpid(),signal.SIGKILL)
''' + operation + '''
tick(sys.argv[1],wake_id='wake',clock=lambda:datetime.fromisoformat(sys.argv[2]),runner=runner)
'''
        proc = self.process(code)
        self.assertEqual(proc.returncode, -signal.SIGKILL, proc.stderr)
        with BodyLoop(self.path) as loop:
            self.assertEqual(schedules(loop)[0]['state'], 'running')

    def test_registration_never_creates_grant_or_mutates_body_history_config(self):
        with BodyLoop(self.path) as loop:
            authorize(loop, grant_id='grant', run_id='next', additional_actions=1,
                      additional_calls=8, observed_checkpoint_sha256=self.sha)
            before = loop.engine.export(), deepcopy(loop.config), grants(loop.engine.db)
            register(loop, wake_id='wake', run_id='next', due_at=self.now.isoformat(),
                expires_at=(self.now+timedelta(minutes=10)).isoformat(), model='fixture')
            self.assertEqual(before, (loop.engine.export(), loop.config, grants(loop.engine.db)))
            self.assertNotIn('authorize', str(BodyAPIHost.resume(loop,run_id='next').definitions()))

    def test_registration_without_prior_grant_is_rejected(self):
        with BodyLoop(self.path) as loop, self.assertRaisesRegex(ValueError, 'existing explicit'):
            register(loop,wake_id='wake',run_id='unapproved',due_at=self.now.isoformat(),
                expires_at=(self.now+timedelta(minutes=1)).isoformat(),model='fixture')

    def test_contract_idempotence_and_no_extension_even_after_completion(self):
        first = self.setup_wake()
        self.run_tick()
        with BodyLoop(self.path) as loop:
            row = register(loop, **self.register_options)
            self.assertEqual(row['contract'], first['contract'])
            self.assertEqual(row['attempts'],1)
            for changes in ({'expires_at':(self.now+timedelta(days=1)).isoformat()},
                            {'max_attempts':2}, {'model':'different'}, {'wake_id':'another'},
                            {'backend':'api'}, {'run_id':'old'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    register(loop, **(self.register_options | changes))
        self.assertEqual(self.snapshot()['progress']['run_actions_remaining'],0)

    def test_invalid_time_and_limits_rejected(self):
        self.setup_wake()
        for changes in ({'due_at':'2026-10-14T00:00:00'}, {'expires_at':self.now.isoformat()},
                        {'max_attempts':True}, {'max_attempts':4}, {'timeout_seconds':float('nan')},
                        {'retry_delay_seconds':0}):
            with self.subTest(changes=changes), BodyLoop(self.path) as loop, self.assertRaises(ValueError):
                register(loop, **(self.register_options|changes))

    def test_before_due_no_runner_network_action_or_budget_consumption(self):
        self.setup_wake(due_at=(self.now+timedelta(seconds=20)).isoformat())
        before = self.snapshot()
        with patch('examples.nasuraya_body_loop.scheduler.synthetic_runner', side_effect=AssertionError('early')):
            row = self.run_tick()
        self.assertEqual(row['state'],'pending')
        self.assertEqual(row['attempts'],0)
        self.assertEqual(before,self.snapshot())

    def test_timezone_normalization_and_restart_catchup(self):
        self.setup_wake(due_at='2026-10-14T03:30:00+03:30')
        self.now += timedelta(seconds=20)
        row=self.run_tick()
        self.assertEqual(row['state'],'completed')
        self.assertEqual(self.snapshot()['body']['revision'],2)
        self.assertEqual(row['contract']['due_at_utc'],'2026-10-14T00:00:00+00:00')

    def test_expiry_exact_boundary_never_starts_or_refills(self):
        self.setup_wake()
        before=self.snapshot()
        self.now+=timedelta(minutes=10)
        row=self.run_tick(runner=lambda *a: self.fail('expired runner'))
        self.assertEqual(row['state'],'expired')
        self.assertEqual(row['attempts'],0)
        self.assertEqual(before,self.snapshot())
        self.now-=timedelta(minutes=5)
        self.assertEqual(self.run_tick()['state'],'expired')

    def test_expiry_between_tool_calls_stops_before_new_reservation(self):
        self.setup_wake()
        def execute(host, contract, timeout):
            host.handle_required('sid',call('observe_body',call_id='observe'))
            before=host.evaluate()['tool_calls_remaining']
            self.now+=timedelta(minutes=10)
            with self.assertRaises(ToolRejected):
                host.handle_required('sid',call('request_body_action',dict(action='observe',duration_s=.1,
                    observed_checkpoint_sha256=host.snapshot()['checkpoint_sha256']),call_id='act'))
            self.assertEqual(before,host.evaluate()['tool_calls_remaining'])
            return dict(status='timeout')
        self.assertEqual(self.run_tick(runner=execute)['state'],'expired')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],0)

    def test_expiry_raised_inside_runner_is_persisted_as_expired(self):
        self.setup_wake()
        def execute(host, contract, timeout):
            self.now += timedelta(minutes=10)
            host.handle_required('sid',call('observe_body'))
        self.assertEqual(self.run_tick(runner=execute)['state'],'expired')
        self.assertEqual(self.snapshot()['progress']['tool_calls_remaining'],8)

    def test_monotonic_expiry_prevents_wall_clock_extension(self):
        self.setup_wake()
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next')
            monotonic=[0]
            guarded=WindowHost(host,schedules(loop)[0]['contract'],clock=lambda:self.now,
                               monotonic=lambda:monotonic[0])
            monotonic[0]=601
            with self.assertRaises(ToolRejected):guarded.handle_required('sid',call('observe_body'))
            self.assertEqual(host.evaluate()['tool_calls_remaining'],8)

    def test_clock_rollback_across_restart_blocks_execution(self):
        self.setup_wake(due_at=(self.now+timedelta(seconds=20)).isoformat())
        self.run_tick()
        self.now-=timedelta(seconds=1)
        self.assertEqual(self.run_tick()['last_status'],'clock_rollback')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],0)

    def test_consumed_tool_budget_is_terminal_and_never_replenished(self):
        self.setup_wake(calls=4)
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next')
            for n in range(4):host.handle_required('sid',call('unknown',call_id='bad-'+str(n)))
        before=self.snapshot()
        self.assertEqual(self.run_tick()['state'],'budget_exhausted')
        self.assertEqual(before,self.snapshot())

    def test_consumed_body_budget_blocks_an_unfinished_goal(self):
        self.setup_wake()
        with BodyLoop(self.path) as loop:
            loop.observe();loop.step(decision_id='other-host-use',duration_s=.1)
        before=self.snapshot()
        self.assertEqual(self.run_tick()['state'],'budget_exhausted')
        self.assertEqual(before,self.snapshot())

    def test_modified_grant_binding_blocks_wake(self):
        self.setup_wake()
        with BodyLoop(self.path) as loop:
            grant=grants(loop.engine.db)[0];grant['additional_calls']+=1
            loop.engine.db.execute('UPDATE body_continuation_grants SET contract=?',(json.dumps(grant),))
        self.assertEqual(self.run_tick()['last_status'],'grant_binding_changed')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],0)

    def test_sigkill_after_claim_resumes_same_goal(self):
        self.setup_wake()
        self.crash('def runner(*a): die()')
        self.assertEqual(self.run_tick()['state'],'completed')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)
        self.assertEqual(self.snapshot()['grants'],[self.grant])

    def test_sigkill_after_committed_action_reconciles_existing_receipt(self):
        self.setup_wake()
        self.crash('''def runner(host,contract,timeout):
 original=BodyAPIHost._finish
 def finish(self,identity,result):
  if result.get('success') and 'decision_id' in result.get('output',''):die()
  return original(self,identity,result)
 with patch.object(BodyAPIHost,'_finish',finish):synthetic_runner(host,contract,timeout)
''')
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('replayed effect')):
            self.assertEqual(self.run_tick()['state'],'completed')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)
        self.assertEqual(self.snapshot()['progress']['tool_calls_remaining'],5)

    def test_sigkill_inside_effect_blocks_unknown_result(self):
        self.setup_wake()
        self.crash('''def runner(host,contract,timeout):
 with patch.object(UnifiedBody,'cycle',die):synthetic_runner(host,contract,timeout)
''')
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('unknown effect replay')):
            self.assertEqual(self.run_tick()['state'],'blocked')
        self.assertTrue(self.snapshot()['progress']['unresolved'])

    def test_sigkill_after_goal_before_scheduler_commit_has_zero_new_effects(self):
        self.setup_wake()
        self.crash('''def runner(host,contract,timeout):
 synthetic_runner(host,contract,timeout)
 die()
''')
        before=self.snapshot()
        row=self.run_tick(runner=lambda *a:self.fail('terminal re-execution'))
        self.assertEqual(row['state'],'completed')
        self.assertEqual(before,self.snapshot())

    def test_separate_concurrent_process_cannot_claim_held_body(self):
        self.setup_wake()
        with BodyLoop(self.path):
            proc=self.process('''import sys,json
from datetime import datetime
from examples.nasuraya_body_loop.scheduler import tick
print(json.dumps(tick(sys.argv[1],wake_id='wake',clock=lambda:datetime.fromisoformat(sys.argv[2]))))
''')
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['state'],'busy')
        self.assertEqual(self.run_tick()['state'],'completed')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)

    def test_two_scheduler_processes_share_one_claim_and_effect(self):
        self.setup_wake()
        code='''import sys,json
from datetime import datetime
from examples.nasuraya_body_loop.scheduler import tick,synthetic_runner
def runner(host,contract,timeout):
 print('CLAIMED',flush=True)
 sys.stdin.readline()
 return synthetic_runner(host,contract,timeout)
print(json.dumps(tick(sys.argv[1],wake_id='wake',clock=lambda:datetime.fromisoformat(sys.argv[2]),runner=runner)))
'''
        first=subprocess.Popen([sys.executable,'-c',code,str(self.path),self.now.isoformat()],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            # Bound readiness waiting; do not leave a failed test hung on a pipe.
            import select
            ready,_,_=select.select([first.stdout],[],[],30)
            self.assertTrue(ready,'scheduler did not claim in time')
            self.assertEqual(first.stdout.readline().strip(),'CLAIMED')
            second=self.run_tick(runner=lambda *a:self.fail('concurrent effect'))
            self.assertEqual(second['state'],'busy')
            out,err=first.communicate('\n',timeout=30)
            self.assertEqual(first.returncode,0,err)
            self.assertEqual(json.loads(out)['state'],'completed')
        finally:
            if first.poll() is None:
                first.kill();first.communicate()
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)
        self.assertEqual(self.run_tick()['attempts'],1)

    def test_finite_attempts_and_backoff_survive_restart_without_extra_calls(self):
        self.setup_wake(max_attempts=2)
        runner=lambda *a:dict(status='timeout')
        self.assertEqual(self.run_tick(runner=runner)['attempts'],1)
        self.assertFalse(self.run_tick(runner=lambda *a:self.fail('backoff'))['execution_started'])
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.run_tick(runner=runner)['attempts'],2)
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.run_tick(runner=lambda *a:self.fail('attempt cap'))['state'],'attempts_exhausted')
        self.assertEqual(self.snapshot()['progress']['tool_calls_remaining'],8)

    def test_completed_wakeup_in_fresh_process_needs_no_runner_or_network(self):
        self.setup_wake();self.run_tick()
        before=self.snapshot()
        proc=self.process('''import sys,json
from datetime import datetime
from examples.nasuraya_body_loop.scheduler import tick
def forbidden(*a):raise AssertionError('network/effect')
print(json.dumps(tick(sys.argv[1],wake_id='wake',clock=lambda:datetime.fromisoformat(sys.argv[2]),runner=forbidden)))
''')
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['state'],'completed')
        self.assertEqual(before,self.snapshot())

    def test_api_stream_resume_uses_existing_transport_and_no_duplicate_effect(self):
        self.setup_wake(actions=2, backend='api')
        active=[]
        def cycle(number):
            yield requires(call('observe_body',call_id='read-'+str(number)))
            sha=active[0].snapshot()['checkpoint_sha256']
            yield requires(call('request_body_action',dict(action='observe',duration_s=.1,
                observed_checkpoint_sha256=sha),call_id='act-'+str(number)))
        api=SimulatedAPI(lambda:cycle(1))
        def runner(host,contract,timeout):
            active[:]=[host]
            return run_api(host,api.client,model='fixture',timeout_seconds=timeout,max_reconnects=0)
        self.assertEqual(self.run_tick(runner=runner)['state'],'pending')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)
        self.now+=timedelta(seconds=1)
        def finish():
            yield from cycle(2)
            yield requires(call('evaluate_body',call_id='eval'))
            yield ended()
        api.reconnect_events=finish
        row=self.run_tick(runner=runner)
        self.assertEqual(row['state'],'completed')
        self.assertEqual(api.requests.count('create'),1)
        self.assertEqual(api.requests.count('stream'),1)
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],2)
        self.assertEqual(self.snapshot()['grants'],[self.grant])

    def test_unknown_remote_creation_after_sigkill_never_creates_again(self):
        self.setup_wake(backend='api')
        self.crash('''from examples.nasuraya_agent_loop.agents_api import run_api
from types import SimpleNamespace
def runner(host,contract,timeout):
 client=SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=SimpleNamespace(create=die))))
 run_api(host,client,model='fixture',timeout_seconds=timeout,max_reconnects=0)
''')
        self.assertEqual(self.run_tick(runner=lambda *a:self.fail('second create'))['last_status'],
                         'transport_requires_explicit_reconciliation')


if __name__=='__main__':unittest.main()
