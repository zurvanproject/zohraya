"""Interactions that only become possible in the unified source tree."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from .host import BodyLoop
from .metacognition import configure
from examples.nasuraya_aesthetics.appraisal import apply, appraise
from examples.nasuraya_aesthetics.fixtures import observation
from examples.nasuraya_self_model.monitor import SelfModel


class UnifiedCombinationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.body=self.root/'body.sqlite';self.memory=self.root/'model.sqlite'

    def enable(self,loop,mode):
        configure(loop,memory_path=self.memory,mode=mode,create_memory=True,
                  expected_checkpoint=loop.body().checkpoint()['sha256'])

    def test_aesthetic_input_metacognition_and_native_affect_replay_together(self):
        with BodyLoop.start(self.body,max_actions=2) as loop:
            self.enable(loop,'shadow')
            before=deepcopy(loop.body().affect['affect'])
            first=apply(loop,observation())
            self.assertEqual(first['native_receipt']['actual_action'],'observe')
            self.assertGreater(loop.body().affect['affect']['admiration'],before['admiration'])
            record=loop.records()[0]
            row=loop.metacognition._get(record['id'])
            self.assertEqual(row['native_request']['external'],record['request']['execution']['external'])
            self.assertTrue(row['native_request']['external']['social'])
            state=loop.body().checkpoint();knowledge=SelfModel(self.memory).verify()
            self.assertFalse(knowledge['pending'])
        with BodyLoop(self.body) as loop:
            replay=apply(loop,observation())
            self.assertTrue(replay['native_receipt']['replayed'])
            self.assertEqual(loop.body().checkpoint(),state)
            self.assertEqual(SelfModel(self.memory).verify(),knowledge)

    def test_unseen_social_walk_cannot_bypass_admission(self):
        with BodyLoop.start(self.body,max_actions=1) as loop:
            self.enable(loop,'enforce');loop.observe()
            before=loop.body().checkpoint();knowledge=SelfModel(self.memory).verify()
            result=loop.step(decision_id='social-walk',preferred_action='walk',
                             social_event=appraise(observation())['social_event'])
            self.assertEqual(result['status'],'deferred')
            self.assertFalse(result['native_executed'])
            self.assertEqual(loop.body().checkpoint(),before)
            self.assertEqual(SelfModel(self.memory).verify(),knowledge)

    def test_recovery_action_keeps_native_arbitration_with_metacognition(self):
        with BodyLoop.start(self.body,fixture='recovery-ready',max_actions=1) as loop:
            self.enable(loop,'enforce');loop.observe()
            before=loop.body().owner.body()['minimum_state']['sleep_pressure']
            result=loop.step(decision_id='unified-sleep',preferred_action='sleep',duration_s=1.)
            self.assertEqual(result['actual_action'],'sleep')
            self.assertLess(loop.body().owner.body()['minimum_state']['sleep_pressure'],before)
            self.assertFalse(SelfModel(self.memory).verify()['pending'])


if __name__=='__main__':unittest.main()
