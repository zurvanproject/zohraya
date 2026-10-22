"""Causal routing, uncertainty, source binding and durable outcome contracts."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from .evaluate import fixture, request, prepare_defaults
from .monitor import SelfModel, snapshot, digest
from .metacognitive_control import ControlTrial, ControlJournal
from .run_metacognitive import train
from motion_journal import UnknownMotionOutcome
from unified_body_v2 import UnifiedBody


class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()
        cls.training_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.training_tmp.cleanup)
        cls.training_path = Path(cls.training_tmp.name)/'frozen.sqlite'
        train(cls.training_path, [.2, .25, .3, .35])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copyfile(self.training_path, self.root/'experience.sqlite')
        self.model = SelfModel(self.root/'experience.sqlite')

    def trial(self, *, arm='control', duration=.1, stale=False):
        body = fixture(.42)
        obs = snapshot(body)
        if stale:
            q = request(body, 'prelude', 6.)
            q.update(requested='observe', external={})
            body.cycle(**q)
        q = request(body, 'test', duration)
        return ControlTrial.start(body, self.model, q, obs, arm=arm)

    def test_report_only_and_control_share_prediction_but_not_action_on_unknown(self):
        control = self.trial(duration=.2)
        reporting = self.trial(duration=.2, arm='report_only')
        self.assertEqual(control.decision()['probability'], .5)
        self.assertEqual(control.decision()['probability'], reporting.decision()['probability'])
        self.assertEqual(control.decision()['choice'], 'defer')
        self.assertEqual(reporting.decision()['choice'], 'request_walk')

    def test_memory_ablation_removes_coverage_and_does_not_invent_learning(self):
        before = self.model.verify()
        self.assertEqual(self.trial().decision()['choice'], 'request_walk')
        no_memory = self.trial(arm='memory_disabled')
        self.assertEqual(no_memory.decision()['choice'], 'defer')
        self.assertEqual(no_memory.decision()['report']['inferred']['samples'], 0)
        self.assertEqual(self.model.verify(), before)

    def test_stale_refresh_is_exact_read_only_and_restores_known_context(self):
        trial = self.trial(stale=True)
        self.assertEqual(trial.contract['initial_decision']['choice'], 'refresh_observation')
        self.assertEqual(trial.decision()['choice'], 'request_walk')
        self.assertEqual(trial.body.checkpoint(), trial.contract['initial_body'])
        self.assertEqual(trial.contract['fresh_observation'], snapshot(trial.body))
        self.assertEqual(trial.decision()['report']['inferred']['samples'], 4)
        reporting = self.trial(stale=True, arm='report_only')
        self.assertEqual(reporting.decision()['report'], trial.decision()['report'])

    def test_unbounded_duration_cannot_be_requested(self):
        with self.assertRaises(ValueError):
            self.trial(duration=2.)

    def test_fresh_unknown_context_defers_after_one_refresh(self):
        trial = self.trial(duration=.2)
        self.assertIsNotNone(trial.contract['fresh_observation'])
        self.assertEqual(trial.decision()['report']['inferred']['samples'], 0)
        with self.assertRaises(ValueError):
            trial.step()
        self.assertEqual(trial.records, [])

    def test_native_only_exposes_no_self_model_probability(self):
        trial = self.trial(arm='native_only', duration=.2)
        self.assertIsNone(trial.decision()['report'])
        self.assertIsNone(trial.decision()['probability'])
        self.assertEqual(trial.decision()['choice'], 'request_walk')

    def test_direct_request_keeps_native_veto_authority(self):
        body = fixture(.95)
        trial = ControlTrial.start(body, self.model, request(body, 'guarded'),
                                   snapshot(body), arm='report_only')
        self.assertEqual(trial.decision()['choice'], 'request_walk')
        receipt = trial.step()
        self.assertNotEqual(receipt['owner']['selected_action'], 'walk')
        self.assertTrue(receipt['owner']['physical_model_valid'])

    def test_deferred_journal_does_not_create_an_execution_intent(self):
        trial = self.trial(duration=.2)
        saved = trial.checkpoint()
        journal = ControlJournal.create(self.root/'deferred.sqlite', trial)
        with self.assertRaises(ValueError):
            journal.step(event_id='test', expected_head=saved['sha256'])
        self.assertIsNone(journal.inspect()['pending'])
        self.assertEqual(journal.inspect()['receipts'], 0)
        self.assertEqual(journal.load().checkpoint(), saved)

    def test_one_native_request_budget_and_idempotent_journal(self):
        trial = self.trial()
        before = trial.checkpoint()
        q = trial.request()
        journal = ControlJournal.create(self.root/'trial.sqlite', trial)
        receipt = journal.step(event_id=q['event_id'], expected_head=before['sha256'])
        after = journal.load().checkpoint()
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('duplicate cycle')):
            self.assertEqual(journal.step(event_id=q['event_id'], expected_head=before['sha256']), receipt)
        self.assertEqual(journal.load().checkpoint(), after)
        with self.assertRaises(ValueError):
            journal.load().step()

    def test_saved_outcome_recovery_has_no_native_calls(self):
        trial = self.trial()
        journal = ControlJournal.create(self.root/'trial.sqlite', trial)
        def interrupt(stage, goal):
            if stage == 'outcome_saved':
                raise RuntimeError('crash after durable outcome')
        with self.assertRaises(RuntimeError):
            journal.step(event_id=trial.request()['event_id'],
                         expected_head=trial.checkpoint()['sha256'], hook=interrupt)
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native replay')):
            recovered = journal.recover()
        self.assertEqual(recovered['native_actions_executed'], 0)
        self.assertEqual(journal.load().task['elapsed'], 1)

    def test_unknown_outcome_blocks_every_retry(self):
        trial = self.trial()
        saved = trial.checkpoint()
        journal = ControlJournal.create(self.root/'trial.sqlite', trial)
        def interrupt(stage, goal):
            if stage == 'executed':
                raise RuntimeError('crash before durable outcome')
        with self.assertRaises(RuntimeError):
            journal.step(event_id=trial.request()['event_id'], expected_head=saved['sha256'], hook=interrupt)
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('native replay')):
            with self.assertRaises(UnknownMotionOutcome):
                journal.recover()
            with self.assertRaises(UnknownMotionOutcome):
                journal.step(event_id='test', expected_head=saved['sha256'])

    def test_rehashed_wrong_decision_or_refresh_is_rejected(self):
        trial = self.trial(duration=.2)
        for target in ('final_decision', 'fresh_observation'):
            saved = trial.checkpoint()
            if target == 'final_decision':
                saved['payload']['contract'][target]['choice'] = 'request_walk'
            else:
                saved['payload']['contract'][target]['minimum']['pain'] = .99
            saved['sha256'] = digest(saved['payload'])
            with self.assertRaises(ValueError):
                ControlTrial.restore(saved)

    def test_conflicting_receipt_and_source_policy_are_rejected(self):
        trial = self.trial()
        trial.step()
        saved = trial.checkpoint()
        bad = deepcopy(saved)
        bad['payload']['records'][0]['owner']['selected_action'] = 'invented'
        bad['sha256'] = digest(bad['payload'])
        with self.assertRaises(ValueError):
            ControlTrial.restore(bad)
        saved['payload']['policy']['max_native_requests'] = 2
        saved['sha256'] = digest(saved['payload'])
        with self.assertRaises(ValueError):
            ControlTrial.restore(saved)

    def test_restored_decision_and_next_native_result_match(self):
        first = self.trial(stale=True)
        second = ControlTrial.restore(json.loads(json.dumps(first.checkpoint())))
        self.assertEqual(first.decision(), second.decision())
        self.assertEqual(first.step(), second.step())
        self.assertEqual(first.checkpoint(), second.checkpoint())

    def test_pending_training_outcome_cannot_be_used_for_control(self):
        body = fixture(.3)
        self.model.begin(body, request(body, 'unresolved'))
        with self.assertRaises(ValueError):
            self.trial()

    def test_preparation_reads_evidence_without_any_native_preview(self):
        body = fixture(.42)
        before = body.checkpoint()
        q = request(body, 'read-only')
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('hidden preview')):
            trial = ControlTrial.start(body, self.model, q, snapshot(body), arm='control')
            self.assertEqual(trial.decision()['choice'], 'request_walk')
        self.assertEqual(body.checkpoint(), before)

    def test_retained_checkpoint_memory_and_receipt_resume_without_native_replay(self):
        evidence = Path(__file__).with_name('evidence')/'metacognitive-control-v01'
        manifest = json.loads((evidence/'retained-manifest.json').read_text())
        unpacked = {}
        for name, expected in manifest['files'].items():
            packed = (evidence/name).read_bytes()
            self.assertEqual(hashlib.sha256(packed).hexdigest(), expected['gzip_sha256'])
            raw = gzip.decompress(packed)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected['raw_sha256'])
            path = self.root/name.removesuffix('.gz')
            path.write_bytes(raw)
            unpacked[name] = path
        model = SelfModel(unpacked['self-model.sqlite.gz'])
        self.assertEqual(model.verify()['episodes'], 8)
        before = json.loads(unpacked['control-before.json.gz'].read_text())
        journal = ControlJournal(unpacked['control-journal.sqlite.gz'])
        with patch.object(UnifiedBody, 'cycle', side_effect=AssertionError('retained native replay')):
            after = journal.load()
            receipt = journal.step(event_id=before['payload']['contract']['request']['event_id'],
                                   expected_head=before['sha256'])
        self.assertEqual(after.checkpoint()['sha256'], manifest['retained_after_sha256'])
        self.assertEqual(after.records, [receipt])


if __name__ == '__main__':
    unittest.main()
