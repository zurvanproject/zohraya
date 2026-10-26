from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_agent_loop import local
from .engine import AffectiveAgent
from .workshop import AffectiveWorkshop, candidates


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'session.sqlite'
        self.agent = AffectiveAgent(self.path)
        self.work = AffectiveWorkshop.attach(self.agent, local.State(29, 78, 3), max_actions=4)

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_affect_changes_executed_recovery_and_completes_task(self):
        result = self.work.run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['final']['actions_used'], 4)
        self.assertEqual(result['receipts'][0]['action_id'], 'recover_3')
        self.assertEqual(result['receipts'][0]['baseline_action'], 'recover_1')
        self.assertEqual(result['receipts'][0]['after']['energy'], 89)
        self.assertEqual(result['final']['state']['completed_jobs'], 3)
        self.assertGreater(result['final']['affect']['joy'], 0)
        # Appraisal and returned outcome each persisted once for every action.
        self.assertEqual(self.agent.state()['revision'], 8)

    def test_same_budget_without_affect_stops_with_unfinished_work(self):
        with AffectiveAgent(Path(self.tmp.name)/'off.sqlite') as other:
            work = AffectiveWorkshop.attach(other, local.State(29, 78, 3), max_actions=4, use_affect=False)
            result = work.run()
        self.assertEqual(result['status'], 'bounded_stop')
        self.assertEqual(result['final']['state']['completed_jobs'], 2)
        self.assertEqual(result['final']['actions_used'], 4)

    def test_receipt_replay_and_cold_process_do_not_refill_budget(self):
        first = self.work.step('first')
        before = self.agent.state()
        replay = self.work.step('first')
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['this_call_actions'], 0)
        self.assertEqual(replay['after'], first['after'])
        self.assertEqual(self.agent.state(), before)
        raw = subprocess.check_output([sys.executable, '-m', 'examples.nasuraya_affect.workshop',
                                       'run', '--db', str(self.path)], text=True)
        result = json.loads(raw)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['final']['actions_used'], 4)
        with self.assertRaisesRegex(ValueError, 'goal already'):
            self.work.step('extra')

    def test_interruption_before_execution_commit_is_recoverable(self):
        save = self.work._save
        calls = 0
        def fail_second(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('crash before host commit')
            save(value)
        with patch.object(self.work, '_save', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.work.step('interrupted')
        self.assertEqual(self.work.status()['actions_used'], 0)
        self.assertEqual(self.agent.state()['revision'], 1)
        with self.assertRaisesRegex(ValueError, 'pending'):
            self.work.step('different')
        result = self.work.step('interrupted')
        self.assertEqual(result['actions_used'], 1)
        self.assertEqual(self.agent.state()['revision'], 2)

    def test_interruption_after_host_commit_does_not_repeat_action(self):
        with patch.object(self.work, '_feedback', side_effect=RuntimeError('crash before feedback')):
            with self.assertRaises(RuntimeError):
                self.work.step('interrupted')
        self.assertEqual(self.work.status()['actions_used'], 1)
        self.assertEqual(self.agent.state()['revision'], 1)
        with patch.object(local.ToolHost, 'call', side_effect=AssertionError('must not execute again')):
            result = self.work.step('interrupted')
        self.assertEqual(result['this_call_actions'], 0)
        self.assertEqual(self.agent.state()['revision'], 2)
        self.assertIsNone(self.work.status()['pending'])

    def test_interruption_after_feedback_replays_without_amplification(self):
        save = self.work._save
        calls = 0
        def fail_third(value):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError('crash before clearing pending feedback')
            save(value)
        with patch.object(self.work, '_save', side_effect=fail_third):
            with self.assertRaises(RuntimeError):
                self.work.step('interrupted')
        before = self.agent.state()
        self.work.step('interrupted')
        self.assertEqual(self.agent.state(), before)
        self.assertEqual(self.work.status()['actions_used'], 1)

    def test_observe_mode_and_budget_survive_restart(self):
        for mode, budget in [('observe', 4), ('bounded', 0)]:
            path = Path(self.tmp.name)/(mode+'.sqlite')
            with AffectiveAgent(path) as other:
                work = AffectiveWorkshop.attach(other, mode=mode, max_actions=budget)
                with self.assertRaises(ValueError):
                    work.step('blocked')
                self.assertEqual(other.state()['revision'], 0)
            with AffectiveAgent(path) as other:
                work = AffectiveWorkshop(other)
                self.assertEqual(work.status()['actions_used'], 0)
                self.assertEqual(work.status()['actions_remaining'], budget)

    def test_candidate_dry_runs_do_not_mutate_host_or_admit_blocked_job(self):
        host = local.ToolHost(local.State(0, 100, 2), local.Journal(), max_actions=2)
        before = host.state
        choices = candidates(host)
        self.assertNotIn('process_job', [c['action']['id'] for c in choices])
        self.assertEqual(host.state, before)
        self.assertEqual(host.actions_used, 0)
        self.assertEqual(host.journal.events, [])

    def test_repeated_attachment_cannot_reset_authority(self):
        self.work.step('first')
        with self.assertRaises(Exception):
            AffectiveWorkshop.attach(self.agent, max_actions=100)
        self.assertEqual(self.work.status()['actions_remaining'], 3)

    def test_empty_queue_does_not_offer_excess_recovery(self):
        host = local.ToolHost(local.State(0, 100, 0), local.Journal())
        self.assertEqual([o['action']['id'] for o in candidates(host)], ['recover_1'])

    def test_recovery_horizon_tracks_remaining_jobs(self):
        host = local.ToolHost(local.State(25, 70, 2), local.Journal())
        self.assertEqual([o['action']['id'] for o in candidates(host)], ['recover_1', 'recover_2'])


if __name__ == '__main__':
    unittest.main()
