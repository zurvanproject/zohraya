"""Contract tests use a declared BodyLoop double plus the real audio engine.

These tests alone do not establish native-body execution. See test_body_native.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

from .body_bridge import BIND, RUN, SetarBodyBridge, readiness


class DeclaredBodyDouble:
    def __init__(self, path):
        self.engine = types.SimpleNamespace(db=sqlite3.connect(path, isolation_level=None))
        self.engine.db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
        self.mode, self.calls, self.max_actions = 'bounded', 0, 10
        self.unresolved, self.action = [], 'observe'
        self.minimum = dict(energy=.9, hydration=.9, fatigue=.1, pain=0., sleep_pressure=.1)

    def status(self):
        return dict(mode=self.mode, unresolved_running=self.unresolved,
                    actions_remaining=self.max_actions - self.calls)

    def observe(self):
        return dict(checkpoint_sha256='a' * 64, revision=self.calls,
                    minimum_state=deepcopy(self.minimum))

    def step(self, **kwargs):
        self.calls += 1
        return dict(status='complete', requested_action='observe', actual_action=self.action,
                    self_model_after=self.observe(), decision_id=kwargs['decision_id'])

    def close(self):
        self.engine.db.close()


class BridgeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.loop = DeclaredBodyDouble(self.root / 'body.sqlite')
        self.bridge = SetarBodyBridge(self.loop)

    def tearDown(self):
        self.loop.close()
        self.temp.cleanup()

    def bound(self, n=3):
        self.bridge.bind(max_steps=n)
        return self.bridge

    def test_initially_unbound_and_no_implicit_binding(self):
        self.assertFalse(self.bridge.status()['bound'])
        with self.assertRaises(ValueError):
            self.bridge.step('one', self.root / 'out', realtime=False)
        self.assertEqual(self.loop.calls, 0)

    def test_binding_preserves_seed_and_cannot_reset(self):
        self.bound()
        self.assertEqual(self.bridge.status()['total_updates'], 2860)
        with self.assertRaises(ValueError):
            self.bridge.bind(max_steps=99)

    def test_one_step_real_audio_and_atomic_memory(self):
        self.bound()
        result = self.bridge.step('one', self.root / 'out', realtime=False)
        self.assertEqual(result['state'], 'completed')
        self.assertTrue(result['checkpoint_committed'])
        self.assertEqual(result['summary']['inherited_updates'], 2860)
        self.assertGreater(result['summary']['new_updates'], 0)
        self.assertEqual(self.bridge.status()['total_updates'], result['summary']['total_updates'])
        self.assertTrue((self.root / 'out' / 'practice' / 'practice.wav').is_file())
        self.assertEqual(self.loop.calls, 1)

    def test_replay_has_no_native_or_training_effect(self):
        self.bound()
        first = self.bridge.step('one', self.root / 'out', realtime=False)
        replay = self.bridge.step('one', self.root / 'out', realtime=False)
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['summary'], replay['summary'])
        self.assertEqual(self.loop.calls, 1)

    def test_conflicting_replay_rejected(self):
        self.bound()
        self.bridge.step('one', self.root / 'out', realtime=False)
        with self.assertRaises(ValueError):
            self.bridge.step('one', self.root / 'out', realtime=False, seed=17)
        self.assertEqual(self.loop.calls, 1)

    def test_cold_reload_keeps_progress_and_budget(self):
        self.bound(1)
        result = self.bridge.step('one', self.root / 'out', realtime=False)
        self.loop.close()
        self.loop = DeclaredBodyDouble(self.root / 'body.sqlite')
        self.bridge = SetarBodyBridge(self.loop)
        self.assertEqual(self.bridge.status()['total_updates'], result['summary']['total_updates'])
        self.assertTrue(self.bridge.step('one', self.root / 'out', realtime=False)['replayed'])
        with self.assertRaises(ValueError):
            self.bridge.step('two', self.root / 'new', realtime=False)
        self.assertEqual(self.loop.calls, 0)

    def test_sleep_gate_defers_without_training(self):
        self.bound()
        self.loop.minimum['sleep_pressure'] = .95
        before = self.bridge._read(BIND)
        result = self.bridge.step('sleep', self.root / 'out', realtime=False)
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(self.bridge._read(BIND), before)
        self.assertEqual(self.loop.calls, 0)
        self.assertFalse((self.root / 'out' / 'practice').exists())

    def test_unknown_nonfinite_and_bool_state_fail_closed(self):
        for value in (None, float('nan'), float('inf'), True, -1., 1.1):
            snapshot = self.loop.observe()
            snapshot['minimum_state']['fatigue'] = value
            self.assertFalse(readiness(snapshot)['allowed'])

    def test_native_veto_defers_without_training(self):
        self.bound()
        self.loop.action = 'protect'
        result = self.bridge.step('protect', self.root / 'out', realtime=False)
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(self.bridge.status()['total_updates'], 2860)
        self.assertEqual(self.loop.calls, 1)

    def test_postcycle_state_is_checked(self):
        self.bound()
        original = self.loop.step
        def tired(**kwargs):
            result = original(**kwargs)
            result['self_model_after']['minimum_state']['fatigue'] = .99
            return result
        with patch.object(self.loop, 'step', tired):
            result = self.bridge.step('tired', self.root / 'out', realtime=False)
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(self.bridge.status()['total_updates'], 2860)

    def test_read_only_body_rejects_binding_and_step(self):
        self.loop.mode = 'observe'
        with self.assertRaises(ValueError):
            self.bridge.bind()
        self.loop.mode = 'bounded'
        self.bound()
        self.loop.mode = 'observe'
        with self.assertRaises(ValueError):
            self.bridge.step('one', self.root / 'out', realtime=False)

    def test_native_budget_and_unresolved_execution_rejected(self):
        self.bound()
        self.loop.max_actions = 0
        with self.assertRaises(ValueError):
            self.bridge.step('one', self.root / 'out', realtime=False)
        self.loop.max_actions = 10
        self.loop.unresolved = ['other-native-work']
        with self.assertRaises(ValueError):
            self.bridge.step('two', self.root / 'out', realtime=False)
        self.assertEqual(self.bridge.status()['attempts_reserved'], 0)

    def test_pending_run_blocks_automatic_retry_and_new_work(self):
        self.bound()
        self.bridge._write(RUN + 'crash', {'run_id': 'crash', 'state': 'running'})
        with self.assertRaises(RuntimeError):
            self.bridge.step('other', self.root / 'out', realtime=False)
        self.assertEqual(self.loop.calls, 0)

    def test_interruption_does_not_advance_checkpoint_or_replay(self):
        self.bound()
        before = self.bridge._read(BIND)
        with patch('examples.setar_practice.body_bridge.SetarSkill.practice', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.bridge.step('interrupted', self.root / 'out', realtime=False)
        self.assertEqual(self.bridge._read(BIND), before)
        replay = self.bridge.step('interrupted', self.root / 'out', realtime=False)
        self.assertEqual(replay['state'], 'failed_or_interrupted')
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.loop.calls, 1)

    def test_invalid_inputs_and_existing_output_do_not_consume_budget(self):
        self.bound()
        for kwargs in ({'run_id': '../bad', 'realtime': False},
                       {'run_id': 'valid', 'realtime': 1},
                       {'run_id': 'valid', 'realtime': False, 'seed': True}):
            with self.assertRaises(ValueError):
                self.bridge.step(output=self.root / 'out', **kwargs)
        with self.assertRaises(ValueError):
            self.bridge.step('existing', self.root, realtime=False)
        self.assertEqual(self.bridge.status()['attempts_reserved'], 0)

    def test_evaluation_is_read_only_for_body_and_skill(self):
        self.bound()
        before = self.bridge._read(BIND)
        result = self.bridge.evaluate()
        self.assertTrue(result['binding_unchanged'])
        self.assertEqual(self.bridge._read(BIND), before)
        self.assertEqual(self.loop.calls, 0)

    def test_two_steps_inherit_exactly_once(self):
        self.bound()
        first = self.bridge.step('one', self.root / 'one', realtime=False)
        second = self.bridge.step('two', self.root / 'two', realtime=False)
        self.assertEqual(second['summary']['inherited_updates'], first['summary']['total_updates'])
        self.assertEqual(second['summary']['total_updates'], 2860 + first['summary']['new_updates'] + second['summary']['new_updates'])


if __name__ == '__main__':
    unittest.main()
