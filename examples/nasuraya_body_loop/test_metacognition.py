"""Core-vs-model attribution, real receipt learning and two-ledger recovery."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from .host import BodyLoop, UnifiedBody
from .api_host import BodyAPIHost
from .metacognition import configure, InterruptedExecution, canonical, digest
from examples.nasuraya_self_model.monitor import SelfModel
from examples.nasuraya_agent_loop.tests.test_agents_api import call


class MetacognitiveAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.seed.cleanup)
        cls.seed_memory = Path(cls.seed.name)/'model.sqlite'
        SelfModel.create(cls.seed_memory)
        for i in range(3):
            with BodyLoop.start(Path(cls.seed.name)/f'probe-{i}.sqlite', max_actions=1) as loop:
                configure(loop, memory_path=cls.seed_memory, mode='shadow',
                          expected_checkpoint=loop.body().checkpoint()['sha256'])
                loop.observe()
                result = loop.step(decision_id=f'seed-{i}', duration_s=.1)
                if result['actual_action'] != 'walk':
                    raise AssertionError('synthetic training request was not admitted')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'body.sqlite'
        self.memory = self.root/'model.sqlite'
        shutil.copyfile(self.seed_memory, self.memory)
        self.loop = BodyLoop.start(self.path, max_actions=3)
        self.addCleanup(lambda: self.loop.close() if self.loop.engine.db is not None else None)

    def enable(self, mode='enforce'):
        return configure(self.loop, memory_path=self.memory, mode=mode,
                         expected_checkpoint=self.loop.body().checkpoint()['sha256'])

    def invoke(self, host, name, args=None, identity='call', turn='turn', session='session'):
        return host.handle_required(session, call(name, args, identity, turn))

    def action_args(self, host, duration=.1):
        obs = json.loads(self.invoke(host, 'observe_body', identity='read')['output'])
        return dict(action='walk', duration_s=duration, observed_checkpoint_sha256=obs['checkpoint_sha256'])

    def test_legacy_host_is_unchanged_until_opted_in(self):
        host = BodyAPIHost(self.loop)
        self.assertNotIn('metacognition', host.snapshot())
        self.assertNotIn('assess_body_action', {t['name'] for t in host.definitions()})

    def test_exact_action_assessment_reads_without_learning_or_body_advance(self):
        self.enable()
        host = BodyAPIHost(self.loop, mode='bounded', target_cycles=1)
        args = self.action_args(host)
        before = self.loop.body().checkpoint()
        counts = SelfModel(self.memory).verify()
        assessment = json.loads(self.invoke(host, 'assess_body_action', args, identity='assess')['output'])
        self.assertEqual((assessment['samples'], assessment['probability']), (3, .8))
        self.assertEqual(assessment['recommendation'], 'request_walk')
        self.assertEqual(SelfModel(self.memory).verify(), counts)
        self.assertEqual(self.loop.body().checkpoint(), before)
        novel = json.loads(self.invoke(host, 'assess_body_action', {**args, 'duration_s':.2}, identity='novel')['output'])
        self.assertEqual((novel['samples'], novel['recommendation']), (0, 'defer'))
        self.assertNotIn('payload', json.dumps(assessment))
        self.assertNotIn('memory_path', json.dumps(assessment))

    def test_assessment_cannot_borrow_another_turns_observation(self):
        self.enable()
        host = BodyAPIHost(self.loop, mode='bounded', target_cycles=1)
        args = self.action_args(host)
        result = self.invoke(host, 'assess_body_action', args, identity='wrong-turn', turn='other')
        self.assertFalse(result['success'])
        self.assertEqual(self.loop.status()['completed_cycles'], 0)

    def test_integral_json_durations_share_assessment_and_execution_context(self):
        self.enable('shadow')
        host = BodyAPIHost(self.loop, mode='bounded', target_cycles=1)
        args = self.action_args(host, duration=1.0)
        integer = host.admission_assessment('walk', 1, args['observed_checkpoint_sha256'])
        floating = host.admission_assessment('walk', 1.0, args['observed_checkpoint_sha256'])
        self.assertEqual(integer, floating)
        receipt = json.loads(self.invoke(host, 'request_body_action', args, identity='whole-second')['output'])
        row = self.loop.metacognition._get(receipt['decision_id'])
        self.assertIs(type(row['native_request']['duration_s']), int)
        self.assertTrue(row['outcome']['learned'])

    def test_enforcement_uses_actual_duration_without_trusting_prior_assessment(self):
        self.enable()
        host = BodyAPIHost(self.loop, mode='bounded', target_cycles=1)
        args = self.action_args(host)
        self.invoke(host, 'assess_body_action', args, identity='known')
        before = self.loop.body().checkpoint()
        counts = SelfModel(self.memory).verify()
        # A known .1-second assessment is not permission for a .2-second walk.
        result = self.invoke(host, 'request_body_action', {**args, 'duration_s':.2}, identity='defer')
        receipt = json.loads(result['output'])
        self.assertTrue(result['success'])
        self.assertEqual(receipt['status'], 'deferred')
        self.assertFalse(receipt['native_executed'])
        self.assertEqual(self.loop.body().checkpoint(), before)
        self.assertEqual(SelfModel(self.memory).verify(), counts)
        progress = host.evaluate()
        self.assertEqual((progress['completed_cycles'], progress['failed_cycles'], progress['deferred_cycles']), (0, 0, 1))
        self.assertFalse(progress['goal_reached'])
        record = self.loop.records()[0]
        self.assertFalse(record['feedback']['verified'])
        self.assertEqual(self.loop.engine.recall(record['context'], record['topic']), {})

    def test_known_request_executes_and_only_verified_effect_trains(self):
        self.enable()
        self.loop.observe()
        receipt = self.loop.step(decision_id='known', duration_s=.1)
        self.assertEqual((receipt['requested_action'], receipt['actual_action']), ('walk', 'walk'))
        self.assertEqual(receipt['metacognition']['samples'], 3)
        self.assertEqual(SelfModel(self.memory).verify()['episodes'], 4)
        self.assertTrue(receipt['metacognition']['learning']['learned'])
        before = self.loop.body().checkpoint()
        self.assertEqual(self.loop.step(decision_id='known', duration_s=.1)['actual_action'], 'walk')
        self.assertEqual(self.loop.body().checkpoint(), before)
        self.assertEqual(SelfModel(self.memory).verify()['episodes'], 4)

    def test_shadow_mode_can_run_a_bounded_unknown_probe(self):
        self.enable('shadow')
        self.loop.observe()
        result = self.loop.step(decision_id='shadow', duration_s=.2)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['metacognition']['recommendation'], 'defer')
        self.assertEqual(result['metacognition']['effective_choice'], 'execute_under_native_guards')
        self.assertEqual(SelfModel(self.memory).verify()['episodes'], 4)

    def test_core_choice_is_gated_and_learned_separately_from_model_preference(self):
        self.loop.close()
        self.loop = BodyLoop.start(self.root/'sleep.sqlite', fixture='sleep', max_actions=3)
        self.enable('shadow')
        self.loop.observe()
        first = self.loop.step(decision_id='sleep-first')
        self.assertEqual((first['requested_action'], first['actual_action']), ('walk', 'protect'))
        self.enable('enforce')
        self.loop.observe()
        second = self.loop.step(decision_id='sleep-second', preferred_action='walk')
        self.assertEqual((second['requested_action'], second['actual_action']), ('observe', 'observe'))
        self.assertEqual(second['metacognition']['action'], 'observe')
        self.assertEqual(SelfModel(self.memory).verify()['last']['requested'], 'observe')

    def test_commit_before_learning_recovers_from_receipt_without_native_call(self):
        self.enable('shadow')
        self.loop.observe()
        with patch.object(self.loop.adapter, '_finish_learning', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.loop.step(decision_id='committed')
        self.assertEqual(len(SelfModel(self.memory).verify()['pending']), 1)
        head = self.loop.body().checkpoint()
        self.loop.close()
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native replay')):
            self.loop = BodyLoop(self.path)
            self.assertEqual(self.loop.body().checkpoint(), head)
        self.assertEqual(SelfModel(self.memory).verify()['episodes'], 4)
        self.assertEqual(SelfModel(self.memory).verify()['pending'], [])

    def test_learning_before_bridge_result_save_does_not_train_twice(self):
        self.enable('shadow')
        self.loop.observe()
        original = self.loop.adapter._put
        def crash(row):
            if row['phase'] == 'complete':
                raise KeyboardInterrupt
            return original(row)
        with patch.object(self.loop.adapter, '_put', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.loop.step(decision_id='already-learned')
        self.assertEqual(SelfModel(self.memory).verify()['pending'], [])
        self.loop.close()
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native replay')):
            self.loop = BodyLoop(self.path)
        self.assertEqual(SelfModel(self.memory).verify()['episodes'], 4)
        self.assertEqual(self.loop.metacognition.public_record('already-learned')['learning']['learned'], True)

    def test_unknown_outcome_remains_readable_but_blocks_every_retry(self):
        self.enable('shadow')
        self.loop.observe()
        original = UnifiedBody.cycle
        def lost(body, **kwargs):
            original(body, **kwargs)
            raise KeyboardInterrupt
        with patch.object(UnifiedBody, 'cycle', lost):
            with self.assertRaises(KeyboardInterrupt):
                self.loop.step(decision_id='unknown')
        self.loop.close()
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native retry')):
            self.loop = BodyLoop(self.path)
            self.assertEqual(self.loop.status()['metacognition']['pending_outcomes'], 1)
            with self.assertRaises(InterruptedExecution):
                self.loop.step(decision_id='unknown')
            with self.assertRaises(InterruptedExecution):
                self.loop.step(decision_id='new')

    def test_memory_and_mode_cannot_be_silently_reset(self):
        self.enable()
        with self.assertRaises(ValueError):
            configure(self.loop, memory_path=self.root/'other.sqlite', mode='shadow',
                      expected_checkpoint=self.loop.body().checkpoint()['sha256'], create_memory=True)
        with self.assertRaises(ValueError):
            configure(self.loop, memory_path=self.memory, mode='shadow', expected_checkpoint='0'*64)

    def test_rehashed_decision_that_disagrees_with_saved_knowledge_is_rejected(self):
        self.enable()
        self.loop.observe()
        self.loop.step(decision_id='deferred', duration_s=.2)
        row = self.loop.adapter._get('deferred')
        row['decision']['choice'] = 'request_walk'
        self.loop.engine.db.execute('UPDATE body_metacognition SET value=?,sha256=? WHERE decision_id=?',
                                   (canonical(row), digest(row), 'deferred'))
        with self.assertRaises(ValueError):
            self.loop.metacognition.public_record('deferred')


if __name__ == '__main__':
    unittest.main()
