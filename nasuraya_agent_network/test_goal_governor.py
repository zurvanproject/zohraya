"""No model/API/simulator calls: fake durable network receipts exercise goal selection."""
from dataclasses import replace
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from . import engine, worker, goal_governor as goal


class GoalChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.run_id = 'verified-1'
        self.output = self.workspace / self.run_id
        self.output.mkdir()
        for role in worker.ROLES:
            (self.output / role).mkdir()
        self.binding = {'schema': engine.VERSION, 'source_sha256': 'a' * 64,
                        'implementation_sha256': 'b' * 64, 'max_workers': 2}
        self.receipts = {role: {'agent': role, 'passed': True,
                          'model_api_calls': 0, 'network_syscalls_denied': True,
                          'commands': [{'returncode': 0, 'interrupted': None,
                                        'network_syscalls_denied': True}], 'artifacts': {}}
                         for role in worker.ROLES}
        self.receipts['self_model']['metrics'] = {
            'native_cycles': 64, 'heldout_trials': 24,
            'context_brier': .2, 'pooled_brier': .3,
            'pooled_minus_context_brier': .1,
            'context_helped_on_constructed_holdout': True,
        }
        self.report = {**self.binding, 'run_id': self.run_id, 'status': 'passed',
                       'mode': 'offline_fixed_workers', 'model_api_calls': 0,
                       'workers': self.receipts, 'reviewer': engine.review(self.receipts)}
        with closing(sqlite3.connect(self.workspace / 'ledger.sqlite')) as db:
            db.execute('CREATE TABLE runs (id TEXT PRIMARY KEY, fingerprint TEXT, status TEXT, report TEXT)')
            db.execute('CREATE TABLE jobs (run_id TEXT, agent TEXT, status TEXT, receipt TEXT, PRIMARY KEY(run_id,agent))')
            db.commit()
        self.persist()

    def persist(self, *, status='finished'):
        self.report['reviewer'] = engine.review(self.receipts)
        (self.output / 'summary.json').write_text(engine.encode(self.report), encoding='utf-8')
        with closing(sqlite3.connect(self.workspace / 'ledger.sqlite')) as db:
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?,?)',
                       (self.run_id, sha256(engine.encode(self.binding).encode('utf-8')).hexdigest(), status, engine.encode(self.report)))
            for role, receipt in [*self.receipts.items(), ('reviewer', self.report['reviewer'])]:
                db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',
                           (self.run_id, role, 'completed', engine.encode(receipt)))
            db.commit()

    def evidence(self):
        return goal.verified_network(self.workspace, self.run_id)

    def test_verified_report_selects_rare_action(self):
        self.assertEqual(goal.propose(self.evidence())['chosen']['id'], 'rare_slow_breath')

    def test_evidence_sha_matches_stored_report(self):
        self.assertEqual(self.evidence()['report_sha256'], goal.digest(self.report))

    def test_negative_forecast_delta_switches_goal(self):
        m = self.receipts['self_model']['metrics']
        m.update(context_brier=.41, pooled_brier=.3, pooled_minus_context_brier=-.11,
                 context_helped_on_constructed_holdout=False)
        self.persist()
        self.assertEqual(goal.propose(self.evidence())['chosen']['id'], 'audit_self_model_regression')

    def test_zero_delta_switches_goal(self):
        m = self.receipts['self_model']['metrics']
        m.update(context_brier=.3, pooled_brier=.3, pooled_minus_context_brier=0.,
                 context_helped_on_constructed_holdout=False)
        self.persist()
        self.assertEqual(goal.propose(self.evidence())['chosen']['id'], 'audit_self_model_regression')

    def test_counterfactual_reprioritization(self):
        rare = goal.GAPS[0]
        new = replace(rare, observed=12, misses=3, uncertainty=.15)
        gaps = (new, *goal.GAPS[1:])
        self.assertEqual(goal.propose(self.evidence(), gaps)['chosen']['id'], 'sqlite_recovery')

    def test_order_independence(self):
        evidence = self.evidence()
        self.assertEqual(goal.propose(evidence), goal.propose(evidence, tuple(reversed(goal.GAPS))))

    def test_paid_and_body_changes_blocked(self):
        results = goal.propose(self.evidence())['assessments']
        by_id = {item['id']: item for item in results}
        self.assertIn('paid_action_not_authorized', by_id['paid_affect']['blockers'])
        self.assertIn('canonical_body_write_not_authorized', by_id['rewrite_body']['blockers'])

    def test_all_blocked_abstains(self):
        gaps = (replace(goal.GAPS[0], observed=0, misses=0),)
        self.assertIsNone(goal.propose(self.evidence(), gaps)['chosen'])

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            goal.propose(self.evidence(), (goal.GAPS[0], goal.GAPS[0]))

    def test_boolean_and_nan_rejected(self):
        with self.assertRaises(ValueError):
            replace(goal.GAPS[0], misses=True)
        with self.assertRaises(ValueError):
            replace(goal.GAPS[0], uncertainty=float('nan'))
        with self.assertRaises(ValueError):
            replace(goal.GAPS[0], cost_usd=True)

    def test_untrusted_provenance_rejected(self):
        with self.assertRaises(ValueError):
            replace(goal.GAPS[0], source='https://other.example/pr/96')

    def test_noncanonical_ledger_fingerprint_rejected(self):
        with closing(sqlite3.connect(self.workspace / 'ledger.sqlite')) as db:
            db.execute('UPDATE runs SET fingerprint=? WHERE id=?',
                       (goal.digest(self.binding), self.run_id))
            db.commit()
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            self.evidence()

    def test_inflight_run_rejected(self):
        self.persist(status='running')
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            self.evidence()

    def test_tampered_report_rejected(self):
        (self.output / 'summary.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            self.evidence()

    def test_artifact_tampering_rejected(self):
        (self.output / 'body' / 'new-file.txt').write_text('surprise')
        with self.assertRaises(ValueError):
            self.evidence()

    def test_job_ledger_tampering_rejected(self):
        with closing(sqlite3.connect(self.workspace / 'ledger.sqlite')) as db:
            db.execute("UPDATE jobs SET status='failed' WHERE agent='memory'")
            db.commit()
        with self.assertRaisesRegex(ValueError, 'job ledger'):
            self.evidence()

    def test_paid_receipt_rejected(self):
        self.receipts['memory']['model_api_calls'] = 1
        self.persist()
        with self.assertRaisesRegex(ValueError, 'reviewer'):
            self.evidence()

    def test_missing_or_negative_self_model_evidence_rejected(self):
        self.receipts['self_model'].pop('metrics')
        self.persist()
        with self.assertRaisesRegex(ValueError, 'self-model'):
            self.evidence()

    def test_score_inconsistency_rejected(self):
        self.receipts['self_model']['metrics']['pooled_minus_context_brier'] = .99
        self.persist()
        with self.assertRaisesRegex(ValueError, 'contradictory'):
            self.evidence()

    def test_nonfinite_score_rejected(self):
        # The network's serializer itself forbids NaN in durable receipts.
        # The goal selector must also reject a corrupted in-memory input.
        with self.assertRaisesRegex(ValueError, 'invalid self-model delta'):
            goal.propose({**self.evidence(), 'delta': float('nan')})

    def test_report_is_only_output_and_never_overwrites(self):
        path = self.workspace / 'proposal.json'
        result = goal.run(self.workspace, self.run_id, path)
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text()), result)
        self.assertFalse(result['auto_execution'])
        self.assertEqual(result['api_calls'], 0)
        self.assertEqual(result['decision_sha256'], goal.digest({k:v for k,v in result.items() if k!='decision_sha256'}))
        with self.assertRaisesRegex(ValueError, 'must be new'):
            goal.run(self.workspace, self.run_id, path)

    def test_strict_loader_rejects_duplicate_keys(self):
        path = self.workspace / 'duplicate.json'
        path.write_text('{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            goal.strict_load(path)


if __name__ == '__main__':
    unittest.main()
