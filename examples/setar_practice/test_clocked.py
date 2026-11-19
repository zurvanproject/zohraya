"""Contract tests: declared body double plus actual synthetic audio engine."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .body_bridge import BIND, RUN, encode
from .clocked import ClockedAudio, ClockedSetarBridge, CURSOR, TOTAL_SAMPLES
from . import engine as e
from .skill import SetarSkill
from .test_body_bridge import DeclaredBodyDouble


class ClockBodyDouble(DeclaredBodyDouble):
    def __init__(self, path):
        super().__init__(path)
        self.max_actions = 100
        self.elapsed, self.durations = 0., []
        self.tire_at, self.drift = None, 0.
        row = self.engine.db.execute("SELECT value FROM meta WHERE key='test-clock'").fetchone()
        if row:
            self.elapsed, self.calls = json.loads(row[0])

    def observe(self):
        result = super().observe()
        result['simulated_wall_utc'] = (datetime(2026, 1, 1) + timedelta(seconds=self.elapsed)).isoformat()
        return result

    def step(self, **kwargs):
        self.elapsed += kwargs['duration_s'] + self.drift
        self.durations.append(kwargs['duration_s'])
        if self.tire_at == self.calls + 1:
            self.minimum['fatigue'] = .99
        result = super().step(**kwargs)
        result['replayed'] = False
        self.engine.db.execute("INSERT OR REPLACE INTO meta VALUES('test-clock', ?)",
            (encode([self.elapsed, self.calls]),))
        return result


class ClockedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.loop = ClockBodyDouble(self.root / 'body.sqlite')
        self.bridge = ClockedSetarBridge(self.loop)
        self.bridge.bind(max_steps=10)

    def tearDown(self):
        self.loop.close()
        self.temp.cleanup()

    def run_lesson(self, name='one', **kwargs):
        return self.bridge.lesson(name, self.root / name, realtime=False, **kwargs)

    def test_complete_matches_entire_audio_duration(self):
        result = self.run_lesson()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['native_cycles_caused'], 12)
        self.assertAlmostEqual(sum(self.loop.durations), 11.2)
        self.assertEqual(result['body_elapsed_seconds'], 11.2)
        self.assertEqual(result['audio']['duration_s'], 11.2)
        self.assertEqual(result['clock_residual_seconds'], 0.)
        self.assertEqual(result['total_updates'], 2878)
        self.assertEqual(result['next_curriculum_index'], 1)
        self.assertFalse(result['ten_minutes_wall_clock_verified'])

    def test_feedback_waits_until_full_note_window_is_available(self):
        self.run_lesson()
        rows = [json.loads(x) for x in (self.root / 'one' / 'events.jsonl').read_text().splitlines()]
        self.assertEqual([x['sample'] for x in rows], sorted(x['sample'] for x in rows))
        for row in rows:
            if row['kind'] == 'feedback':
                self.assertEqual(row['sample'] - row['rendered_at_sample'], round(e.NOTE_S * e.SR))
        self.assertEqual(sum(x['kind'] == 'feedback' for x in rows), 18)

    def test_reopen_advances_to_different_exercise_without_losing_memory(self):
        first = self.run_lesson()
        self.loop.close()
        self.loop = ClockBodyDouble(self.root / 'body.sqlite')
        self.bridge = ClockedSetarBridge(self.loop)
        second = self.run_lesson('two')
        self.assertEqual(second['curriculum_index'], 1)
        self.assertEqual(second['total_updates'], first['total_updates'] + 18)
        self.assertEqual(self.bridge.status()[CURSOR], 2)
        def first_note(name):
            return json.loads((self.root / name / 'events.jsonl').read_text().splitlines()[0])['event']
        self.assertNotEqual(first_note('one')['semitones'], first_note('two')['semitones'])

    def test_replay_is_read_only_and_conflicting_mode_rejected(self):
        self.run_lesson()
        count = self.loop.calls
        replay = self.run_lesson()
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.loop.calls, count)
        with self.assertRaises(ValueError):
            self.bridge.lesson('one', self.root / 'one', realtime=True)
        with self.assertRaises(ValueError):
            self.bridge.step('one', self.root / 'one', realtime=False)

    def test_insufficient_budget_is_rejected_before_reservation(self):
        self.loop.max_actions = 11
        with self.assertRaises(ValueError):
            self.run_lesson()
        self.assertEqual(self.bridge.status()['attempts_reserved'], 0)
        self.assertEqual(self.loop.calls, 0)
        self.assertFalse((self.root / 'one').exists())

    def test_initial_sleep_stops_without_audio_or_updates(self):
        self.loop.minimum['sleep_pressure'] = .95
        before = self.bridge._read(BIND)
        result = self.run_lesson()
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(result['native_cycles_caused'], 0)
        self.assertEqual(result['approved_audio_seconds'], 0.)
        self.assertEqual(before, self.bridge._read(BIND))

    def test_mid_lesson_gate_preserves_committed_memory_and_cursor(self):
        before = self.bridge._read(BIND)
        self.loop.tire_at = 3
        result = self.run_lesson()
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(result['body_elapsed_seconds'], 3.)
        self.assertEqual(result['approved_audio_seconds'], 2.)
        self.assertEqual(result['audio']['duration_s'], 2.)
        self.assertFalse(result['blockwise_clock_aligned'])
        self.assertGreater(result['provisional_updates'], 0)
        self.assertEqual(before, self.bridge._read(BIND))
        self.assertFalse((self.root / 'one' / 'checkpoint.json').exists())
        self.assertTrue(self.run_lesson()['replayed'])
        self.assertEqual(self.loop.calls, 3)

    def test_clock_drift_fails_without_committing_progress(self):
        before = self.bridge._read(BIND)
        self.loop.drift = .1
        with self.assertRaises(RuntimeError):
            self.run_lesson()
        self.assertEqual(before, self.bridge._read(BIND))
        self.assertEqual(self.bridge._read(RUN + 'one')['state'], 'failed_or_interrupted')

    def test_interruption_cannot_publish_partial_training(self):
        before = self.bridge._read(BIND)
        with patch.object(e, 'render_observe', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_lesson()
        self.assertEqual(before, self.bridge._read(BIND))
        self.assertEqual(self.run_lesson()['state'], 'failed_or_interrupted')
        self.assertEqual(self.loop.calls, 1)

    def test_database_commit_failure_rolls_back_skill_and_cursor(self):
        before = self.bridge._read(BIND)
        original = self.bridge._write
        def fail_commit(key, value):
            if key == RUN + 'one' and value['state'] == 'completed':
                raise OSError('injected ledger failure')
            return original(key, value)
        with patch.object(self.bridge, '_write', fail_commit):
            with self.assertRaises(OSError):
                self.run_lesson()
        self.assertEqual(before, self.bridge._read(BIND))
        self.assertFalse(self.bridge._read(RUN + 'one')['checkpoint_committed'])

    def test_receipt_export_failure_does_not_undo_completed_commit(self):
        from . import clocked
        original = clocked.atomic_json
        def fail_export(path, value):
            if path.name == 'bridge_receipt.json':
                raise OSError('injected export failure')
            return original(path, value)
        with patch.object(clocked, 'atomic_json', fail_export):
            result = self.run_lesson()
        self.assertEqual(result['state'], 'completed')
        self.assertFalse(result['receipt_copy_written'])
        self.assertEqual(self.bridge.status()[CURSOR], 1)
        self.assertTrue(self.run_lesson()['replayed'])

    def test_course_end_and_invalid_cursor_do_not_wrap(self):
        for index in (60, -1, True, 1.2):
            binding = self.bridge._read(BIND)
            binding[CURSOR] = index
            self.bridge._write(BIND, binding)
            with self.assertRaises(ValueError):
                self.run_lesson()
        self.assertEqual(self.loop.calls, 0)

    def test_pending_work_blocks_new_lessons(self):
        self.bridge._write(RUN + 'lost', {'run_id': 'lost', 'state': 'running'})
        with self.assertRaises(RuntimeError):
            self.run_lesson()
        self.assertEqual(self.loop.calls, 0)

    def test_evaluation_does_not_advance_curriculum(self):
        before = self.bridge._read(BIND)
        self.bridge.evaluate()
        self.assertEqual(before, self.bridge._read(BIND))
        self.assertEqual(self.loop.calls, 0)

    def test_invalid_inputs_do_not_reserve_work(self):
        for run_id, realtime, seed in [('../x', False, 1), ('x', 1, 1), ('x', False, True), ('x', False, -1)]:
            with self.assertRaises(ValueError):
                self.bridge.lesson(run_id, self.root / 'out', realtime=realtime, seed=seed)
        with self.assertRaises(ValueError):
            self.bridge.lesson('exists', self.root, realtime=False)
        self.assertEqual(self.bridge.status()['attempts_reserved'], 0)

    def test_read_only_body_blocks_lessons(self):
        self.loop.mode = 'observe'
        with self.assertRaises(ValueError):
            self.run_lesson()
        self.assertEqual(self.loop.calls, 0)

    def test_native_protect_cannot_start_audio(self):
        self.loop.action = 'protect'
        result = self.run_lesson()
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(result['note_events'], 0)
        self.assertEqual(self.bridge.status()['total_updates'], 2860)

    def test_clock_rejects_nonmonotonic_steps(self):
        audio = ClockedAudio(SetarSkill().controller, 0, 1)
        for end in (0, -1, True, TOTAL_SAMPLES + 1):
            with self.assertRaises(ValueError):
                audio.advance(end, pace=lambda _: None)

    def test_new_curriculum_reaches_next_stage(self):
        binding = self.bridge._read(BIND)
        binding[CURSOR] = 10  # Explicit test fixture, not earned advancement.
        self.bridge._write(BIND, binding)
        result = self.run_lesson()
        self.assertEqual(result['stage'], 'new_calibration_nodes')
        self.assertEqual(result['note_events'], 22)
        self.assertEqual(result['next_curriculum_index'], 11)


if __name__ == '__main__':
    unittest.main()
