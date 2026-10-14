"""Evidence-based care continuity, bounded wake cycles and cold recovery."""
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from . import test_scheduler as fixtures
from .api_host import BodyAPIHost
from .care import episodes, plan, reconcile
from .host import BodyLoop, UnifiedBody
from .scheduler import schedules


class CareTests(unittest.TestCase):
    setUp = fixtures.SchedulerTests.setUp
    setup_wake = fixtures.SchedulerTests.setup_wake
    run_tick = fixtures.SchedulerTests.run_tick
    snapshot = fixtures.SchedulerTests.snapshot
    process = fixtures.SchedulerTests.process
    crash = fixtures.SchedulerTests.crash

    def prepare(self, **options):
        return self.setup_wake(actions=2, calls=8, backend='care', **options)

    def memos(self):
        with BodyLoop(self.path) as loop:
            return episodes(loop,'next')

    def test_high_sleep_policy_observes_and_clear_fixture_requests_motion(self):
        base=dict(minimum_state=dict(sleep_pressure=.8,fatigue=.2,pain=0.,hydration=.8))
        self.assertEqual(plan(base)['preferred_action'],'observe')
        self.assertIn('sleep_pressure_high',plan(base)['reasons'])
        base['minimum_state']['sleep_pressure']=.2
        self.assertEqual(plan(base)['preferred_action'],'walk')
        for value in (float('nan'),True,float('inf')):
            base['minimum_state']['pain']=value
            with self.assertRaises(ValueError):plan(base)

    def test_two_wakes_share_goal_budgets_and_prior_feedback(self):
        self.prepare()
        first=self.run_tick()
        self.assertEqual(first['state'],'pending')
        self.assertEqual(first['last_status'],'yielded')
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)
        self.assertEqual(self.snapshot()['progress']['tool_calls_remaining'],4)
        old_memo=self.memos()[0]
        self.assertEqual(old_memo['body_actual'],'observe')
        self.assertEqual(old_memo['observed_after']['revision'],2)
        self.assertTrue(old_memo['recalled_feedback_ids'])
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.run_tick()['state'],'completed')
        memories=self.memos()
        self.assertEqual(memories[0],old_memo)
        self.assertEqual(len(memories),2)
        self.assertEqual(memories[1]['observed_before']['revision'],2)
        self.assertEqual(memories[1]['observed_after']['revision'],3)
        self.assertEqual(self.snapshot()['progress']['tool_calls_remaining'],0)
        self.assertEqual(self.snapshot()['grants'],[self.grant])
        self.assertIn(old_memo['decision_id'],memories[1]['recalled_feedback_ids'])

    def test_memory_survives_fresh_process_and_terminal_replay_does_not_rewrite_it(self):
        self.prepare();self.run_tick();self.now+=timedelta(seconds=1);self.run_tick()
        before=self.memos(),self.snapshot()
        proc=self.process('''import sys,json
from examples.nasuraya_body_loop.care import episodes,reconcile
from examples.nasuraya_body_loop.host import BodyLoop,UnifiedBody
from examples.nasuraya_body_loop.api_host import BodyAPIHost
from unittest.mock import patch
with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('replay')),BodyLoop(sys.argv[1]) as loop:
 host=BodyAPIHost.resume(loop,run_id='next')
 print(json.dumps(reconcile(host)))
''')
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout),before[0])
        self.assertEqual(self.run_tick()['state'],'completed')
        self.assertEqual(before,(self.memos(),self.snapshot()))

    def test_crash_after_committed_second_effect_recovers_missing_memo_without_replay(self):
        self.prepare();self.run_tick();self.now+=timedelta(seconds=1)
        self.crash('''from examples.nasuraya_body_loop.care import runner as care_runner
def runner(host,contract,timeout):
 original=BodyAPIHost._finish
 def finish(self,identity,result):
  if result.get('success') and 'decision_id' in result.get('output',''):die()
  return original(self,identity,result)
 with patch.object(BodyAPIHost,'_finish',finish):care_runner(host,contract,timeout)
''')
        self.assertEqual(len(self.memos()),1)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('duplicate effect')):
            self.assertEqual(self.run_tick()['state'],'completed')
        self.assertEqual(len(self.memos()),2)
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],2)
        self.assertEqual(self.snapshot()['progress']['tool_calls_remaining'],1)

    def test_unknown_effect_never_becomes_a_success_memory(self):
        self.prepare()
        self.crash('''from examples.nasuraya_body_loop.care import runner as care_runner
def runner(host,contract,timeout):
 with patch.object(UnifiedBody,'cycle',die):care_runner(host,contract,timeout)
''')
        self.assertEqual(self.run_tick()['state'],'blocked')
        self.assertEqual(self.memos(),[])
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],0)

    def test_expiry_between_wakes_preserves_first_episode_and_stops_second(self):
        self.prepare();self.run_tick()
        before=self.memos(),self.snapshot()
        self.now+=timedelta(minutes=10)
        self.assertEqual(self.run_tick()['state'],'expired')
        self.assertEqual(before,(self.memos(),self.snapshot()))

    def test_care_cannot_create_more_budget_when_calls_end_after_first_cycle(self):
        self.setup_wake(actions=2,calls=4,backend='care')
        self.assertEqual(self.run_tick()['state'],'pending')
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.run_tick()['state'],'budget_exhausted')
        self.assertEqual(len(self.memos()),1)
        self.assertEqual(self.snapshot()['progress']['completed_cycles'],1)
        self.assertEqual(self.snapshot()['grants'],[self.grant])

    def test_larger_grant_still_respects_unchanged_base_host_call_cap(self):
        from .continuation import authorize
        from .scheduler import register, tick, synthetic_runner
        path=Path(self.temp.name)/'small-host.sqlite'
        with BodyLoop.start(path,fixture='sleep',max_actions=1) as loop:
            old=BodyAPIHost(loop,mode='bounded',target_cycles=1,max_calls=4,run_id='old')
            synthetic_runner(old,{},30)
            grant=authorize(loop,grant_id='limited-grant',run_id='limited',additional_actions=2,
                additional_calls=8,observed_checkpoint_sha256=old.snapshot()['checkpoint_sha256'])
            register(loop,wake_id='limited',run_id='limited',backend='care',model='fixture',
                due_at=self.now.isoformat(),expires_at=(self.now+timedelta(minutes=10)).isoformat(),
                retry_delay_seconds=1)
        self.assertEqual(tick(path,wake_id='limited',clock=lambda:self.now)['state'],'pending')
        self.now+=timedelta(seconds=1)
        self.assertEqual(tick(path,wake_id='limited',clock=lambda:self.now)['state'],'budget_exhausted')
        with BodyLoop(path) as loop:
            host=BodyAPIHost.resume(loop,run_id='limited')
            self.assertEqual(host.max_calls,4)
            self.assertEqual(host.evaluate()['completed_cycles'],1)
            self.assertEqual(len(episodes(loop,'limited')),1)

    def test_altered_derived_memory_is_blocked_before_next_action(self):
        self.prepare();self.run_tick()
        before=self.snapshot()
        with BodyLoop(self.path) as loop:
            memo=episodes(loop,'next')[0];memo['body_actual']='invented'
            loop.engine.db.execute('UPDATE body_care_episodes SET memo=?',(json.dumps(memo),))
        self.now+=timedelta(seconds=1)
        self.assertEqual(self.run_tick()['last_status'],'care_memory_source_conflict')
        self.assertEqual(before,self.snapshot())

    def test_source_deltas_and_identifiers_are_exactly_from_committed_records(self):
        self.prepare();self.run_tick()
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next')
            memo=reconcile(host)[0]
            receipt=loop.receipt(loop.engine.get(memo['decision_id']),replayed=True)
            self.assertEqual(memo['observed_after'],receipt['self_model_after'])
            for key,value in memo['delta'].items():
                self.assertEqual(value,memo['observed_after']['minimum_state'][key]-memo['observed_before']['minimum_state'][key])
            self.assertEqual(memo['recalled_feedback_ids'],receipt['recalled_feedback_ids'])
            before=host.snapshot()
            self.assertEqual(reconcile(host),[memo])
            self.assertEqual(before,host.snapshot())


if __name__=='__main__':unittest.main()
