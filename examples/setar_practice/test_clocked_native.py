"""Run via body_cli test inside the verified original body runtime."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from examples.nasuraya_body_loop.host import BodyLoop
from .clocked import ClockedSetarBridge, CURSOR
from .body_bridge import BIND


class NativeClockedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'body.sqlite'

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_body_clock_and_cold_curriculum_continuation(self):
        with BodyLoop.start(self.path, fixture='normal', max_actions=24) as loop:
            bridge = ClockedSetarBridge(loop)
            bridge.bind(max_steps=2)
            origin = loop.status()['self_model']['simulated_wall_utc']
            first = bridge.lesson('one', self.root / 'one', realtime=False)
            self.assertEqual(first['state'], 'completed', first)
            self.assertEqual(first['clock_residual_seconds'], 0.)
            self.assertEqual(first['body_elapsed_seconds'], 11.2)
            self.assertEqual(loop.status()['completed_cycles'], 12)
        with BodyLoop(self.path) as loop:
            bridge = ClockedSetarBridge(loop)
            self.assertTrue(bridge.lesson('one', self.root / 'one', realtime=False)['replayed'])
            self.assertEqual(loop.status()['completed_cycles'], 12)
            second = bridge.lesson('two', self.root / 'two', realtime=False)
            self.assertEqual(second['state'], 'completed', second)
            self.assertEqual(second['curriculum_index'], 1)
            self.assertEqual(bridge.status()[CURSOR], 2)
            self.assertEqual(loop.status()['completed_cycles'], 24)
            end = loop.status()['self_model']['simulated_wall_utc']
            elapsed = (datetime.fromisoformat(end) - datetime.fromisoformat(origin)).total_seconds()
            self.assertEqual(elapsed, 22.4)
            print('NATIVE_CLOCKED_EVIDENCE=' + json.dumps(dict(
                native_cycles=24, body_elapsed_seconds=elapsed,
                audio_seconds=first['audio']['duration_s'] + second['audio']['duration_s'],
                lessons=[first['curriculum_index'], second['curriculum_index']],
                total_updates=bridge.status()['total_updates'], cold_replay_no_new_cycles=True,
                physical_hand_control=False, accelerated=True)))

    def test_native_sleep_and_insufficient_budget(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=12) as loop:
            bridge = ClockedSetarBridge(loop)
            bridge.bind()
            result = bridge.lesson('sleep', self.root / 'sleep', realtime=False)
            self.assertEqual(result['state'], 'deferred')
            self.assertEqual(loop.status()['completed_cycles'], 0)
        path2 = self.root / 'small.sqlite'
        with BodyLoop.start(path2, max_actions=11) as loop:
            bridge = ClockedSetarBridge(loop)
            bridge.bind()
            with self.assertRaises(ValueError):
                bridge.lesson('small', self.root / 'small', realtime=False)
            self.assertEqual(loop.status()['completed_cycles'], 0)

    def test_mid_lesson_interruption_keeps_committed_native_effects_only(self):
        with BodyLoop.start(self.path, max_actions=12) as loop:
            bridge = ClockedSetarBridge(loop)
            bridge.bind()
            before = bridge._read(BIND)
            original = loop.observe
            calls = 0
            def interrupt_after_two_windows():
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise KeyboardInterrupt('injected interruption')
                return original()
            with patch.object(loop, 'observe', interrupt_after_two_windows):
                with self.assertRaises(KeyboardInterrupt):
                    bridge.lesson('cut', self.root / 'cut', realtime=False)
            self.assertEqual(loop.status()['completed_cycles'], 2)
            self.assertEqual(bridge._read(BIND), before)
            self.assertEqual(bridge.lesson('cut', self.root / 'cut', realtime=False)['state'], 'failed_or_interrupted')
            self.assertEqual(loop.status()['completed_cycles'], 2)
            print('NATIVE_CLOCKED_INTERRUPTION=' + json.dumps(dict(
                committed_native_cycles=2, skill_unchanged=True, curriculum_unchanged=True,
                replay_caused_new_cycles=False)))
