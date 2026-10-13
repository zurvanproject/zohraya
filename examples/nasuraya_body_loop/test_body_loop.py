"""Behavioral checks of the new bridge, run inside the verified source worker."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .host import BodyLoop, InterruptedExecution, UnifiedBody
from . import worker
from reflection_cycle import ReflectionCycle


class BodyLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.sqlite'

    def tearDown(self): self.temp.cleanup()

    def test_source_pinned_body_feedback_changes_next_requested_action(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=3) as loop:
            observation = loop.observe()
            self.assertGreater(observation['minimum_state']['sleep_pressure'], .65)
            first = loop.step()
            self.assertEqual((first['requested_action'], first['actual_action']), ('walk', 'protect'))
            self.assertFalse(first['expected_outcome_matched'])
            loop.observe()
            second = loop.step()
            self.assertEqual((second['requested_action'], second['actual_action']), ('observe', 'observe'))
            self.assertTrue(second['expected_outcome_matched'])
            self.assertIn(first['decision_id'], second['recalled_feedback_ids'])
            for result in [first, second]:
                audit = result['body_audit']
                self.assertLess(abs(audit['energy_error_J']), 1e-6)
                self.assertLess(abs(audit['water_error_L']), 1e-9)
                self.assertTrue(audit['same_owner_ticks'])

    def test_fresh_observation_required_and_consumed(self):
        with BodyLoop.start(self.path, max_actions=3) as loop:
            before = loop.status()['self_model']['checkpoint_sha256']
            with self.assertRaisesRegex(ValueError, 'fresh observe'): loop.step()
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])
            loop.observe(); loop.step()
            with self.assertRaisesRegex(ValueError, 'fresh observe'): loop.step()
            self.assertEqual(loop.status()['completed_cycles'], 1)

    def test_observe_mode_never_mutates_body(self):
        with BodyLoop.start(self.path, mode='observe') as loop:
            before = loop.observe()['checkpoint_sha256']
            with self.assertRaisesRegex(ValueError, 'disabled'): loop.step()
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])
            self.assertEqual(loop.status()['actions_reserved'], 0)

    def test_budget_survives_reopen(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            loop.observe(); loop.step()
        with BodyLoop(self.path) as loop:
            before = loop.observe()['checkpoint_sha256']
            with self.assertRaisesRegex(ValueError, 'budget exhausted'): loop.step()
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])
            self.assertEqual(loop.status()['actions_remaining'], 0)

    def test_completed_replay_does_not_repeat_body_effect(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            loop.observe(); first = loop.step(decision_id='first')
            loop.observe(); loop.step(decision_id='second')
            before = loop.status()['self_model']['checkpoint_sha256']
            replay = loop.step(decision_id='first')
            self.assertTrue(replay['replayed'])
            self.assertEqual(replay['self_model_after'], first['self_model_after'])
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])
            self.assertEqual(loop.status()['completed_cycles'], 2)
            with self.assertRaisesRegex(ValueError, 'conflicting'): loop.step(decision_id='first', duration_s=.2)

    def test_cold_process_recalls_the_actual_body_veto(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=2) as loop:
            loop.observe(); first = loop.step()
        code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
with BodyLoop(sys.argv[1]) as loop:
 loop.observe()
 print(json.dumps(loop.step()))
'''
        proc = subprocess.run([sys.executable, '-c', code, str(self.path)], capture_output=True, text=True, check=True)
        result = json.loads(proc.stdout)
        self.assertEqual(result['requested_action'], 'observe')
        self.assertIn(first['decision_id'], result['recalled_feedback_ids'])

    def test_concurrent_writer_is_rejected(self):
        with BodyLoop.start(self.path):
            with self.assertRaises(BlockingIOError): BodyLoop(self.path)

    def test_existing_session_is_never_reset(self):
        with BodyLoop.start(self.path) as loop:
            loop.observe(); loop.step()
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError): BodyLoop.start(self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_unrelated_old_ledger_is_rejected_without_migration(self):
        with ReflectionCycle(self.path) as engine:
            engine.db.execute("UPDATE meta SET value='old-index-version' WHERE key='feedback_index_version'")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'original ledger left unchanged'):
            BodyLoop(self.path)
        self.assertEqual(before, self.path.read_bytes())

    def test_unresolved_operation_blocks_all_new_execution(self):
        with BodyLoop.start(self.path) as loop:
            snapshot = loop.observe()
            request = loop.make_request('interrupted', snapshot, .1)
            request['execution'] = dict(runtime_key='nasuraya-body-loop', at_utc=request['at_utc'], duration_s=.1, external={})
            record = loop.engine.decide(request)
            record['status'] = 'running'
            loop.engine.db.execute('UPDATE decisions SET status=?,record=? WHERE id=?', ('running', json.dumps(record), record['id']))
            before = loop.status()['self_model']['checkpoint_sha256']
            with self.assertRaises(InterruptedExecution): loop.step(decision_id='new-attempt')
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])

    def test_tampered_body_observation_is_rejected(self):
        with BodyLoop.start(self.path) as loop:
            snapshot = loop.observe()
            snapshot['checkpoint_sha256'] = '0' * 64
            loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(snapshot), 'body-loop-observation'))
            with self.assertRaisesRegex(ValueError, 'stale'): loop.step()
            self.assertEqual(loop.status()['actions_reserved'], 0)

    def test_invalid_duration_and_identity_preserve_observation_and_budget(self):
        with BodyLoop.start(self.path) as loop:
            before = loop.observe()['checkpoint_sha256']
            for value in (.001, .05, .15, 1.1, float('nan'), float('inf'), True):
                with self.subTest(duration=value), self.assertRaises(ValueError):
                    loop.step(duration_s=value)
            for value in ('', ' ', 'x' * 110, 3):
                with self.subTest(identity=value), self.assertRaises(ValueError):
                    loop.step(decision_id=value)
            self.assertEqual(loop.status()['actions_reserved'], 0)
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])
            self.assertEqual(loop.step(duration_s=.3)['status'], 'complete')

    def test_callback_failure_is_not_a_completed_cycle_and_replay_never_retries(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            before = loop.observe()['checkpoint_sha256']
            with patch.object(UnifiedBody, 'cycle', side_effect=RuntimeError('PRIVATE-SENTINEL')) as callback:
                first = loop.step(decision_id='failed')
                second = loop.step(decision_id='failed')
            self.assertEqual(callback.call_count, 1)
            self.assertEqual(first['status'], 'executor_failed')
            self.assertTrue(second['replayed'])
            self.assertEqual(loop.status()['completed_cycles'], 0)
            self.assertEqual(loop.status()['failed_cycles'], 1)
            self.assertEqual(loop.status()['actions_remaining'], 0)
            self.assertEqual(before, loop.status()['self_model']['checkpoint_sha256'])
            self.assertNotIn('PRIVATE-SENTINEL', json.dumps(loop.engine.export()))

    def test_failed_demo_exits_nonzero_and_retains_failed_receipt(self):
        output = Path(self.temp.name) / 'demo'
        args = dict(command='demo', output_dir=str(output), steps=2, max_actions=2,
                    fixture='normal', mode='bounded', duration_s=.1)
        # Patch the adapter after fixture creation, not the native warm-up.
        from reflection_cycle import ReflectiveBody
        original = ReflectiveBody.cycle
        def fail_body(adapter, *args, **kwargs):
            with patch.object(UnifiedBody, 'cycle', side_effect=RuntimeError('PRIVATE-SENTINEL')):
                return original(adapter, *args, **kwargs)
        with patch.object(ReflectiveBody, 'cycle', fail_body), redirect_stdout(io.StringIO()):
            code = worker.main(args)
        summary = json.loads((output / 'summary.json').read_text())
        self.assertEqual(code, 1)
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['completed_cycles'], 0)
        self.assertEqual(summary['failed_cycles'], 1)
        self.assertEqual(summary['actions_reserved'], 1)
        self.assertEqual(len((output / 'events.jsonl').read_text().splitlines()), 1)
        self.assertNotIn('PRIVATE-SENTINEL', (output / 'decisions.json').read_text())

    def test_hardlink_alias_is_rejected_before_sqlite_can_open_another_wal(self):
        with BodyLoop.start(self.path) as loop:
            alias = self.path.with_name('alias.sqlite')
            os.link(self.path, alias)
            before = self.path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'without hard links'):
                BodyLoop(alias)
            self.assertEqual(before, self.path.read_bytes())
            self.assertFalse(Path(str(alias) + '-wal').exists())
            alias.unlink()

    def test_session_and_sqlite_sidecars_are_private_even_with_permissive_umask(self):
        old = os.umask(0)
        try:
            with BodyLoop.start(self.path) as loop:
                loop.observe()
                for path in self.path.parent.glob('session.sqlite*'):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600, str(path))
        finally:
            os.umask(old)


if __name__ == '__main__': unittest.main()
