"""Behavioral checks of the new bridge, run inside the verified source worker."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .host import BodyLoop, InterruptedExecution
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


if __name__ == '__main__': unittest.main()
