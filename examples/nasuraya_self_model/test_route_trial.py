from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .energy import EnergyCalibration,features
from .planning import PlanningGoal,empty_learning,state
from .route_trial import RouteTrial,TrialJournal,selection
from . import test_planning as fixtures
from .test_regulation import knowledge
from .evaluate import prepare_defaults
from .monitor import digest
from motion_journal import UnknownMotionOutcome
from unified_body_v2 import UnifiedBody


def frozen_model():
    model=EnergyCalibration();model.begin_validation();model.freeze();return model


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def goal(self,mode='calibrated',pressure=.3):
        helper=fixtures.PlanningTests();helper.setUp()
        try:goal=helper.goal(pressure).goal
        finally:helper.doCleanups()
        return RouteTrial.start(goal,mode,frozen_model(),knowledge())

    def test_old_policy_matches_existing_planner_native_receipts(self):
        a=self.goal('old');b=PlanningGoal.start(deepcopy(a.goal),knowledge(),session_id='trial-control')
        for _ in range(3):
            self.assertEqual(a.request(),b.request());self.assertEqual(a.step(),b.step())
        self.assertEqual(a.goal.checkpoint(),b.goal.checkpoint())

    def test_restored_calibrated_policy_matches_next_action_and_body(self):
        a=self.goal();a.step();b=RouteTrial.restore(json.loads(json.dumps(a.checkpoint())))
        self.assertEqual(a.request(),b.request());self.assertEqual(a.step(),b.step())
        self.assertEqual(a.checkpoint(),b.checkpoint())

    def test_new_selection_changes_cost_without_bypassing_guards(self):
        b=dict(fuel_J=1000.,minimum=dict(posture='double_support',sleep_pressure=.3,fatigue=.1,pain=.1))
        def c(action,eta):return dict(strategy=action,valid=True,horizon_s=1,eta_s=eta,fuel_debit_J=100.,
            series=[dict(requested=action,fuel_J=900.,minimum=deepcopy(b['minimum']))])
        candidates=dict(walk=c('walk',5.),observe=c('observe',5.01),rest=c('rest',8.))
        m=EnergyCalibration();f=features(b,candidates['walk']['series'][0],0)
        for i in range(3):m.add(str(i),dict(features=f,raw_J=100.,actual_J=140.))
        m.begin_validation()
        for i in range(2):m.add('v'+str(i),dict(features=f,raw_J=100.,actual_J=140.))
        m.freeze();spent=dict(observe=0,recovery=0);learning=empty_learning()
        self.assertEqual(selection('old','route',b,candidates,learning,spent,m)[0],'walk')
        self.assertEqual(selection('calibrated','route',b,candidates,learning,spent,m)[0],'observe')
        self.assertEqual(selection('calibrated','route',b,candidates,learning,dict(observe=3,recovery=0),m)[0],'walk')
        b['minimum']['fatigue']=.6
        self.assertEqual(selection('calibrated','route',b,candidates,learning,spent,m)[0],'rest')

    def test_saved_policy_or_feedback_mutation_rejected(self):
        a=self.goal();a.step();saved=a.checkpoint()
        for field in ('mode','feedback'):
            bad=deepcopy(saved)
            if field=='mode':bad['payload']['session']['mode']='invalid'
            else:bad['payload']['session']['records'][0]['feedback']['fuel_error_J']+=1.
            bad['sha256']=digest(bad['payload'])
            with self.assertRaises(ValueError):RouteTrial.restore(bad)

    def test_durable_result_recovers_without_execution_or_projection(self):
        a=self.goal();j=TrialJournal.create(self.root/'journal.sqlite',a);head=a.checkpoint()['sha256'];event=a.goal.request()['event_id']
        def crash(stage,goal):
            if stage=='outcome_saved':raise RuntimeError('injected crash')
        with self.assertRaises(RuntimeError):j.step(event_id=event,expected_head=head,hook=crash,current_goal=a)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('duplicate execution')), \
             patch('examples.nasuraya_self_model.planning.rollout',side_effect=AssertionError('projection on recovery')):
            self.assertEqual(j.recover()['native_actions_executed'],0)
        self.assertEqual(j.load().task['elapsed'],7)

    def test_unknown_result_blocks_retry(self):
        a=self.goal();j=TrialJournal.create(self.root/'unknown.sqlite',a);head=a.checkpoint()['sha256'];event=a.goal.request()['event_id']
        def crash(stage,goal):
            if stage=='executed':raise RuntimeError('lost receipt')
        with self.assertRaises(RuntimeError):j.step(event_id=event,expected_head=head,hook=crash,current_goal=a)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('retry')):
            with self.assertRaises(UnknownMotionOutcome):j.recover()
            with self.assertRaises(UnknownMotionOutcome):j.step(event_id=event,expected_head=head,current_goal=a)


if __name__=='__main__':unittest.main()
