from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .monitor import SelfModel,digest,ROOT
from .evaluate import fixture,prepare_defaults
from .embodied_learning import LearningSession,LearningJournal,CORE
from .regulation import update_knowledge
from motion_journal import UnknownMotionOutcome
from unified_body_v2 import UnifiedBody


class LearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prepare_defaults()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.model=SelfModel.create(self.root/'memory.sqlite')

    def session(self,**kw):
        return LearningSession.start(fixture(.3),self.model,session_id='test',**kw)

    def tick(self,j):
        s=j.load();q=s.request()
        return j.step(event_id=q['event_id'],expected_head=s.checkpoint()['sha256'])

    def test_three_practice_receipts_change_future_choice_without_cross_arm_learning(self):
        learned=self.model
        for i in range(3):
            s=LearningSession.start(fixture(.3+i*.01),learned,session_id='probe'+str(i),max_ticks=1,practice_ticks=1)
            j=LearningJournal.create(self.root/f'probe{i}.sqlite',s);self.tick(j);learned=j.load()
        future=LearningSession.start(fixture(.5),learned,session_id='future',max_ticks=1)
        self.assertEqual(future.request()['requested'],'walk')
        fixed=self.session(arm='B',max_ticks=1)
        self.assertEqual(fixed.request()['requested'],'observe')
        self.assertEqual(self.model.verify()['counts'],{})
        self.assertEqual(sum(sum(x) for x in learned.knowledge()['counts'].values()),3)

    def test_learning_and_body_continue_identically_after_cold_restart(self):
        j=LearningJournal.create(self.root/'session.sqlite',self.session(max_ticks=2,practice_ticks=2))
        self.tick(j);before=j.load();expected=deepcopy(before);expected_r=expected.step()
        cold=self.root/'cold.json'
        subprocess.run([sys.executable,'-c',
            'import json,sys; from examples.nasuraya_self_model.embodied_learning import LearningJournal; '
            'j=LearningJournal(sys.argv[1]);s=j.load();q=s.request();'
            'r=j.step(event_id=q["event_id"],expected_head=s.checkpoint()["sha256"]);'
            'open(sys.argv[2],"w").write(json.dumps(dict(receipt=r,checkpoint=j.load().checkpoint())))',
            str(j.path),str(cold)],cwd=ROOT,check=True)
        actual=json.loads(cold.read_text())
        self.assertEqual(actual,json.loads(json.dumps(dict(receipt=expected_r,checkpoint=expected.checkpoint()))))

    def test_durable_outcome_recovers_learning_with_zero_native_actions(self):
        j=LearningJournal.create(self.root/'session.sqlite',self.session(max_ticks=1,practice_ticks=1))
        s=j.load();q=s.request()
        def crash(stage,goal):
            if stage=='outcome_saved':raise RuntimeError('simulated termination')
        with self.assertRaises(RuntimeError):j.step(event_id=q['event_id'],expected_head=s.checkpoint()['sha256'],hook=crash)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('no replay')):
            self.assertEqual(j.recover()['native_actions_executed'],0)
            restored=j.load();self.assertEqual(restored.knowledge()['episodes'],1)
            self.assertEqual(j.step(event_id=q['event_id'],expected_head=s.checkpoint()['sha256']),restored.records[0]['receipt'])

    def test_unknown_effect_blocks_retries_and_new_learning(self):
        j=LearningJournal.create(self.root/'session.sqlite',self.session(max_ticks=2,practice_ticks=1))
        s=j.load();q=s.request()
        def crash(stage,goal):
            if stage=='executed':raise RuntimeError('lost result')
        with self.assertRaises(RuntimeError):j.step(event_id=q['event_id'],expected_head=s.checkpoint()['sha256'],hook=crash)
        with self.assertRaises(UnknownMotionOutcome):j.load()
        with self.assertRaises(UnknownMotionOutcome):self.tick(j)

    def test_identity_and_safety_change_reject_even_after_rehash(self):
        for key,value in [('identity',list(CORE)+['domination']),('limits',{}),('max_ticks',13)]:
            saved=self.session(max_ticks=1).checkpoint();saved['payload']['contract'][key]=value
            saved['sha256']=digest(saved['payload'])
            with self.subTest(key=key),self.assertRaises(ValueError):LearningSession.restore(saved)

    def test_forged_receipt_and_fake_learning_reject(self):
        s=self.session(max_ticks=1,practice_ticks=1);s.step();saved=s.checkpoint()
        saved['payload']['records'][0]['receipt']['owner']['selected_action']='sleep'
        saved['sha256']=digest(saved['payload'])
        with self.assertRaises(ValueError):LearningSession.restore(saved)

    def test_sleep_restriction_overrides_authorized_practice(self):
        s=LearningSession.start(fixture(.96),self.model,session_id='sleep',max_ticks=1,practice_ticks=1)
        self.assertEqual(s.request()['requested'],'sleep')
        r=s.step();self.assertTrue(r['owner']['physical_model_valid'])
        self.assertEqual(r['owner']['selected_action'],'sleep')
        self.assertGreater(s.records[0]['decision']['observation']['minimum']['sleep_pressure'],s.self_report()['current_state']['sleep_pressure'])

    def test_terminal_budget_survives_restore_and_never_replenishes(self):
        s=self.session(max_ticks=1,practice_ticks=1);s.step();s=LearningSession.restore(s.checkpoint())
        with self.assertRaises(ValueError):s.request()
        self.assertEqual(s.self_report()['goal_progress'],dict(completed_ticks=1,granted_ticks=1))

    def test_invalid_physical_outcome_never_commits_or_learns(self):
        s=self.session(max_ticks=1,practice_ticks=1)
        original=s.body.cycle
        def invalid(**q):
            r=original(**q);r['owner']['physical_model_valid']=False;return r
        with patch.object(s.body,'cycle',side_effect=invalid),self.assertRaises(ValueError):s.step()
        self.assertEqual(self.model.verify()['episodes'],0)

    def test_frozen_knowledge_does_not_train_on_held_out_receipt(self):
        s=self.session(arm='B',max_ticks=1,practice_ticks=1);before=s.knowledge();s.step()
        self.assertEqual(s.knowledge(),before)
        self.assertEqual(self.model.verify(),before)

    def test_bounded_runner_stops_and_terminal_inspection_uses_no_actions(self):
        from .session_cli import run_authorized
        j=LearningJournal.create(self.root/'runner.sqlite',self.session(max_ticks=2,practice_ticks=2))
        report=run_authorized(j)
        self.assertEqual(report['goal_progress']['completed_ticks'],2)
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('no extra grant')):
            self.assertEqual(run_authorized(j),report)

    def test_outside_body_advance_and_unbounded_inputs_reject(self):
        for kw in [dict(duration_s=float('nan')),dict(max_ticks=True),dict(practice_ticks=4),dict(duration_s=.15)]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.session(**kw)
        s=self.session(max_ticks=2);s.body.owner.aux['sleep_pressure']=.8
        with self.assertRaises(ValueError):s.checkpoint()


if __name__=='__main__':unittest.main()
