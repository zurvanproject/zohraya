"""Saved mission intent, cold continuation and no promotion of unknown outcomes."""
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from . import test_scheduler as fixtures
from .api_host import BodyAPIHost
from .host import BodyLoop,UnifiedBody
from .decision_context import records
from .experience import packet
from .scheduler import tick
from .memory_ablation import propose


class DecisionTests(unittest.TestCase):
    setUp=fixtures.SchedulerTests.setUp
    setup_wake=fixtures.SchedulerTests.setup_wake
    run_tick=fixtures.SchedulerTests.run_tick
    crash=fixtures.SchedulerTests.crash
    process=fixtures.SchedulerTests.process
    snapshot=fixtures.SchedulerTests.snapshot

    def test_unfinished_goal_and_reason_survive_reopen_after_one_cycle(self):
        self.setup_wake(actions=2,calls=8,backend='care')
        self.run_tick()
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next');c=host.decision_context()
            self.assertEqual(c['completed_cycles'],1)
            self.assertEqual(c['cycles_remaining'],1)
            self.assertEqual(c['reason_code'],'sleep_pressure_high')
            self.assertEqual(c['preferred_action'],'observe')
            self.assertEqual(c,packet(host)['next_decision'])
            saved=records(loop,'next')[0]
            self.assertEqual(saved['intent']['cycles_remaining'],2)
            self.assertEqual(saved['intent']['completed_cycles'],0)
            self.assertEqual(saved['outcome_state'],'complete')
            self.assertEqual(saved['body_actual'],'observe')
            self.assertEqual(saved['outcome_reason_codes'],['requested_preference_executed'])

    def test_cold_context_reads_neither_grant_nor_effect_budget(self):
        self.setup_wake()
        before=self.snapshot()
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next')
            with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('effect')):
                context=host.decision_context()
            self.assertEqual(context['cycles_remaining'],1)
        self.assertEqual(before,self.snapshot())

    def test_unknown_effect_is_unresolved_and_context_stops(self):
        self.setup_wake(backend='care')
        self.crash('''from examples.nasuraya_body_loop.care import runner as care_runner
def runner(host,contract,timeout):
 with patch.object(UnifiedBody,'cycle',die):care_runner(host,contract,timeout)
''')
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next')
            self.assertEqual(host.decision_context()['next_step'],'stop')
            self.assertEqual(host.decision_context()['reason_code'],'unresolved_or_failed_effect')
            self.assertEqual(records(loop,'next')[0]['outcome_state'],'unresolved')
            self.assertIsNone(records(loop,'next')[0]['body_actual'])

    def test_completed_goal_has_no_next_action(self):
        self.setup_wake(backend='care');self.run_tick()
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next');c=host.decision_context()
            self.assertEqual(c['cycles_remaining'],0)
            self.assertEqual(c['next_step'],'stop')
            self.assertEqual(c['reason_code'],'saved_goal_complete')

    def test_explicitly_failed_effect_never_has_complete_intent(self):
        self.setup_wake(backend='care')
        with patch.object(UnifiedBody,'cycle',side_effect=RuntimeError('declared synthetic failure')):
            self.run_tick()
        with BodyLoop(self.path) as loop:
            self.assertNotEqual(records(loop,'next')[0]['outcome_state'],'complete')
            self.assertIsNone(records(loop,'next')[0]['body_actual'])

    def test_proposer_ablation_is_declared_and_fixed_rule_can_mask_memory(self):
        s=dict(minimum_state=dict(sleep_pressure=.8,fatigue=.2))
        p=dict(records=[dict(preferred_action='walk',expected_outcome_matched=False)])
        self.assertEqual(propose(s,p,input_experience=False,fixed_rules=False)[0],'walk')
        self.assertEqual(propose(s,p,input_experience=True,fixed_rules=False)[0],'observe')
        self.assertEqual(propose(s,p,input_experience=False,fixed_rules=True)[0],'observe')
        self.assertEqual(propose(s,p,input_experience=True,fixed_rules=True)[0],'observe')

    def test_terminal_call_replay_keeps_single_saved_intent(self):
        self.setup_wake(backend='care');self.run_tick()
        with BodyLoop(self.path) as loop:
            before=records(loop,'next')
        self.run_tick()
        with BodyLoop(self.path) as loop:
            self.assertEqual(before,records(loop,'next'))
            self.assertEqual(len(before),1)

    def test_unknown_api_creation_also_stops_next_decision(self):
        from examples.nasuraya_agent_loop.api_recovery import APIRecovery
        self.setup_wake()
        with BodyLoop(self.path) as loop:
            host=BodyAPIHost.resume(loop,run_id='next')
            APIRecovery(host,'fixture','resume')
            loop.engine.db.execute("INSERT INTO body_api_transport VALUES('next','fixture','creating',NULL,NULL,NULL)")
            context=host.decision_context()
            self.assertEqual(context['next_step'],'stop')
            self.assertEqual(context['reason_code'],'api_creation_outcome_unknown')
            self.assertFalse(context['safe'])
            self.assertFalse(context['goal_reached'])


if __name__=='__main__':unittest.main()
