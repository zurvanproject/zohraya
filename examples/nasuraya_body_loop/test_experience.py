"""Receipt, restart, feature-ablation and honest consolidation contracts."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reflection_cycle import InterruptedExecution
from .host import BodyLoop, UnifiedBody
from .experience import ExperienceController, KEY, METRICS, plan


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'body.sqlite'

    def tearDown(self):
        self.temp.cleanup()

    def test_native_protection_then_anticipatory_memory(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=3) as loop:
            c = ExperienceController.enable(loop)
            first = c.step('one')
            self.assertEqual(first['plan']['preferred'], 'walk')
            self.assertEqual(first['native_receipt']['actual_action'], 'protect')
            second = c.step('two')
            self.assertEqual(second['plan']['preferred'], 'observe')
            self.assertEqual(second['native_receipt']['actual_action'], 'observe')
            self.assertIn('one', second['plan']['recalled'])
            self.assertGreater(second['plan']['memory_risk'], .5)
            self.assertLess(first['affect_after']['valence'], .65)
            self.assertGreater(first['affect_after']['arousal'], .35)
            self.assertIsNotNone(first['prediction']['mean_absolute_error'])
            self.assertEqual(loop.status()['actions_reserved'], 2)
            for r in (first, second):
                self.assertLess(abs(r['native_receipt']['body_audit']['energy_error_J']), 1e-6)

    def test_replay_neither_reexecutes_nor_relearns(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            c = ExperienceController.enable(loop); first = c.step('one')
            before = c.status()
            again = c.step('one')
            self.assertTrue(again['replayed'])
            self.assertEqual(again['this_call_native_cycles'], 0)
            self.assertEqual(c.status(), before)
            self.assertEqual(again['prediction'], first['prediction'])
            with self.assertRaisesRegex(ValueError, 'conflicting'):
                c.step('one', duration_s=.2)

    def test_cold_process_keeps_affect_memory_and_budget(self):
        with BodyLoop.start(self.path, fixture='sleep', max_actions=2) as loop:
            c = ExperienceController.enable(loop); c.step('one'); c.consolidate()
            state = c.status()['state']
        code = '''import json,sys
from examples.nasuraya_body_loop.host import BodyLoop
from examples.nasuraya_body_loop.experience import ExperienceController
with BodyLoop(sys.argv[1]) as loop:
 c=ExperienceController(loop)
 before=c.status()['state']
 result=c.step('two')
 print(json.dumps({'before':before,'result':result,'remaining':loop.status()['actions_remaining']}))
'''
        result = json.loads(subprocess.run([sys.executable, '-c', code, str(self.path)],
            capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result['before'], state)
        self.assertEqual(result['result']['plan']['preferred'], 'observe')
        self.assertEqual(result['remaining'], 0)

    def test_crash_after_native_commit_recovers_once(self):
        with BodyLoop.start(self.path, max_actions=2) as loop:
            c = ExperienceController.enable(loop)
            with patch.object(c, '_finish', side_effect=RuntimeError('simulated crash')):
                with self.assertRaises(RuntimeError): c.step('one')
            self.assertEqual(loop.status()['completed_cycles'], 1)
        with BodyLoop(self.path) as loop:
            c = ExperienceController(loop)
            with self.assertRaises(InterruptedExecution): c.step('other')
            recovered = c.step('one')
            self.assertTrue(recovered['replayed'])
            self.assertEqual(recovered['this_call_native_cycles'], 0)
            self.assertEqual(len(c.status()['state']['episodes']), 1)
            self.assertEqual(loop.status()['completed_cycles'], 1)
            c.step('one')
            self.assertEqual(len(c.status()['state']['episodes']), 1)

    def test_crash_before_native_reservation_retries_safe_intent(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            with patch.object(loop, 'step', side_effect=RuntimeError('before native reservation')):
                with self.assertRaises(RuntimeError): c.step('one')
            self.assertEqual(loop.status()['actions_reserved'], 0)
            c.step('one')
            self.assertEqual(loop.status()['completed_cycles'], 1)

    def test_changed_body_blocks_unexecuted_reserved_intent(self):
        with BodyLoop.start(self.path, max_actions=3) as loop:
            c = ExperienceController.enable(loop)
            with patch.object(loop, 'step', side_effect=RuntimeError('crash')):
                with self.assertRaises(RuntimeError): c.step('one')
            loop.observe(); loop.step(decision_id='outside')
            with self.assertRaises(InterruptedExecution): c.step('one')

    def test_failure_does_not_fabricate_experience(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            with patch.object(UnifiedBody, 'cycle', side_effect=RuntimeError('failed')):
                r = c.step('one')
            self.assertEqual(r['native_receipt']['status'], 'executor_failed')
            self.assertIsNone(r['prediction']['actual'])
            self.assertIsNone(r['action_forecast_score'])
            self.assertEqual(c.status()['self_knowledge']['scored'], 0)
            self.assertEqual(c.status()['state']['episodes'], [])
            self.assertEqual(c.status()['state']['predictors'], {})
            self.assertEqual(loop.status()['actions_remaining'], 0)

    def test_prediction_is_reserved_before_execution_and_updates_after(self):
        with BodyLoop.start(self.path, max_actions=3) as loop:
            c = ExperienceController.enable(loop)
            first = c.step('one'); second = c.step('two')
            self.assertEqual(first['plan']['prediction']['prior_samples'], 0)
            self.assertEqual(first['plan']['prediction']['before'], first['plan']['prediction']['expected'])
            self.assertEqual(second['plan']['prediction']['prior_samples'], 1)
            self.assertEqual(set(first['prediction']['actual']), set(METRICS))
            self.assertIn('native-decision://', first['prediction']['source'])
            self.assertEqual(first['plan']['action_forecast']['samples'], 0)
            self.assertEqual(second['plan']['action_forecast']['samples'], 1)
            self.assertEqual(second['plan']['action_forecast']['source_ids'], ['one'])
            self.assertEqual(first['action_forecast_score']['actual_action'],
                             first['native_receipt']['actual_action'])
            self.assertEqual(c.status()['self_knowledge']['cold_start']['count'], 2)
            self.assertEqual(c.status()['state']['episodes'][0]['duration_s'], .1)

    def test_self_forecast_and_affect_audit_are_saved_before_execution(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            def stop_before_execution(**kwargs):
                intent = c._load()['intents']['one']
                self.assertIsNone(intent['result'])
                forecast = intent['plan']['action_forecast']
                self.assertIsNone(forecast['predicted_action'])
                self.assertEqual(forecast['status'], 'insufficient_evidence')
                self.assertNotIn('actual_action', forecast)
                self.assertIn('affect_audit', intent['plan'])
                self.assertEqual(loop.status()['completed_cycles'], 0)
                raise RuntimeError('before native execution')
            with patch.object(loop, 'step', side_effect=stop_before_execution):
                with self.assertRaisesRegex(RuntimeError, 'before native'):
                    c.step('one')
            saved = c._load()['intents']['one']['plan']
            result = c.step('one')
            self.assertEqual(result['plan'], saved)
            self.assertEqual(result['action_forecast_score']['distribution'],
                             saved['action_forecast']['distribution'])

    def test_legacy_reserved_plan_is_recovered_without_backfilled_forecast(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            with patch.object(c, '_finish', side_effect=RuntimeError('after native')):
                with self.assertRaises(RuntimeError): c.step('one')
            state = c._load()
            # Model a legitimately reserved older-version intent. The body
            # already ran; forecasting now would use hindsight.
            state['intents']['one']['plan'].pop('action_forecast')
            state['intents']['one']['plan'].pop('affect_audit')
            c._save(state)
            result = c.step('one')
            self.assertIsNone(result['action_forecast_score'])
            self.assertEqual(result['this_call_native_cycles'], 0)
            self.assertEqual(loop.status()['completed_cycles'], 1)
            self.assertEqual(c.status()['self_knowledge']['scored'], 0)

    def test_memory_ablation_changes_preference_for_same_observation(self):
        with BodyLoop.start(self.path, fixture='sleep') as loop:
            c = ExperienceController.enable(loop); c.step('one')
            state = c.status()['state']; snapshot = loop.observe()
            on = plan(state, snapshot, .1)
            state['flags']['memory'] = False
            off = plan(state, snapshot, .1)
            self.assertEqual(on['preferred'], 'observe')
            self.assertEqual(off['preferred'], 'walk')
            self.assertEqual(off['recalled'], [])

    def test_affect_ablation_changes_policy_but_cannot_add_actions(self):
        with BodyLoop.start(self.path) as loop:
            c = ExperienceController.enable(loop); state = c.status()['state']
            # Deliberately constructed control input; not a measured emotional state.
            state['affect'] = dict(valence=.05, arousal=.95)
            on = plan(state, loop.observe(), .1)
            state['flags']['affect'] = False
            off = plan(state, loop.observe(), .1)
            self.assertEqual((on['preferred'], off['preferred']), ('observe', 'walk'))
            self.assertEqual(set(on['scores']), {'walk', 'observe'})

    def test_prediction_ablation_does_not_update_model(self):
        with BodyLoop.start(self.path) as loop:
            c = ExperienceController.enable(loop, prediction=False)
            c.step('one'); c.step('two')
            self.assertEqual(c.status()['state']['predictors'], {})
            self.assertEqual(c.status()['state']['error_ema'], 0.)
            self.assertEqual(c.status()['self_knowledge']['scored'], 0)

    def test_consolidation_is_idempotent_and_hypotheses_are_not_evidence(self):
        with BodyLoop.start(self.path) as loop:
            c = ExperienceController.enable(loop); c.step('one'); c.step('two')
            before = loop.status()['self_model']['checkpoint_sha256']
            c.consolidate(); state = c.status()['state']
            again = c.consolidate()
            self.assertFalse(again['changed'])
            self.assertEqual(c.status()['state'], state)
            self.assertEqual(loop.status()['self_model']['checkpoint_sha256'], before)
            self.assertEqual(len(state['self_models']), 1)
            self.assertEqual(state['hypotheses'][0]['kind'], 'authored_hypothesis')
            self.assertFalse(state['hypotheses'][0]['verified'])
            p = plan(state, loop.observe(), .1)
            state['hypotheses'].append({'text':'pretend movement always succeeds'})
            self.assertEqual(plan(state, loop.observe(), .1), p)

    def test_consolidation_ablation(self):
        with BodyLoop.start(self.path) as loop:
            c = ExperienceController.enable(loop, consolidation=False); c.step('one')
            before = c.status()['state']
            self.assertFalse(c.consolidate()['enabled'])
            self.assertEqual(c.status()['state'], before)

    def test_invalid_input_and_exhaustion_leave_state_unchanged(self):
        with BodyLoop.start(self.path, max_actions=1) as loop:
            c = ExperienceController.enable(loop); before = c.status()
            for value in (float('nan'), True, .15, 2):
                with self.assertRaises(ValueError): c.step('one', duration_s=value)
            with self.assertRaises(ValueError): c.step('bad/id')
            self.assertEqual(c.status(), before)
            c.step('one'); before = c.status()
            with self.assertRaisesRegex(ValueError, 'budget'): c.step('two')
            self.assertEqual(c.status(), before)

    def test_explicit_enable_and_integrity(self):
        with BodyLoop.start(self.path) as loop:
            with self.assertRaises(ValueError): ExperienceController(loop)
            c = ExperienceController.enable(loop)
            with self.assertRaises(Exception): ExperienceController.enable(loop)
            loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?',
                (json.dumps({'value': c.status()['state'], 'sha256': 'wrong'}), KEY))
            with self.assertRaisesRegex(ValueError, 'integrity'): c.status()

    def test_observe_only_session_cannot_enable_authority(self):
        with BodyLoop.start(self.path, mode='observe', max_actions=0) as loop:
            with self.assertRaises(ValueError): ExperienceController.enable(loop)

    def test_native_id_collision_is_not_adopted_as_experience(self):
        with BodyLoop.start(self.path) as loop:
            c = ExperienceController.enable(loop)
            loop.observe(); loop.step(decision_id='experience:one')
            with self.assertRaisesRegex(ValueError, 'already belongs'): c.step('one')
            self.assertEqual(c.status()['state']['episodes'], [])


if __name__ == '__main__':
    unittest.main()
