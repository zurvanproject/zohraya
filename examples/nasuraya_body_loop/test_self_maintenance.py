"""Offline tests for deterministic self-maintenance and identity persistence."""
import sqlite3
import unittest
from unittest.mock import patch
from .self_maintenance import IdentityContinuity, MaintenanceBlocked, SelfMaintenance, plan, PRINCIPLES


class FakeEngine:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.records = {}

    def get(self, key):
        return self.records.get(key)


class FakeLoop:
    """Nonbiological fixture. The GitHub workflow also runs native body cycles."""
    def __init__(self, *, state=None, max_actions=5, mode='bounded', veto=False):
        self.engine = FakeEngine()
        self.config = {'mode': mode}
        self.n = 0
        self.max_actions = max_actions
        self.sha = 'a' * 64
        self.veto = veto
        self.state = state or dict(energy=.9, fatigue=.1, pain=.1,
                                   balance=.9, sleep_pressure=.1, temperature=37.0)

    def status(self):
        return {'self_model': {'checkpoint_sha256': self.sha},
                'actions_remaining': self.max_actions-self.n, 'unresolved_running': []}

    def observe(self):
        return {'checkpoint_sha256': self.sha, 'minimum_state': dict(self.state)}

    def step(self, *, decision_id, duration_s, preferred_action):
        if self.n >= self.max_actions:
            raise ValueError('budget exhausted')
        self.n += 1
        self.sha = (hex(self.n)[2:] * 64)[:64]
        actual = 'protect' if self.veto and preferred_action == 'walk' else preferred_action
        receipt = {'status': 'complete', 'requested_action': preferred_action,
                   'actual_action': actual, 'expected_outcome_matched': actual == preferred_action,
                   'self_model_after': {'checkpoint_sha256': self.sha}}
        self.engine.records[decision_id] = {'status': 'complete', 'receipt': receipt}
        return receipt

    def receipt(self, record, *, replayed):
        return dict(record['receipt'], replayed=replayed)


class SelfMaintenanceTests(unittest.TestCase):
    def test_healthy_snapshot_prefers_walk(self):
        p = plan(FakeLoop().observe())
        self.assertEqual(p['requested_action'], 'walk')
        self.assertEqual(p['indices']['compute_load_proxy'], .1)
        self.assertIn('not_calibrated_probability', p['confidence_kind'])

    def test_unhealthy_indices_prefer_observation(self):
        for variable, value in [('energy', .2), ('fatigue', .8), ('balance', .2),
                                ('sleep_pressure', .9), ('pain', .8), ('temperature', 40.)]:
            loop = FakeLoop(state={**FakeLoop().state, variable: value})
            with self.subTest(variable=variable):
                self.assertEqual(plan(loop.observe())['requested_action'], 'observe')

    def test_invalid_indices_refuse_decision(self):
        for value in (-.1, 1.1, None, float('nan'), True):
            state = {**FakeLoop().state, 'energy': value}
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan(FakeLoop(state=state).observe())

    def test_native_veto_feedback_changes_next_preference(self):
        loop = FakeLoop(veto=True)
        result = SelfMaintenance(loop, goal_id='first', target_cycles=2).run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([(x['requested_action'], x['actual_action']) for x in result['history']],
                         [('walk', 'protect'), ('observe', 'observe')])
        self.assertIn('remembered_motion_veto', result['history'][1]['reason_codes'])

    def test_restart_recovers_committed_effect_without_duplicate(self):
        loop = FakeLoop()
        original = SelfMaintenance(loop, goal_id='long', target_cycles=2)
        real_step = loop.step
        def interruption(**kwargs):
            real_step(**kwargs)
            raise RuntimeError('process stopped after native commit')
        with patch.object(loop, 'step', side_effect=interruption):
            with self.assertRaises(RuntimeError):
                original.run()
        self.assertEqual(loop.n, 1)
        resumed = SelfMaintenance(loop, goal_id='long', target_cycles=2).run()
        self.assertEqual(resumed['completed_cycles'], 2)
        self.assertEqual(loop.n, 2)
        again = SelfMaintenance(loop, goal_id='long', target_cycles=2).run()
        self.assertEqual(again['completed_cycles'], 2)
        self.assertEqual(loop.n, 2)

    def test_unknown_result_blocks_retry(self):
        loop = FakeLoop()
        controller = SelfMaintenance(loop, goal_id='uncertain', target_cycles=2)
        with patch.object(loop, 'step', side_effect=RuntimeError('uncertain result')):
            with self.assertRaises(RuntimeError): controller.run()
        with self.assertRaisesRegex(MaintenanceBlocked, 'uncertain pending'):
            SelfMaintenance(loop, goal_id='uncertain', target_cycles=2).run()
        self.assertEqual(loop.n, 0)

    def test_goal_contract_budget_and_observe_mode(self):
        loop = FakeLoop(max_actions=1)
        controller = SelfMaintenance(loop, goal_id='limit', target_cycles=2)
        with self.assertRaisesRegex(MaintenanceBlocked, 'budget'): controller.run()
        self.assertEqual(loop.n, 1)
        with self.assertRaisesRegex(MaintenanceBlocked, 'target changed'):
            SelfMaintenance(loop, goal_id='limit', target_cycles=1)
        with self.assertRaisesRegex(MaintenanceBlocked, 'observe-only'):
            SelfMaintenance(FakeLoop(mode='observe'), goal_id='readonly', target_cycles=1)

    def test_identity_versioning_revert_and_fixed_constitution(self):
        db = sqlite3.connect(':memory:', isolation_level=None)
        identity = IdentityContinuity(db)
        identity.revise_belief('weather', 'unknown', reason='record a test belief', evidence='fixture://weather/initial')
        self.assertEqual(identity.verify()['beliefs']['weather'], 'unknown')
        identity.revert_to(1, reason='fixture correction', evidence='fixture://weather/reviewed')
        self.assertEqual(identity.verify()['beliefs'], {})
        self.assertEqual(identity.verify()['principles'], list(PRINCIPLES))
        with self.assertRaises(MaintenanceBlocked):
            identity.revise_belief('principles', False, reason='bad core attempt', evidence='fixture://blocked/test')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM nasu_identity_versions').fetchone()[0], 3)

    def test_identity_hash_chain_detects_accidental_corruption(self):
        db = sqlite3.connect(':memory:', isolation_level=None)
        identity = IdentityContinuity(db)
        db.execute('UPDATE nasu_identity_versions SET rationale=? WHERE version=1', ('forged',))
        with self.assertRaisesRegex(MaintenanceBlocked, 'verification failed'): identity.verify()

    def test_tampered_maintenance_receipt_is_detected(self):
        loop = FakeLoop()
        maintenance = SelfMaintenance(loop, goal_id='tamper', target_cycles=1)
        maintenance.run()
        loop.engine.db.execute(
            "UPDATE nasu_maintenance_steps SET after_sha=? WHERE goal_id=?",
            ('0'*64, 'tamper'))
        with self.assertRaisesRegex(MaintenanceBlocked, 'conflicts'):
            maintenance.status()


if __name__ == '__main__':
    unittest.main()
