"""Public deterministic crash contracts; no private checkpoint or live API."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

NATIVE=Path(os.environ.get('NASURAYA_NATIVE_ROOT',str(Path(__file__).resolve().parents[2]/'runtimes/tadash_body'))).resolve()
sys.path.insert(0,str(NATIVE))
from synthetic_fixture import prepare_defaults, synthetic_body
from extension_state import attach
from motion_goal import MotionGoal
from motion_journal import MotionJournal, UnknownMotionOutcome
from persistent_embodiment_v1 import digest


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()
        body=synthetic_body()
        attach(body,dict(star_enabled=False,star_started=dict(L=0,R=0),
                        star_targets=dict(L=[],R=[]),cursor_semantics='confirmed'))
        cls.origin=MotionGoal.start(body,'reverse','synthetic-recovery').checkpoint()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.goal=MotionGoal.restore(deepcopy(self.origin))
        self.store=MotionJournal.create(self.root/'motion.sqlite',self.goal)
        self.head=self.origin['sha256']
        self.event=self.goal.request()['event_id']

    def crash(self,fault):
        marker=self.root/'marker.json'
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('recovery_fault_worker.py')),
            '--native-root',str(NATIVE),'--journal',str(self.store.path),
            '--marker',str(marker),'--fault',fault],capture_output=True,text=True,timeout=180)
        self.assertEqual(result.returncode,86,result.stderr)
        return json.loads(marker.read_text())

    def blocked_without_another_cycle(self):
        before=self.store.inspect()
        self.assertEqual(before['head'],self.head)
        self.assertEqual(before['receipts'],0)
        self.assertEqual(before['pending'],self.goal.request())
        with self.assertRaises(UnknownMotionOutcome):self.store.load()
        with self.assertRaises(UnknownMotionOutcome):
            self.store.step(event_id=self.event,expected_head=self.head)
        self.assertEqual(self.store.inspect(),before)

    def test_committed_retry_does_not_charge_or_move(self):
        expected=self.goal.step()
        first=self.store.step(event_id=self.event,expected_head=self.head)
        self.assertEqual(expected,first)
        state=self.store.load().checkpoint()
        self.assertEqual(state,self.goal.checkpoint())
        self.assertEqual(self.store.step(event_id=self.event,expected_head=self.head),first)
        self.assertEqual(self.store.load().checkpoint(),state)
        self.assertEqual(self.store.inspect()['receipts'],1)
        self.assertIsNone(self.store.inspect()['pending'])

    def test_stale_writer_and_conflicting_retry_reject(self):
        self.store.step(event_id=self.event,expected_head=self.head)
        before=self.store.inspect()
        next_id=self.store.load().request()['event_id']
        for event,head in ((next_id,self.head),(self.event,'0'*64)):
            with self.assertRaises(ValueError):self.store.step(event_id=event,expected_head=head)
        self.assertEqual(self.store.inspect(),before)

    def test_existing_destination_never_overwritten(self):
        with self.assertRaises(FileExistsError):MotionJournal.create(self.store.path,self.goal)
        self.assertEqual(self.store.load().checkpoint(),self.origin)

    def test_crash_after_intent_before_action_blocks(self):
        self.assertEqual(self.crash('prepared')['substeps'],0)
        self.blocked_without_another_cycle()

    def test_crash_in_actual_native_substep_blocks(self):
        marker=self.crash('mid_native')
        self.assertEqual(marker['substeps'],3)
        self.blocked_without_another_cycle()

    def test_crash_after_body_before_goal_bookkeeping_blocks(self):
        self.crash('after_body')
        self.blocked_without_another_cycle()

    def test_crash_after_goal_before_commit_blocks(self):
        marker=self.crash('executed')
        self.assertEqual(marker['task_elapsed'],self.goal.task['elapsed']+1)
        self.blocked_without_another_cycle()

    def test_crash_inside_commit_rolls_back_goal_and_keeps_intent(self):
        self.crash('writing')
        with sqlite3.connect(self.store.path) as db:
            saved=json.loads(db.execute('SELECT goal FROM state').fetchone()[0])
        self.assertEqual(saved,self.origin)
        self.recovered_without_native_action()

    def recovered_without_native_action(self):
        from unified_body_v2 import UnifiedBody
        from coordinated_support import CoordinatedSupport
        expected=self.goal.step()
        # Recovery must reuse a receipt; a native cycle or model rollout fails
        # this test even if its final checkpoint would coincidentally match.
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native replay during recovery')), \
             patch.object(CoordinatedSupport,'step',side_effect=AssertionError('model rollout during recovery')):
            result=self.store.recover()
            self.assertEqual(result['status'],'recovered')
            self.assertEqual(result['native_actions_executed'],0)
            self.assertEqual(result['receipt_sha256'],digest(expected))
            self.assertEqual(self.store.load().checkpoint(),self.goal.checkpoint())
            self.assertEqual(self.store.step(event_id=self.event,expected_head=self.head),expected)
            self.assertEqual(self.store.recover(),dict(status='clean'))
        self.assertEqual(self.store.inspect()['receipts'],1)
        self.assertFalse(self.store.inspect()['durable_outcome'])
        self.assertIsNone(self.store.inspect()['pending'])

    def test_crash_after_durable_outcome_recovers_without_native_replay(self):
        self.crash('outcome_saved')
        self.assertTrue(self.store.inspect()['durable_outcome'])
        self.recovered_without_native_action()

    def test_load_automatically_validates_and_publishes_saved_outcome(self):
        self.crash('outcome_saved')
        self.goal.step()
        from unified_body_v2 import UnifiedBody
        with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native replay')):
            self.assertEqual(MotionJournal(self.store.path).load().checkpoint(),self.goal.checkpoint())

    def test_corrupt_or_conflicting_durable_outcomes_stay_blocked(self):
        self.crash('outcome_saved')
        before=self.store.inspect()
        with sqlite3.connect(self.store.path) as db:
            original=json.loads(db.execute('SELECT candidate FROM outcome').fetchone()[0])
        for case in ('checksum','request','receipt','goal_transition','source'):
            candidate=deepcopy(original)
            p=candidate['payload']
            if case=='checksum':candidate['sha256']='0'*64
            elif case=='request':p['request']['event_id']='unrelated'
            elif case=='receipt':p['receipt']['owner_ticks']=999
            elif case=='source':p['source']='0'*64
            else:
                p['after']['payload']['task']['stop_reason']='invented transition'
                p['after']['sha256']=digest(p['after']['payload'])
            if case!='checksum':candidate['sha256']=digest(p)
            with sqlite3.connect(self.store.path) as db:
                db.execute('UPDATE outcome SET candidate=?',(json.dumps(candidate),))
            with self.subTest(case=case),self.assertRaises(ValueError):self.store.recover()
            self.assertEqual(self.store.inspect(),before)

    def test_two_fresh_writers_recover_one_outcome_without_another_tick(self):
        self.crash('outcome_saved')
        self._two_writers_expect_one_tick()

    def test_crash_after_commit_before_response_deduplicates(self):
        self.crash('committed')
        after=self.store.load().checkpoint()
        expected=self.goal.step()
        self.assertEqual(after,self.goal.checkpoint())
        self.assertEqual(self.store.step(event_id=self.event,expected_head=self.head),expected)
        self.assertEqual(self.store.load().checkpoint(),after)

    def test_tampered_goal_fails_before_intent_or_action(self):
        with sqlite3.connect(self.store.path) as db:
            saved=deepcopy(self.origin)
            saved['payload']['task']['elapsed']+=1
            saved['sha256']=digest(saved['payload'])
            db.execute('UPDATE state SET goal=?,head=?',(json.dumps(saved),saved['sha256']))
        with self.assertRaises(ValueError):
            self.store.step(event_id=self.event,expected_head=saved['sha256'])
        self.assertIsNone(self.store.inspect()['pending'])

    def test_two_fresh_writers_same_token_execute_only_once(self):
        self._two_writers_expect_one_tick()

    def _two_writers_expect_one_tick(self):
        cmd=[sys.executable,str(Path(__file__).with_name('recovery_fault_worker.py')),
            '--native-root',str(NATIVE),'--journal',str(self.store.path),
            '--marker',str(self.root/'unused.json'),'--fault','none',
            '--event-id',self.event,'--expected-head',self.head]
        workers=[subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        outputs=[p.communicate(timeout=180) for p in workers]
        for p,output in zip(workers,outputs):self.assertEqual(p.returncode,0,output[1])
        self.assertEqual(outputs[0][0],outputs[1][0])
        expected=self.goal.step()
        self.assertEqual(outputs[0][0].strip(),digest(expected))
        self.assertEqual(self.store.load().checkpoint(),self.goal.checkpoint())
        self.assertEqual(self.store.inspect()['receipts'],1)


@unittest.skipUnless(os.environ.get('NASURAYA_RECOVERY_SOURCE'),'external saved MotionGoal fixture required')
class RecordedRecoveryTests(RecoveryTests):
    @classmethod
    def setUpClass(cls):
        cls.origin=json.loads(Path(os.environ['NASURAYA_RECOVERY_SOURCE']).read_text())
        MotionGoal.restore(deepcopy(cls.origin))


if __name__=='__main__':unittest.main()
