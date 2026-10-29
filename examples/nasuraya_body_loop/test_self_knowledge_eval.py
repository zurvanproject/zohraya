"""Evaluation integrity: frozen labels, pre-outcome writes and control matching."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reflection_cycle import digest
from . import self_knowledge_eval as evaluation


class FakeBodyLoop:
    """Fast test double reverses outcomes at holdout to expose accidental refits."""
    def __init__(self, path, fixture, max_actions):
        self.path, self.fixture, self.max_actions = Path(path), fixture, max_actions
        self.count, self.records = 0, {}
        self.engine = self

    @classmethod
    def start(cls, path, *, fixture, max_actions):
        return cls(path, fixture, max_actions)

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def observe(self):
        return dict(checkpoint_sha256=digest([self.fixture, self.count]),
            minimum_state=dict(energy=.8, fatigue=.1, pain=.1,
                sleep_pressure=.95 if self.fixture == 'sleep' else .1))

    def step(self, *, decision_id, duration_s, preferred_action):
        # If the evaluator moves prediction reservation after execution, fail now.
        reservations = [json.loads(line) for line in
                        (self.path.parent / 'predictions.jsonl').read_text().splitlines()]
        assert reservations[-1]['id'] == decision_id
        assert reservations[-1]['before_checkpoint_sha256'] == self.observe()['checkpoint_sha256']
        actual = preferred_action
        if preferred_action == 'walk':
            actual = 'protect' if self.fixture == 'sleep' else 'walk'
            if self.count >= evaluation.PROTOCOL['warmup_rounds']:
                actual = 'walk' if actual == 'protect' else 'protect'
        self.count += 1
        self.records[decision_id] = dict(id=decision_id, status='complete',
            actual_outcome=dict(status='completed', body_receipt={}, body_checkpoint={},
                                selected_action=actual))
        return dict(actual_action=actual, status='complete', body_audit={},
                    self_model_after=self.observe())

    def get(self, decision_id): return self.records[decision_id]

    def status(self):
        return dict(completed_cycles=self.count, actions_remaining=self.max_actions-self.count)


class SelfKnowledgeEvaluationTests(unittest.TestCase):
    @staticmethod
    def _save_rows(path, rows):
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def test_shuffled_control_preserves_groups_sources_and_outcomes(self):
        episodes = [dict(id=str(i), preferred='walk' if i < 8 else 'observe',
            duration_s=.1 if i % 2 else .3, context=str(i % 3),
            actual_action='protect' if i % 3 else 'walk', source='receipt:' + str(i))
            for i in range(16)]
        before = deepcopy(episodes)
        a = evaluation.shuffled_contexts(episodes, 20261029)
        b = evaluation.shuffled_contexts(episodes, 20261029)
        self.assertEqual(a, b)
        self.assertEqual(episodes, before)
        for old, new in zip(before, a):
            self.assertEqual({k: v for k, v in old.items() if k != 'context'},
                             {k: v for k, v in new.items() if k != 'context'})
        for pref in ('walk', 'observe'):
            for duration in (.1, .3):
                selected = lambda rows: sorted(row['context'] for row in rows
                    if row['preferred'] == pref and row['duration_s'] == duration)
                self.assertEqual(selected(before), selected(a))

    def test_temporal_holdout_is_frozen_even_when_outcomes_reverse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'eval'
            with patch.object(evaluation, 'BodyLoop', FakeBodyLoop):
                summary = evaluation.run_evaluation(path)
            trials = [json.loads(line) for line in (path/'trials.jsonl').read_text().splitlines()]
            training = json.loads((path/'training.json').read_text())
            heldout = [row for row in trials if row['phase'] == 'holdout']
            self.assertEqual(summary['actual_native_cycles'], 64)
            self.assertEqual(summary['training_receipts'], 40)
            self.assertEqual(summary['holdout']['scored'], 24)
            self.assertEqual(summary['holdout']['supported'], 24)
            self.assertEqual(len(training['episodes']), 40)
            self.assertEqual({row['training_sha256'] for row in heldout}, {training['sha256']})
            self.assertTrue(all(row['training_count'] == 40 for row in heldout))
            heldout_ids = {row['id'] for row in heldout}
            self.assertTrue(heldout_ids.isdisjoint({row['id'] for row in training['episodes']}))
            # Reversed walk outcomes must remain errors throughout heldout rounds.
            for row in heldout:
                if row['preferred'] == 'walk':
                    self.assertNotEqual(row['forecast']['predicted_action'], row['actual_action'])
                self.assertEqual(row['forecast']['samples'], 5)
                self.assertEqual(row['forecast']['pooled_samples'], 10)
            self.assertEqual(summary['holdout']['supported_accuracy'], .5)
            self.assertFalse(summary['holdout_outcomes_used_for_fitting'])
            self.assertTrue(summary['validation_passed'])
            # Integrity rejection is independent of whether the forecast improves.
            data = json.loads((path/'summary.json').read_text())
            data['actual_native_cycles'] = 63
            (path/'summary.json').write_text(json.dumps(data))
            self.assertFalse(evaluation.finalize_evaluation(path)['validation_passed'])
            with patch.object(evaluation, 'BodyLoop', FakeBodyLoop):
                with self.assertRaises(FileExistsError):
                    evaluation.run_evaluation(path)

    def test_changed_saved_brier_is_rejected_and_summary_is_rederived(self):
        for score_key in ('score', 'shuffled_score', 'zero_history_score'):
            with self.subTest(score_key=score_key), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'eval'
                with patch.object(evaluation, 'BodyLoop', FakeBodyLoop):
                    original = evaluation.run_evaluation(path)
                rows = [json.loads(line) for line in (path/'trials.jsonl').read_text().splitlines()]
                rows[-1][score_key]['brier'] = -42.
                self._save_rows(path/'trials.jsonl', rows)
                altered = deepcopy(original)
                altered['heldout_brier_improvement_absolute'] = 999.
                altered['context_helped_on_this_constructed_holdout'] = True
                (path/'summary.json').write_text(json.dumps(altered))
                final = evaluation.finalize_evaluation(path)
                self.assertFalse(final['validation_passed'])
                self.assertFalse(final['validation_checks']['scores_match_frozen_forecasts'])
                self.assertTrue(final['validation_checks']['forecasts_match_prior_evidence'])
                self.assertEqual(final['holdout'], original['holdout'])
                self.assertEqual(final['heldout_brier_improvement_absolute'],
                                 original['heldout_brier_improvement_absolute'])
                self.assertEqual(final['context_helped_on_this_constructed_holdout'],
                                 original['context_helped_on_this_constructed_holdout'])

    def test_consistently_rewritten_forecast_is_rejected_against_prior_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'eval'
            with patch.object(evaluation, 'BodyLoop', FakeBodyLoop):
                original = evaluation.run_evaluation(path)
            rows = [json.loads(line) for line in (path/'trials.jsonl').read_text().splitlines()]
            predictions = [json.loads(line) for line in (path/'predictions.jsonl').read_text().splitlines()]
            row = rows[-1]
            row['forecast']['distribution'] = dict.fromkeys(evaluation.CATEGORIES, .25)
            row['forecast']['predicted_action'] = 'walk'
            row['score'] = evaluation.score_action(row['forecast'], row['actual_action'], source=row['source'])
            predictions[-1]['forecast'] = deepcopy(row['forecast'])
            self._save_rows(path/'trials.jsonl', rows)
            self._save_rows(path/'predictions.jsonl', predictions)
            final = evaluation.finalize_evaluation(path)
            self.assertFalse(final['validation_passed'])
            self.assertTrue(final['validation_checks']['forecasts_preserved'])
            self.assertTrue(final['validation_checks']['scores_match_frozen_forecasts'])
            self.assertFalse(final['validation_checks']['forecasts_match_prior_evidence'])
            self.assertEqual(final['holdout'], original['holdout'])

    def test_self_consistent_changed_protocol_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'eval'
            with patch.object(evaluation, 'BodyLoop', FakeBodyLoop):
                summary = evaluation.run_evaluation(path)
            protocol = json.loads((path/'protocol.json').read_text())
            protocol['shuffle_seed'] = 7
            protocol['protocol_sha256'] = digest({k: v for k, v in protocol.items()
                                                 if k != 'protocol_sha256'})
            summary['protocol_sha256'] = protocol['protocol_sha256']
            (path/'protocol.json').write_text(json.dumps(protocol))
            (path/'summary.json').write_text(json.dumps(summary))
            final = evaluation.finalize_evaluation(path)
            self.assertFalse(final['validation_passed'])
            self.assertFalse(final['validation_checks']['protocol_preserved'])

    def test_empty_summary_does_not_invent_accuracy_or_improvement(self):
        summary = evaluation.summarize_trials([])
        self.assertEqual(summary['scored'], 0)
        self.assertEqual(summary['coverage'], 0.)
        self.assertIsNone(summary['mean_brier'])
        self.assertIsNone(summary['supported_accuracy'])


if __name__ == '__main__':
    unittest.main()
