"""Functional checks of the complete frozen-transfer protocol on fresh bodies."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .adapters import digest
from .transfer import PLAN, read_sealed, run, save_new


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name)/'experiment'
        try:
            cls.summary = run(cls.output)
            cls.result = read_sealed(cls.output/'results.json')
        except BaseException:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_plan_and_training_are_content_sealed(self):
        plan = read_sealed(self.output/'plan.json')
        training = read_sealed(self.output/'training.json')
        self.assertEqual(plan['cases'], PLAN['cases'])
        self.assertEqual(digest(plan), self.summary['plan_sha256'])
        self.assertEqual(digest(training), self.summary['training_sha256'])
        self.assertEqual(len(training['history']), 2)
        self.assertFalse(training['test_results_in_training'])
        self.assertEqual(self.summary['test_outcomes_used_for_training'], 0)

    def test_every_scored_forecast_was_sealed_before_native_execution(self):
        for row in self.result['cases']:
            if not row['scored']: continue
            before = read_sealed(self.output/(row['case']['id']+'-before.json'))
            self.assertIsNone(before['prediction']['outcome'])
            self.assertEqual(before['native_records_before'], 0)
            self.assertEqual(row['preexecution_seals'], [digest(before)])
            self.assertEqual(row['prediction']['outcome_source'], row['production_prediction']['outcome_source'])
            self.assertEqual(row['native_cycles'], 1)
            self.assertEqual(row['replay_native_cycles'], 0)

    def test_frozen_transfer_is_not_imported_into_production_history(self):
        for row in self.result['cases']:
            if not row['scored']: continue
            self.assertEqual(row['production_prediction']['samples'], 0)
            self.assertIn(row['prediction']['samples'], (0, 2))
        self.assertFalse(self.summary['production_history_imported'])
        self.assertFalse(self.summary['decision_writeback'])

    def test_invalid_or_changed_observations_are_not_false_training_labels(self):
        rows = {r['case']['id']:r for r in self.result['cases']}
        stale, changed = rows['stale-checkpoint'], rows['change-after-forecast']
        for row in (stale, changed):
            self.assertEqual(row['status'], 'blocked')
            self.assertEqual(row['native_cycles'], 0)
            self.assertFalse(row['scored'])
        self.assertEqual(stale['preexecution_seals'], [])
        self.assertEqual(changed['pending'], ['held-out'])
        self.assertIsNone(changed['prediction']['outcome'])

    def test_result_labels_follow_native_action_instead_of_fixture_expectations(self):
        for row in self.result['cases']:
            if not row['scored']: continue
            self.assertEqual(row['prediction']['outcome'], row['preferred_action'] == row['actual_action'])
            if row['prediction']['domain']['restrictions']:
                self.assertEqual(row['preferred_action'], 'observe')
                self.assertEqual(row['prediction']['samples'], 0)

    def test_counts_report_coverage_without_a_generalization_claim(self):
        self.assertEqual(self.summary['case_count'], 10)
        self.assertEqual(self.summary['scored_forecasts'], 8)
        self.assertEqual(self.summary['blocked_cases'], 2)
        self.assertEqual(self.summary['training_native_cycles'], 2)
        self.assertEqual(self.summary['test_native_cycles'], 8)
        self.assertFalse(self.summary['general_improvement_demonstrated'])
        self.assertFalse(self.summary['empirical_validation'])

    def test_existing_output_cannot_be_overwritten_or_restart_experiment(self):
        with patch('examples.nasuraya_body_loop.host.BodyLoop.start', side_effect=AssertionError('rerun')):
            with self.assertRaises(FileExistsError): run(self.output)

    def test_content_tampering_is_detected(self):
        path = Path(self.temp.name)/'tampered.json'
        save_new(path, {'outcome': None})
        value = json.loads(path.read_text()); value['value']['outcome'] = True
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): read_sealed(path)

    def test_cli_requires_an_explicit_evidence_destination(self):
        from examples.nasuraya_body_loop.__main__ import ROOT
        result = subprocess.run([sys.executable, '-S', '-m', 'examples.nasuraya_research.control',
                                 'transfer'], cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--output-dir is required', result.stderr)


if __name__ == '__main__':
    unittest.main()
