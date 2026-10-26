"""Native affect and body integration; no replacement/mock emotion engine.

These require the complete repository. They are separate from locally executed
pure contracts so a missing native runtime cannot silently count as a pass.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .appraisal import digest, native_affect, preview, preview_stored
from .test_appraisal import fixture


class NativeAffectTests(unittest.TestCase):
    def setUp(self):
        self.native = native_affect()
        self.state = self.native.initial_state()

    def test_receipt_changes_existing_joy_not_forecast(self):
        row = fixture(); old = deepcopy(row)
        out = preview(self.state, row)
        self.assertGreater(out['state']['affect']['joy'], self.state['affect']['joy'])
        self.assertEqual(out['evidence']['calibrated_confidence'], .9)
        self.assertEqual(row, old)
        self.assertEqual(self.state['tick'], 0)

    def test_failed_prediction_is_verified_even_with_high_joy(self):
        self.state['affect']['joy'] = 1.
        out = preview(self.state, fixture(outcome=False, p=.95))
        self.assertEqual(out['record']['plan']['action'], 'verify')
        self.assertFalse(out['evidence']['preferred_action_executed'])
        self.assertGreater(out['state']['affect']['surprise'], 0.)
        self.assertGreater(out['state']['affect']['disappointment'], 0.)

    def test_calm_cannot_manufacture_progress(self):
        row=fixture(outcome=False, p=.9)
        a=preview(self.state, row)
        self.state['affect'].update(calm=1., fear=0., joy=1.)
        b=preview(self.state, row)
        self.assertEqual(a['evidence'], b['evidence'])
        self.assertEqual(b['evidence']['body_need_change'], 0.)

    def test_mixed_recovery_and_prediction_failure_are_retained(self):
        out=preview(self.state, fixture(outcome=False, p=.95,
            after=[.9,1.,.05,0.,.05,1.]))
        self.assertGreater(out['state']['affect']['relief'], 0.)
        self.assertGreater(out['state']['affect']['disappointment'], 0.)
        self.assertFalse(out['evidence']['preferred_action_executed'])

    def test_affect_ablation_changes_plan_but_not_evidence(self):
        row=fixture(p=.9)
        a=preview(self.state, row); b=preview(self.state, row, affect_enabled=False)
        self.assertNotEqual(a['record']['plan']['action'], b['record']['plan']['action'])
        self.assertEqual(a['evidence'], b['evidence'])

    def test_existing_body_priority_survives_success(self):
        row=fixture(after=[.1,.9,.1,0.,.1,1.])
        out=preview(self.state, row)
        self.assertEqual(out['record']['plan']['action'], 'pause_regulate')

    def test_existing_respect_boundary_survives_warmth(self):
        event=dict(id='space-check', source='synthetic_fixture', autonomy='space_requested',
                   partner='test-person', signals=dict(warmth=1., need=.1))
        record=self.native.transition(self.state,event)
        self.assertEqual(record['plan']['action'], 'respect_space')
        self.assertEqual(record['plan']['expression']['pressure_to_return'], 0.)
        self.assertFalse(record['plan']['expression']['retaliation'])

    def test_duplicate_episode_rejected_without_mutating_input(self):
        row=fixture(); out=preview(self.state,row); prior=digest(out['state'])
        with self.assertRaises(ValueError): preview(out['state'],row)
        self.assertEqual(digest(out['state']),prior)

    def test_invalid_result_has_no_affect_transition(self):
        prior=digest(self.state)
        with self.assertRaises(ValueError): preview(self.state,dict(fixture(),historical_native_cycles=0))
        self.assertEqual(digest(self.state),prior)

    def test_native_cold_restore_replays_same_next_result(self):
        out=preview(self.state,fixture())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'affect.json'; self.native.save(out['state'],path)
            code=("from pathlib import Path; import json; from examples.nasuraya_affect_research.appraisal "
                  "import native_affect, digest; print(digest(native_affect().load(Path(__import__('sys').argv[1]))))")
            result=subprocess.run([sys.executable,'-c',code,str(path)],check=True,capture_output=True,text=True)
            self.assertEqual(result.stdout.strip(),digest(out['state']))
            next_row=fixture(outcome=False,p=.95)
            next_row['prediction']['outcome_source']='native-decision://constructed-next/'+('d'*64)
            a=preview(out['state'],next_row)
            b=preview(self.native.load(path),next_row)
            self.assertEqual(a,b)


class NativeBodyBridgeTests(unittest.TestCase):
    def test_completed_native_result_is_read_without_new_action(self):
        native=native_affect()
        from examples.nasuraya_body_loop.host import BodyLoop
        from examples.nasuraya_research.controller import BoundedResearchController
        with tempfile.TemporaryDirectory() as tmp, BodyLoop.start(Path(tmp)/'body.sqlite',max_actions=1) as loop:
            controller=BoundedResearchController.enable(loop,forecast_confidence=.75)
            controller.step('actual')
            before=deepcopy(loop.body().checkpoint()); status=controller.status()
            output=preview_stored(controller,'actual',native.initial_state())
            self.assertEqual(loop.body().checkpoint(),before)
            self.assertEqual(controller.status(),status)
            self.assertTrue(output['evidence']['preferred_action_executed'])
            self.assertEqual(output['body_actions_executed'],0)
            self.assertEqual(controller.status()['native']['actions_remaining'],0)

    def test_unknown_stored_result_cannot_start_work(self):
        native=native_affect()
        from examples.nasuraya_body_loop.host import BodyLoop
        from examples.nasuraya_research.controller import BoundedResearchController
        with tempfile.TemporaryDirectory() as tmp, BodyLoop.start(Path(tmp)/'body.sqlite',max_actions=1) as loop:
            controller=BoundedResearchController.enable(loop,forecast_confidence=.75)
            before=controller.status()
            with self.assertRaises(ValueError): preview_stored(controller,'not-started',native.initial_state())
            self.assertEqual(controller.status(),before)

if __name__=='__main__':
    unittest.main()
