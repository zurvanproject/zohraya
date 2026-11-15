"""Native tests: only run via body_cli test in the verified isolated runtime."""
from pathlib import Path
import json
import tempfile
import unittest
from examples.nasuraya_body_loop.host import BodyLoop
from .body_bridge import SetarBodyBridge


class NativeSetarBodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'body.sqlite'

    def tearDown(self):
        self.temp.cleanup()

    def test_real_body_cycle_audio_checkpoint_and_cold_replay(self):
        with BodyLoop.start(self.path, fixture='normal', max_actions=3) as loop:
            bridge = SetarBodyBridge(loop)
            bridge.bind(max_steps=2)
            result = bridge.step('one', self.root / 'one', realtime=False)
            self.assertEqual(result['state'], 'completed', result)
            self.assertEqual(result['native_receipt']['actual_action'], 'observe')
            self.assertEqual(loop.status()['completed_cycles'], 1)
            total = bridge.status()['total_updates']
        with BodyLoop(self.path) as loop:
            bridge = SetarBodyBridge(loop)
            self.assertEqual(bridge.status()['total_updates'], total)
            replay = bridge.step('one', self.root / 'one', realtime=False)
            self.assertTrue(replay['replayed'])
            self.assertEqual(loop.status()['completed_cycles'], 1)
            second = bridge.step('two', self.root / 'two', realtime=False)
            self.assertEqual(second['state'], 'completed', second)
            self.assertEqual(second['summary']['inherited_updates'], total)
            self.assertEqual(loop.status()['completed_cycles'], 2)
            self.assertLess(abs(second['native_receipt']['body_audit']['energy_error_J']), 1e-6)
            print('NATIVE_SETAR_EVIDENCE=' + json.dumps({
                'state': second['state'], 'native_action': second['native_receipt']['actual_action'],
                'initial_updates': 2860, 'after_first': total,
                'after_second': bridge.status()['total_updates'],
                'native_cycles': loop.status()['completed_cycles'],
                'cold_replay_did_not_execute': replay['replayed'],
                'energy_error_J': second['native_receipt']['body_audit']['energy_error_J'],
                'physical_hand_control': False}))

    def test_real_sleep_fixture_blocks_practice(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=3) as loop:
            bridge = SetarBodyBridge(loop)
            bridge.bind()
            result = bridge.step('sleep', self.root / 'sleep', realtime=False)
            self.assertEqual(result['state'], 'deferred', result)
            self.assertEqual(bridge.status()['total_updates'], 2860)
            self.assertEqual(loop.status()['completed_cycles'], 0)
            self.assertIn('sleep_pressure', result['readiness_before']['reasons'])
            print('NATIVE_SLEEP_EVIDENCE=' + json.dumps({
                'state': result['state'], 'reasons': result['readiness_before']['reasons'],
                'total_updates': bridge.status()['total_updates'],
                'native_cycles': loop.status()['completed_cycles']}))

    def test_real_observe_only_body_cannot_bind(self):
        with BodyLoop.start(self.path, mode='observe', max_actions=0) as loop:
            with self.assertRaises(ValueError):
                SetarBodyBridge(loop).bind()

    def test_real_native_budget_survives_reopen(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            bridge = SetarBodyBridge(loop)
            bridge.bind(max_steps=3)
            result = bridge.step('one', self.root / 'one', realtime=False)
            self.assertEqual(result['state'], 'completed', result)
        with BodyLoop(self.path) as loop:
            bridge = SetarBodyBridge(loop)
            with self.assertRaises(ValueError):
                bridge.step('two', self.root / 'two', realtime=False)
            self.assertEqual(loop.status()['actions_remaining'], 0)

    def test_real_evaluation_does_not_change_body_checkpoint(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            bridge = SetarBodyBridge(loop)
            bridge.bind()
            before = loop.status()['self_model']['checkpoint_sha256']
            result = bridge.evaluate()
            self.assertTrue(result['binding_unchanged'])
            self.assertEqual(loop.status()['self_model']['checkpoint_sha256'], before)
            self.assertEqual(loop.status()['completed_cycles'], 0)
