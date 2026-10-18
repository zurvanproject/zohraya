"""Functional authority tests; run through `control test`'s verified worker."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_body_loop.host import BodyLoop
from .adapters import digest
from .controller import BoundedResearchController as Controller, ResearchBlocked, KEY


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'session.sqlite'

    def start(self, **kwargs):
        loop = BodyLoop.start(self.path, **kwargs)
        self.addCleanup(loop.close)
        return loop

    def enabled(self, **kwargs):
        loop = self.start(**kwargs)
        return loop, Controller.enable(loop)

    def test_explicit_enable_is_required(self):
        loop = self.start(); before = loop.body().checkpoint()
        with self.assertRaises(ResearchBlocked): Controller(loop)
        self.assertEqual(before, loop.body().checkpoint())

    def test_observe_mode_and_larger_native_budget_cannot_gain_authority(self):
        with BodyLoop.start(self.path, mode='observe') as loop:
            with self.assertRaises(ValueError): Controller.enable(loop)
        other = Path(self.temp.name) / 'large.sqlite'
        with BodyLoop.start(other, max_actions=4) as loop:
            with self.assertRaises(ValueError): Controller.enable(loop)

    def test_normal_body_executes_one_existing_native_cycle(self):
        loop, control = self.enabled(); before = loop.body().revision
        result = control.step('one')
        self.assertEqual(result['preferred_action'], 'walk')
        self.assertEqual(result['native_receipt']['actual_action'], 'walk')
        self.assertEqual(result['this_call_native_cycles'], 1)
        self.assertEqual(loop.body().revision, before + 1)
        self.assertEqual(control.status()['native']['actions_remaining'], 2)
        self.assertLess(abs(result['native_receipt']['body_audit']['energy_error_J']), 1e-6)

    def test_sleep_restriction_selects_observation_before_requesting_movement(self):
        _, control = self.enabled(fixture='sleep')
        result = control.step('rest')
        self.assertEqual(result['preferred_action'], 'observe')
        self.assertIn('sleep_pressure', result['reasons'])
        self.assertEqual(result['native_receipt']['actual_action'], 'observe')

    def test_native_veto_still_overrules_an_incorrect_upper_preference(self):
        from .controller import snapshot
        _, control = self.enabled(fixture='sleep')
        def mistaken(body):
            value = snapshot(body)
            value['audit']['upper_controller_walk_guard_allows'] = True
            value['audit']['walking_restrictions'] = []
            return value
        with patch('examples.nasuraya_research.controller.snapshot', side_effect=mistaken):
            result = control.step('native-veto')
        self.assertEqual(result['preferred_action'], 'walk')
        self.assertEqual(result['native_receipt']['actual_action'], 'protect')
        self.assertFalse(result['native_receipt']['expected_outcome_matched'])

    def test_three_action_budget_persists_and_reenable_cannot_refill_it(self):
        with BodyLoop.start(self.path, max_actions=3) as loop:
            control = Controller.enable(loop)
            control.run(steps=3)
            self.assertEqual(control.status()['native']['completed_cycles'], 3)
        with BodyLoop(self.path) as loop:
            control = Controller(loop); before = loop.body().checkpoint()
            control.pause(); control.resume()
            with self.assertRaises(ResearchBlocked): control.step('four')
            with self.assertRaises(ResearchBlocked): Controller.enable(loop)
            self.assertEqual(before, loop.body().checkpoint())
            self.assertEqual(control.status()['native']['actions_remaining'], 0)

    def test_pause_survives_restart_and_resume_preserves_budget(self):
        with BodyLoop.start(self.path) as loop:
            Controller.enable(loop).pause()
        with BodyLoop(self.path) as loop:
            control = Controller(loop); before = loop.body().checkpoint()
            with self.assertRaises(ResearchBlocked): control.step('paused')
            self.assertEqual(before, loop.body().checkpoint())
            control.resume(); control.step('after-resume')
            self.assertEqual(control.status()['native']['actions_remaining'], 2)

    def test_completed_replay_after_another_step_has_no_new_effect(self):
        loop, control = self.enabled()
        first = control.step('one'); control.step('two')
        before = loop.body().checkpoint()
        with patch.object(loop, 'step', side_effect=AssertionError('unexpected replay')):
            replay = control.step('one')
        self.assertEqual(replay['research_after'], first['research_after'])
        self.assertEqual(replay['this_call_native_cycles'], 0)
        self.assertTrue(replay['replayed'])
        self.assertEqual(before, loop.body().checkpoint())

    def test_conflicting_replay_does_not_advance_or_refund(self):
        loop, control = self.enabled(); control.step('one')
        before = loop.body().checkpoint()
        with self.assertRaises(ValueError): control.step('one', duration_s=.2)
        self.assertEqual(before, loop.body().checkpoint())
        self.assertEqual(control.status()['native']['actions_remaining'], 2)

    def test_foreign_native_receipt_cannot_be_adopted(self):
        loop, control = self.enabled()
        loop.observe(); loop.step(decision_id='research-authority:foreign')
        before = loop.body().checkpoint()
        with self.assertRaises(ResearchBlocked): control.step('foreign')
        self.assertEqual(before, loop.body().checkpoint())
        self.assertEqual(control.status()['requests'], 0)

    def test_failure_to_record_reservation_prevents_execution(self):
        loop, control = self.enabled(); before = loop.body().checkpoint()
        with patch.object(control, '_save', side_effect=OSError('disk unavailable')), \
             patch.object(loop, 'step', side_effect=AssertionError('unreserved effect')):
            with self.assertRaises(OSError): control.step('disk')
        self.assertEqual(before, loop.body().checkpoint())
        self.assertEqual(control.status()['requests'], 0)

    def test_reserved_request_with_unknown_outcome_never_automatically_reexecutes(self):
        loop, control = self.enabled(); before = loop.body().checkpoint()
        with patch.object(loop, 'step', side_effect=OSError('lost worker')):
            with self.assertRaises(OSError): control.step('lost')
        for request_id in ('lost', 'new'):
            with self.assertRaises(ResearchBlocked): control.step(request_id)
        control.pause(); control.resume()
        with self.assertRaises(ResearchBlocked): control.run()
        self.assertEqual(control.status()['pending'], ['lost'])
        self.assertEqual(before, loop.body().checkpoint())

    def test_native_commit_is_recovered_without_reexecution_after_metadata_failure(self):
        loop, control = self.enabled()
        with patch.object(control, '_complete', side_effect=OSError('lost result write')):
            with self.assertRaises(OSError): control.step('committed')
        recorded = loop.body().checkpoint()
        loop.observe(); loop.step(decision_id='outside-later')
        current = loop.body().checkpoint()
        with patch.object(loop, 'step', side_effect=AssertionError('double effect')):
            result = control.step('committed')
        self.assertTrue(result['replayed'])
        self.assertEqual(result['this_call_native_cycles'], 0)
        self.assertEqual(result['research_after']['source_checkpoint_sha256'], recorded['sha256'])
        self.assertEqual(current, loop.body().checkpoint())
        self.assertEqual(control.status()['pending'], [])
        self.assertEqual(control.status()['native']['actions_remaining'], 1)

    def test_caught_native_failure_pauses_controller_without_budget_refund(self):
        _, control = self.enabled()
        with patch('unified_body_v2.UnifiedBody.cycle', side_effect=RuntimeError('native failure')):
            result = control.step('failed')
        self.assertEqual(result['historical_native_cycles'], 0)
        self.assertFalse(control.status()['enabled'])
        self.assertEqual(control.status()['native']['actions_remaining'], 2)
        with self.assertRaises(ResearchBlocked): control.step('after-failure')

    def test_native_running_barrier_remains_unresolved_after_hard_interruption(self):
        _, control = self.enabled()
        with patch('unified_body_v2.UnifiedBody.cycle', side_effect=SystemExit('interrupted')):
            with self.assertRaises(SystemExit): control.step('interrupted')
        self.assertTrue(control.status()['native']['unresolved_running'])
        with self.assertRaises(ResearchBlocked): control.step('interrupted')
        with self.assertRaises(ResearchBlocked): control.step('other')

    def test_changed_grant_or_source_is_rejected(self):
        loop, control = self.enabled(); before = loop.body().checkpoint()
        raw = loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()[0]
        value = json.loads(raw); value['value']['source_sha256'] = '0'*64
        value['sha256'] = digest(value['value'])
        loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(value), KEY))
        with self.assertRaises(ResearchBlocked): control.step('changed')
        self.assertEqual(before, loop.body().checkpoint())

    def test_invalid_requests_and_runs_are_rejected_before_any_effect(self):
        loop, control = self.enabled(); before = loop.body().checkpoint()
        for steps in (0, 4, True):
            with self.assertRaises(ValueError): control.run(steps=steps)
        for duration in (float('nan'), True, 1.1, .15):
            with self.assertRaises(ValueError): control.run(duration_s=duration)
        for request_id in ('', '../escape', 'x'*65):
            with self.assertRaises(ValueError): control.step(request_id)
        self.assertEqual(before, loop.body().checkpoint())
        self.assertEqual(control.status()['requests'], 0)

    def test_overbudget_run_is_rejected_before_partial_execution(self):
        loop, control = self.enabled(max_actions=2)
        control.step('one'); before = loop.body().checkpoint()
        with self.assertRaises(ResearchBlocked): control.run(steps=2)
        self.assertEqual(before, loop.body().checkpoint())

    def test_controller_execution_calls_no_network_or_subprocess(self):
        _, control = self.enabled()
        with patch.object(socket, 'socket', side_effect=AssertionError('network')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('process')):
            result = control.step('local')
        self.assertEqual(result['this_call_native_cycles'], 1)
        self.assertEqual(result['model_api_calls'], 0)

    def test_cli_cold_restart_and_replay_use_the_same_persistent_budget(self):
        from examples.nasuraya_body_loop.__main__ import ROOT
        def cli(*args):
            result = subprocess.run([sys.executable, '-S', '-m', 'examples.nasuraya_research.control',
                *args, '--session', str(self.path)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(cli('init')['native']['actions_remaining'], 3)
        first = cli('step', '--request-id', 'cold')
        replay = cli('step', '--request-id', 'cold')
        self.assertEqual(first['this_call_native_cycles'], 1)
        self.assertEqual(replay['this_call_native_cycles'], 0)
        self.assertEqual(first['research_after'], replay['research_after'])
        self.assertEqual(cli('status')['native']['actions_remaining'], 2)


    def test_finite_run_uses_new_ids_after_a_named_step_matching_its_counter(self):
        loop, control = self.enabled()
        control.step('step-2')
        before = loop.body().revision
        result = control.run()
        self.assertEqual(result['results'][0]['this_call_native_cycles'], 1)
        self.assertEqual(loop.body().revision, before + 1)
        self.assertEqual(control.status()['requests'], 2)

    def test_cli_rejects_a_symlink_session_without_advancing_the_target(self):
        from examples.nasuraya_body_loop.__main__ import ROOT
        with BodyLoop.start(self.path) as loop:
            Controller.enable(loop)
            before = loop.body().checkpoint()
        alias = Path(self.temp.name) / 'alias.sqlite'
        alias.symlink_to(self.path)
        result = subprocess.run([sys.executable, '-S', '-m', 'examples.nasuraya_research.control',
            'run', '--session', str(alias)], cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        with BodyLoop(self.path) as loop:
            self.assertEqual(before, loop.body().checkpoint())


    def test_reserved_intent_rejects_later_foreign_receipts_even_with_same_id(self):
        for mismatch in ('duration', 'body'):
            with self.subTest(mismatch=mismatch):
                path = Path(self.temp.name) / (mismatch + '.sqlite')
                with BodyLoop.start(path) as loop:
                    control = Controller.enable(loop)
                    with patch.object(loop, 'step', side_effect=OSError('before native')):
                        with self.assertRaises(OSError): control.step('reserved')
                    if mismatch == 'body':
                        loop.observe(); loop.step(decision_id='unrelated')
                    loop.observe()
                    loop.step(decision_id='research-authority:reserved',
                              duration_s=.2 if mismatch == 'duration' else .1)
                    before = loop.body().checkpoint()
                    with self.assertRaisesRegex(ResearchBlocked, 'does not match'):
                        control.step('reserved')
                    self.assertEqual(before, loop.body().checkpoint())
                    self.assertEqual(control.status()['pending'], ['reserved'])
