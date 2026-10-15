"""A real MotionJournal can be paused or advanced by the opt-in self-model."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .monitor import SelfModel,ROOT
from .evaluate import fixture,prepare_defaults
from .goal_bridge import step_goal,reconcile_goal
sys.path.insert(0,str(ROOT/'examples/nasuraya_star_motion'))
from extension_state import attach
from motion_goal import MotionGoal
from motion_journal import MotionJournal
from unified_body_v2 import UnifiedBody
from coordinated_support import CoordinatedSupport


class GoalBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.model=SelfModel.create(self.root/'model.sqlite')

    def journal(self,label):
        body=fixture(.3)
        attach(body,dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=dict(L=[],R=[]),cursor_semantics='confirmed'))
        goal=MotionGoal.start(body,'reverse',label)
        return MotionJournal.create(self.root/(label+'.sqlite'),goal)

    def test_unknown_context_pauses_without_spending_goal_budget(self):
        j=self.journal('pause');before=j.load().checkpoint()
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('unexpected action')):
            result=step_goal(self.model,j)
        self.assertFalse(result['executed']);self.assertEqual(before,j.load().checkpoint())
        self.assertEqual(self.model.verify()['episodes'],0)

    def test_verified_experience_enables_one_native_goal_tick(self):
        for i in range(3):
            j=self.journal('practice-'+str(i));g=j.load();q=g.request()
            self.model.begin(g.body,q)
            r=j.step(event_id=q['event_id'],expected_head=g.checkpoint()['sha256'])
            self.model.finish(q['event_id'],j.load().body,r)
        j=self.journal('ready');result=step_goal(self.model,j)
        self.assertTrue(result['executed']);self.assertEqual(j.load().task['elapsed'],1)
        self.assertEqual(result['self_report']['inferred']['samples'],3)

    def test_pending_learning_reconciles_a_verified_receipt_without_action(self):
        j=self.journal('reconcile');g=j.load();q=g.request();self.model.begin(g.body,q)
        j.step(event_id=q['event_id'],expected_head=g.checkpoint()['sha256']);before=j.load().checkpoint()
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('repeated action')), \
             patch.object(CoordinatedSupport,'step',side_effect=AssertionError('repeated rollout')):
            result=reconcile_goal(self.model,j)
        self.assertEqual(result['status'],'reconciled');self.assertEqual(result['native_actions_executed'],0)
        self.assertEqual(j.load().checkpoint(),before);self.assertEqual(self.model.verify()['pending'],[])

    def test_unknown_receipt_remains_pending(self):
        j=self.journal('unknown');g=j.load();self.model.begin(g.body,g.request());before=g.checkpoint()
        with self.assertRaises(ValueError):reconcile_goal(self.model,j)
        self.assertEqual(j.load().checkpoint(),before)
        self.assertEqual(len(self.model.verify()['pending']),1)


if __name__=='__main__':unittest.main()
