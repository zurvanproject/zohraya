"""Run via the CLI so native sources are verified and copied before import."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from examples.nasuraya_body_loop.host import BodyLoop
from .appraisal import apply, appraise
from .fixtures import observation


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'session.sqlite'

    def test_real_native_affect_transition_is_persisted_with_input(self):
        with BodyLoop.start(self.path) as loop:
            before = deepcopy(loop.body().affect['affect'])
            result = apply(loop, observation())
            after = loop.body().affect['affect']
            self.assertGreater(after['admiration'], before['admiration'])
            self.assertGreater(after['contentment'], before['contentment'])
            self.assertEqual(after['shame'], before['shame'])
            self.assertEqual(after['trust'], before['trust'])
            self.assertEqual(result['native_receipt']['actual_action'], 'observe')
            self.assertEqual(result['affect_transition']['affect_after'], after)
            event = loop.engine.get('visual:fixture')['request']['execution']['external']['social']
            self.assertEqual(json.loads(event['summary']), result['report'])
            self.assertLess(abs(result['native_receipt']['body_audit']['energy_error_J']), 1e-6)

    def test_counterfactual_self_other_has_same_beauty_different_contentment(self):
        values = []
        for subject in ('self', 'other'):
            with BodyLoop.start(self.path.with_name(subject + '.sqlite')) as loop:
                result = apply(loop, observation(subject=subject))
                values.append(result['affect_transition']['affect_after'])
        self.assertEqual(values[0]['admiration'], values[1]['admiration'])
        self.assertGreater(values[0]['contentment'], values[1]['contentment'])
        self.assertEqual(values[0]['trust'], values[1]['trust'])

    def test_completed_replay_after_later_event_returns_historical_affect(self):
        with BodyLoop.start(self.path) as loop:
            first = apply(loop, observation())
            second = observation(beauty=0.); second['id'] = 'later'; apply(loop, second)
            before = loop.body().checkpoint()
            replay = apply(loop, observation())
            self.assertTrue(replay['native_receipt']['replayed'])
            self.assertEqual(replay['affect_transition'], first['affect_transition'])
            self.assertEqual(loop.body().checkpoint(), before)

    def test_changed_rating_or_provenance_on_same_id_is_rejected(self):
        with BodyLoop.start(self.path) as loop:
            apply(loop, observation()); before = loop.body().checkpoint()
            for changed in (observation(beauty=.1), observation(subject='other')):
                with self.assertRaisesRegex(ValueError, 'conflicting'): apply(loop, changed)
            self.assertEqual(loop.body().checkpoint(), before)
            self.assertEqual(loop.status()['actions_remaining'], 2)

    def test_budget_and_read_only_mode_still_apply(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            apply(loop, observation()); before = loop.body().checkpoint()
            obs = observation(); obs['id'] = 'second'
            with self.assertRaisesRegex(ValueError, 'budget exhausted'): apply(loop, obs)
            self.assertEqual(before, loop.body().checkpoint())
        with BodyLoop.start(self.path.with_name('read.sqlite'), mode='observe') as loop:
            before = loop.body().checkpoint()
            with self.assertRaisesRegex(ValueError, 'disabled'): apply(loop, observation())
            self.assertEqual(before, loop.body().checkpoint())

    def test_invalid_input_consumes_neither_budget_nor_fresh_observation(self):
        with BodyLoop.start(self.path) as loop:
            loop.observe(); before = loop.body().checkpoint()
            event = appraise(observation())['social_event']; event['signals']['fake'] = .9
            with self.assertRaises(ValueError): loop.step(social_event=event)
            self.assertEqual(before, loop.body().checkpoint())
            loop.step(); self.assertEqual(loop.status()['completed_cycles'], 1)

    def test_cold_process_replays_without_another_native_cycle(self):
        with BodyLoop.start(self.path) as loop:
            first = apply(loop, observation()); before = loop.body().checkpoint()
        code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_aesthetics.appraisal import apply
from examples.nasuraya_aesthetics.fixtures import observation
with BodyLoop(sys.argv[1]) as loop:
 result=apply(loop,observation())
 print(json.dumps({'result':result,'checkpoint':loop.body().checkpoint()}))
'''
        proc = subprocess.run([sys.executable, '-S', '-c', code, str(self.path)],
                              capture_output=True, text=True, check=True)
        value = json.loads(proc.stdout)
        self.assertEqual(value['checkpoint'], before)
        self.assertEqual(value['result']['affect_transition'], first['affect_transition'])
        self.assertTrue(value['result']['native_receipt']['replayed'])

    def test_uncertain_identity_can_change_native_affect_plan_to_verification(self):
        with BodyLoop.start(self.path) as loop:
            result = apply(loop, observation(image_sha256='1'*64))
            self.assertEqual(result['affect_transition']['plan']['action'], 'verify')
            self.assertEqual(result['native_receipt']['actual_action'], 'observe')

    def test_high_beauty_cannot_hide_a_declared_proportion_issue_in_native_plan(self):
        obs = observation(beauty=1.)
        obs['ratings']['proportion'] = dict(value=.2, confidence=1., kind='synthetic_fixture',
                                          source_ref='fixture://proportion-issue')
        with BodyLoop.start(self.path) as loop:
            result = apply(loop, obs)
            self.assertEqual(result['report']['recommendation'], 'review_proportions')
            self.assertEqual(result['affect_transition']['plan']['action'], 'verify')

    def test_source_pinned_native_runtime_is_unchanged(self):
        from examples.nasuraya_body_loop.__main__ import verified_sources
        self.assertGreater(len(verified_sources()), 60)
