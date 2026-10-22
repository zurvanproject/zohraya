from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from .chromosomes import digest
from .design_decision import choose, committed_source, contract, evidence, fresh_source
from .design_memory import DesignMemory
from .run_design_cycle import evaluate, observe
from .traits import baseline, restore


def rehash(saved):
    head = digest(saved['payload']['contract'])
    for event in saved['payload']['events']:
        event['payload']['previous_sha256'] = head
        event['sha256'] = digest(event['payload'])
        head = event['sha256']
    saved['sha256'] = digest(saved['payload'])


class DesignCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.output = Path(cls.shared.name) / 'cycle'
        cls.result = evaluate(cls.output)
        cls.saved = json.loads((cls.output / 'experience-checkpoint.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'memory.sqlite'
        self.memory = DesignMemory.restore(self.path, self.saved)

    def test_actual_decision_changes_and_exact_cold_memory_reproduces_it(self):
        r = self.result
        self.assertTrue(all(r['checks'].values()))
        self.assertEqual(r['initial']['chosen'], 'baseline')
        self.assertEqual(r['after']['chosen'], 'foot_plus_2_percent')
        self.assertEqual(r['memory_disabled']['chosen'], 'baseline')
        self.assertEqual(r['cold'], r['after'])
        self.assertEqual(self.memory.recommend(), r['after'])
        self.assertEqual(r['fresh_physical_experiments'], 1)
        self.assertEqual(r['distinct_physical_observations'], 3)
        self.assertEqual(r['candidate_observations'], 4)
        self.assertEqual(self.memory.verify()['events'], 12)

    def test_cosmetic_change_is_rejected_and_score_matches_frozen_tradeoff(self):
        decision = self.memory.recommend()
        self.assertIn('no_sufficient_measured_net_gain', decision['candidates']['cosmetic_only']['reasons'])
        self.assertEqual(decision['candidates']['cosmetic_only']['status'], 'rejected')
        base = decision['candidates']['baseline']['metrics']
        row = decision['candidates']['foot_plus_2_percent']
        m = row['metrics']
        expected = (.45*(base['pressure_kpa']-m['pressure_kpa'])/base['pressure_kpa']
                    + .35*(m['capture_margin_m']-base['capture_margin_m'])/base['capture_margin_m']
                    - .20*(m['fuel_J']-base['fuel_J'])/base['fuel_J'] - .001)
        self.assertAlmostEqual(row['utility'], expected, places=12)
        self.assertGreater(m['fuel_J'], base['fuel_J'])  # Reduced pressure is not free energy.

    def test_synthetic_failed_expensive_or_incomparable_candidate_cannot_win(self):
        # Constructed policy-unit counterfactuals, not additional native experiments.
        c = contract()
        observations = self.memory.verify()['observations']
        original = observations['foot_plus_1_percent']
        for fault in ('support_failure', 'energy_budget', 'different_progress', 'no_static_support'):
            receipt = deepcopy(original['receipt'])
            walk = next(r for r in receipt['dynamic'] if r['case'] == 'walk')
            if fault == 'support_failure':
                walk.update(valid_throughout=False, failure='insufficient_joint_or_energy_support',
                            minimum_support_fraction=.5, fuel_used_J=0.)
            elif fault == 'energy_budget':
                walk['fuel_used_J'] *= 2
            elif fault == 'different_progress':
                walk['walk_touchdowns'] += 1
            else:
                receipt['static'][0].update(feasible=False, pressures_kpa={}, achieved_normal_N=0.,
                                            force_error_N=None, moment_error_Nm=None, achieved_cop_m=None)
            synthetic = evidence(c, 'foot_plus_1_percent', receipt, original['source'])
            changed = dict(observations, foot_plus_1_percent=synthetic)
            result = choose(c, changed)
            self.assertEqual(result['chosen'], 'foot_plus_2_percent')
            self.assertEqual(result['candidates']['foot_plus_1_percent']['status'], 'rejected')
            self.assertIsNone(result['candidates']['foot_plus_1_percent']['utility'])

    def test_unknown_context_and_no_evidence_do_not_inherit_a_preference(self):
        c = contract()
        self.assertEqual(choose(c, {})['chosen'], 'baseline')
        changed = dict(c['context'], initial_state='different synthetic body state')
        result = self.memory.recommend(requested_context=changed)
        self.assertEqual(result['chosen'], 'baseline')
        self.assertFalse(result['memory_used'])
        self.assertEqual(result['observations_considered'], [])

    def test_unresolved_intent_survives_restart_and_never_retries_callback(self):
        path = Path(self.temp.name) / 'pending.sqlite'
        m = DesignMemory.create(path)
        portable = Path(self.temp.name) / 'pending.json'
        def interrupted(*args):
            raise RuntimeError('injected unknown callback outcome')
        with self.assertRaises(RuntimeError):
            observe(m, 'foot_plus_1_percent', 'interrupted', runner=interrupted, checkpoint_path=portable)
        cold = DesignMemory.restore(Path(self.temp.name) / 'pending-cold.sqlite', json.loads(portable.read_text()))
        self.assertEqual(cold.verify()['pending'], ['interrupted'])
        self.assertIsNone(cold.recommend()['chosen'])
        calls = []
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            observe(cold, 'foot_plus_1_percent', 'interrupted', runner=lambda *args: calls.append(1))
        with self.assertRaises(ValueError):
            cold.begin('baseline', 'bypass')
        self.assertEqual(calls, [])
        receipt = self.memory.verify()['observations']['foot_plus_1_percent']['receipt']
        cold.finish('interrupted', receipt, fresh_source(contract(), 'interrupted'))
        self.assertEqual(cold.verify()['pending'], [])

    def test_completed_trial_and_decision_replay_do_not_duplicate_learning(self):
        count = self.memory.verify()['events']
        def forbidden(*args):
            self.fail('completed replay invoked simulator')
        result = observe(self.memory, 'foot_plus_1_percent', 'foot-plus-1-fresh', runner=forbidden)
        self.assertEqual(result['native_calls'], 0)
        self.assertTrue(result['cached'])
        again = self.memory.record_choice('after-experience')
        self.assertEqual(again, self.result['after'])
        self.assertEqual(self.memory.verify()['events'], count)
        with self.assertRaises(ValueError):
            self.memory.record_choice('after-experience', use_memory=False)
        with self.assertRaises(ValueError):
            self.memory.begin('baseline', 'foot-plus-1-fresh')

    def test_rehashed_derived_metrics_and_historical_choices_are_rejected(self):
        for field in ('metrics', 'choice'):
            bad = deepcopy(self.saved)
            if field == 'metrics':
                event = next(e for e in bad['payload']['events'] if e['payload']['kind'] == 'trial_finish')
                event['payload']['body']['evidence']['metrics']['fuel_J'] = 0
            else:
                event = next(e for e in bad['payload']['events']
                             if e['payload']['event_id'] == 'choice.after-experience')
                event['payload']['body']['recommendation']['chosen'] = 'cosmetic_only'
            rehash(bad)
            with self.subTest(field=field), self.assertRaises(ValueError):
                DesignMemory.restore(Path(self.temp.name) / (field + '.sqlite'), bad)

    def test_policy_or_source_drift_is_rejected_before_destination_creation(self):
        bad = deepcopy(self.saved)
        bad['payload']['contract']['policy']['weights']['pressure'] = .9
        rehash(bad)
        path = Path(self.temp.name) / 'changed.sqlite'
        with self.assertRaisesRegex(ValueError, 'contract mismatch'):
            DesignMemory.restore(path, bad)
        self.assertFalse(path.exists())
        with self.memory.connection() as db:
            raw = json.loads(db.execute('SELECT value FROM events WHERE seq=1').fetchone()[0])
            raw['sha256'] = '0'*64
            db.execute('UPDATE events SET value=? WHERE seq=1', (json.dumps(raw),))
        with self.assertRaises(ValueError):
            DesignMemory(self.path)

    def test_prior_observation_transfer_requires_an_identical_physical_fixture(self):
        c = contract()
        source, receipt, _ = committed_source('baseline')
        with self.assertRaisesRegex(ValueError, 'identical physical fixture'):
            evidence(c, 'foot_plus_1_percent', receipt, source)
        cosmetic = evidence(c, 'cosmetic_only', receipt, source)
        self.assertEqual(cosmetic['source']['physical_trial_id'],
                         self.memory.verify()['observations']['baseline']['source']['physical_trial_id'])
        self.assertFalse(cosmetic['native_apply_allowed'])

    def test_selected_genotype_stays_a_proposal_and_learning_remains_external(self):
        selected = restore(json.loads((self.output/'recommended-genotype.json').read_text()))
        original = baseline()
        for cid, loci in original['chromosomes'].items():
            for lid, value in loci.items():
                if lid not in ('P07.L010', 'P07.L011'):
                    self.assertEqual(selected['chromosomes'][cid][lid], value)
        self.assertNotIn('experience', selected)
        self.assertFalse(self.result['native_apply_allowed'])
        self.assertFalse(self.result['live_body_advanced'])


if __name__ == '__main__':
    unittest.main()
