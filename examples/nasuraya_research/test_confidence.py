"""Forecast contracts and real native-loop integration on disposable fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_body_loop.host import BodyLoop
from .confidence import forecast, probability
from .controller import BoundedResearchController as Controller, KEY, ResearchBlocked


class ConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'session.sqlite'

    def start(self, **kwargs):
        loop = BodyLoop.start(self.path, **kwargs)
        self.addCleanup(loop.close)
        return loop, Controller.enable(loop, forecast_confidence=.75)

    def test_invalid_priors_have_no_authority_side_effect(self):
        with BodyLoop.start(self.path) as loop:
            for value in (True, '0.5', float('nan'), float('inf'), -.1, 1.1):
                with self.assertRaises(ValueError): Controller.enable(loop, forecast_confidence=value)
                self.assertIsNone(loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone())
            Controller.enable(loop, forecast_confidence=0)
        self.assertEqual(probability(1), 1.)

    def test_history_is_scoped_capped_and_needs_two_samples(self):
        domain = dict(action='walk', duration_s=.1, restrictions=[])
        row = dict(domain=domain, raw_confidence=.9, outcome=False)
        other = dict(row, domain=dict(action='observe'))
        self.assertEqual(forecast(.9, domain, [row, other])['calibrated_confidence'], .9)
        f = forecast(.9, domain, [row, row])
        self.assertEqual(f['samples'], 2)
        self.assertAlmostEqual(f['calibrated_confidence'], .65)
        self.assertEqual(f['correction'], .25)
        with self.assertRaises(ValueError): forecast(.9, domain, [row]*4)
        with self.assertRaises(ValueError): forecast(.9, domain, [dict(row, outcome=None)])

    def test_forecast_is_reserved_before_native_effect(self):
        loop, control = self.start()
        original = loop.step
        def check(**kwargs):
            prediction = control._load()['intents']['one']['prediction']
            self.assertIsNone(prediction['outcome'])
            self.assertEqual(prediction['samples'], 0)
            self.assertEqual(loop.body().revision, before)
            return original(**kwargs)
        before = loop.body().revision
        with patch.object(loop, 'step', side_effect=check):
            result = control.step('one')
        self.assertTrue(result['prediction']['outcome'])
        self.assertIn('native-decision://research-authority:one/', result['prediction']['outcome_source'])

    def test_two_successes_adjust_third_forecast_but_not_authority(self):
        _, control = self.start()
        results = control.run(steps=3)['results']
        self.assertEqual([r['prediction']['samples'] for r in results], [0, 1, 2])
        self.assertEqual([r['prediction']['calibrated_confidence'] for r in results], [.75, .75, .875])
        self.assertEqual(results[-1]['prediction']['raw_brier'], .0625)
        self.assertEqual(results[-1]['prediction']['calibrated_brier'], .015625)
        self.assertEqual(control.status()['native']['actions_remaining'], 0)
        with self.assertRaises(ResearchBlocked): control.step('extra')

    def test_native_veto_is_a_prediction_failure_even_when_cycle_completed(self):
        from .controller import snapshot
        _, control = self.start(fixture='sleep')
        def wrong(body):
            value = snapshot(body)
            value['audit']['upper_controller_walk_guard_allows'] = True
            value['audit']['walking_restrictions'] = []
            return value
        with patch('examples.nasuraya_research.controller.snapshot', side_effect=wrong):
            results = control.run(steps=3)['results']
        # First the native body protects itself; its existing scoped feedback
        # then makes DecisionCore choose observe instead of repeating a veto.
        self.assertEqual([r['native_receipt']['actual_action'] for r in results],
                         ['protect', 'observe', 'observe'])
        self.assertTrue(results[1]['native_receipt']['recalled_feedback_ids'])
        for row in results:
            self.assertFalse(row['prediction']['outcome'])
        self.assertEqual(results[-1]['prediction']['calibrated_confidence'], .5)
        self.assertEqual(results[-1]['prediction']['calibrated_brier'], .25)

    def test_actual_success_is_not_guessed_from_initial_fixture_label(self):
        _, control = self.start(fixture='sleep')
        result = control.step('rest')
        self.assertEqual(result['preferred_action'], 'observe')
        self.assertTrue(result['prediction']['outcome'])

    def test_completed_failure_gets_zero_and_pauses_without_refund(self):
        _, control = self.start()
        with patch('unified_body_v2.UnifiedBody.cycle', side_effect=RuntimeError('test failure')):
            result = control.step('failed')
        self.assertFalse(result['prediction']['outcome'])
        self.assertFalse(control.status()['enabled'])
        self.assertEqual(control.status()['native']['actions_remaining'], 2)

    def test_unknown_outcome_never_trains_or_reexecutes(self):
        loop, control = self.start()
        with patch.object(loop, 'step', side_effect=OSError('unknown')):
            with self.assertRaises(OSError): control.step('lost')
        intent = control._load()['intents']['lost']
        self.assertIsNone(intent['prediction']['outcome'])
        self.assertIsNone(intent['result'])
        self.assertEqual(control.status()['calibration']['resolved'], 0)
        with self.assertRaises(ResearchBlocked): control.step('lost')

    def test_recovery_and_replay_attach_outcome_once_without_double_learning(self):
        loop, control = self.start()
        with patch.object(control, '_complete', side_effect=OSError('lost attachment')):
            with self.assertRaises(OSError): control.step('recover')
        before = loop.body().checkpoint()
        with patch.object(loop, 'step', side_effect=AssertionError('double execution')):
            recovered = control.step('recover')
            replayed = control.step('recover')
        self.assertEqual(recovered['prediction'], replayed['prediction'])
        self.assertEqual(before, loop.body().checkpoint())
        second = control.step('second')
        self.assertEqual(second['prediction']['samples'], 1)

    def test_raw_prior_and_learning_survive_cold_restart(self):
        with BodyLoop.start(self.path) as loop:
            control = Controller.enable(loop, forecast_confidence=.75)
            control.step('one'); control.step('two'); control.pause()
        with BodyLoop(self.path) as loop:
            control = Controller(loop)
            with self.assertRaises(ResearchBlocked): control.step('paused')
            control.resume()
            third = control.step('third')['prediction']
            self.assertEqual(third['samples'], 2)
            self.assertEqual(third['calibrated_confidence'], .875)

    def test_duration_change_does_not_reuse_other_domain(self):
        _, control = self.start()
        control.step('one'); control.step('two')
        result = control.step('longer', duration_s=.2)
        self.assertEqual(result['prediction']['samples'], 0)

    def test_calibration_cannot_change_native_requests_or_body_outcomes(self):
        # The same fresh fixture and request IDs produce byte-equivalent native
        # requests and identical body checkpoints with calibration off/on.
        other = Path(self.temp.name) / 'other.sqlite'
        with BodyLoop.start(self.path) as a, BodyLoop.start(other) as b:
            plain = Controller.enable(a)
            calibrated = Controller.enable(b, forecast_confidence=0)
            for i in range(3):
                left = plain.step(str(i)); right = calibrated.step(str(i))
                self.assertEqual(a.engine.get('research-authority:'+str(i)),
                                 b.engine.get('research-authority:'+str(i)))
                self.assertEqual(a.body().checkpoint(), b.body().checkpoint())
                self.assertEqual(left['native_receipt'], right['native_receipt'])

    def test_cli_prior_is_fixed_and_replay_is_read_only(self):
        from examples.nasuraya_body_loop.__main__ import ROOT
        def cli(*args):
            return subprocess.run([sys.executable, '-S', '-m', 'examples.nasuraya_research.control',
                *args, '--session', str(self.path)], cwd=ROOT, text=True, capture_output=True)
        initialized = cli('init', '--forecast-confidence', '.75')
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertTrue(json.loads(initialized.stdout)['calibration']['enabled'])
        self.assertNotEqual(cli('step', '--request-id', 'one', '--forecast-confidence', '.9').returncode, 0)
        first = cli('step', '--request-id', 'one')
        replay = cli('step', '--request-id', 'one')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(json.loads(first.stdout)['prediction'], json.loads(replay.stdout)['prediction'])
        self.assertEqual(json.loads(replay.stdout)['this_call_native_cycles'], 0)

    def test_small_sample_correction_can_hurt_after_distribution_shift(self):
        # Negative control: a functional update is not a guarantee of accuracy.
        domain = {'action': 'walk'}
        history = [dict(domain=domain, raw_confidence=.5, outcome=True)] * 2
        prediction = forecast(.5, domain, history)
        self.assertGreater(prediction['calibrated_confidence']**2, .5**2)


if __name__ == '__main__':
    unittest.main()
