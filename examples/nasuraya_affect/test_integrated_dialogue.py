"""Cross-ledger contracts, including fault injection and independent safety veto."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from reflection_cycle import InterruptedExecution
from . import test_body_dialogue as fixtures
from . import body_dialogue
message = fixtures.message


class IntegratedDialogueTests(unittest.TestCase):
    setUp = fixtures.BodyDialogueTests.setUp
    start = fixtures.BodyDialogueTests.start

    def test_prediction_precedes_body_and_next_message_uses_only_prior_receipts(self):
        body, _, bridge = self.start()
        original = body.step
        def measured_step(**kwargs):
            state = bridge.experience.status()['state']
            pending = [v for v in state['intents'].values() if v['result'] is None]
            self.assertEqual(len(pending), 1)
            self.assertNotIn('actual', pending[0]['plan']['prediction'])
            self.assertEqual(len(state['episodes']), body.status()['completed_cycles'])
            return original(**kwargs)
        with patch.object(body, 'step', side_effect=measured_step):
            first = bridge.receive(message('one'))
            second = bridge.receive(message('two'))
        p1, p2 = (r['experience']['prediction'] for r in (first, second))
        self.assertEqual(p1['method'], 'persistence_fallback')
        self.assertEqual(p2['method'], 'nearest_episode')
        self.assertEqual(p2['history_ids'], ['one'])
        self.assertEqual(p2['new_api_calls'], 0)
        self.assertFalse(p2['numeric_gate']['eligible'])
        self.assertIsInstance(p2['action_correct'], bool)
        self.assertGreaterEqual(p2['mean_absolute_error'], 0)
        self.assertEqual(body.status()['completed_cycles'], 2)
        trace = bridge.trace('two')
        self.assertEqual(trace['message']['source'], 'conversation://two')
        self.assertEqual(trace['appraisal_kind'], 'caller_authored_interpretation')
        self.assertEqual(trace['forecast']['history_ids'], ['one'])
        self.assertTrue(any(r['source']['locator'] == 'conversation://one' for r in trace['recalled']))
        self.assertTrue(p2['source'].startswith('native-decision://dialogue-body:two/'))

    def test_replay_trace_recall_and_consolidation_never_repeat_body_or_learning(self):
        body, affect, bridge = self.start()
        bridge.receive(message())
        bridge.experience.consolidate()
        before = deepcopy(bridge.status()), deepcopy(affect.state())
        with patch.object(body, 'step', side_effect=AssertionError('duplicate body call')):
            repeated = bridge.receive(message())
            self.assertEqual(repeated['experience']['this_call_native_cycles'], 0)
            self.assertTrue(repeated['experience']['native_receipt']['replayed'])
            self.assertEqual(bridge.trace('one')['body_cycles_executed_by_trace'], 0)
            self.assertEqual(bridge.recall(['body'])['body_cycles_executed'], 0)
            self.assertFalse(bridge.experience.consolidate()['changed'])
        self.assertEqual((bridge.status(), affect.state()), before)

    def test_crash_after_learning_before_bridge_commit_reconciles_once(self):
        body, affect, bridge = self.start()
        original = bridge._save
        def crash_on_result(state):
            if state['intents']['one']['result'] is not None:
                raise OSError('bridge result commit lost')
            return original(state)
        with patch.object(bridge, '_save', side_effect=crash_on_result):
            with self.assertRaises(OSError): bridge.receive(message())
        learned = deepcopy(bridge.experience.status()['state'])
        with patch.object(body, 'step', side_effect=AssertionError('duplicate execution')):
            recovered = bridge.receive(message())
        self.assertEqual(recovered['this_call_body_cycles'], 0)
        self.assertEqual(bridge.experience.status()['state'], learned)
        self.assertEqual(affect.state()['revision'], 2)
        self.assertEqual(body.status()['completed_cycles'], 1)

    def test_no_other_controller_can_execute_reserved_dialogue_intent(self):
        body, _, bridge = self.start()
        with patch.object(body, 'step', side_effect=OSError('outcome unknown')):
            with self.assertRaises(OSError): bridge.receive(message())
        for identifier in ('one', 'other'):
            with self.assertRaises(InterruptedExecution): bridge.experience.step(identifier)
        with self.assertRaises(InterruptedExecution): bridge.experience.complete_external('one', replayed=True)
        self.assertEqual(body.status()['completed_cycles'], 0)
        self.assertEqual(bridge.experience.status()['state']['episodes'], [])

    def test_native_protection_teaches_dialogue_even_when_upper_guard_is_wrong(self):
        body, _, bridge = self.start(fixture='sleep')
        original = body_dialogue.snapshot
        def mistaken(body):
            value = original(body)
            value['audit']['upper_controller_walk_guard_allows'] = True
            value['audit']['walking_restrictions'] = []
            return value
        with patch.object(body_dialogue, 'snapshot', side_effect=mistaken):
            first = bridge.receive(message('one'))
            second = bridge.receive(message('two'))
        self.assertEqual(first['native_receipt']['actual_action'], 'protect')
        self.assertEqual(second['native_receipt']['actual_action'], 'observe')
        self.assertIn('remembered_native_harm', second['restrictions'])
        self.assertIn('one', bridge.trace('two')['prior_body_memory']['recalled'])
        self.assertEqual(body.status()['actions_reserved'], 2)

    def test_observe_forecast_never_imports_walk_or_expands_paid_contract(self):
        _, _, bridge = self.start()
        first = bridge.receive(message('one', 'observe'))
        second = bridge.receive(message('two', 'observe'))
        for result in (first, second):
            forecast = result['experience']['prediction']
            self.assertEqual(forecast['predicted_action'], 'observe')
            self.assertEqual(forecast['numeric_gate']['reasons'], ['observe_outside_paid_comparison_contract'])
        self.assertEqual(second['experience']['prediction']['method'], 'nearest_episode')

    def test_forecast_keeps_feature_ablation_and_binding(self):
        body, _, bridge = self.start()
        bridge.receive(message('one'))
        state = bridge.experience._load()
        state['flags']['memory'] = False
        bridge.experience._save(state)
        second = bridge.receive(message('two'))
        self.assertEqual(second['experience']['prediction']['history_ids'], [])
        with self.assertRaisesRegex(ValueError, 'conflicting external'):
            bridge.experience.reserve_external('two', 'dialogue-body:two', body.observe(), .1, 'walk')

    def test_enable_twice_cannot_reset_shared_memory_or_budget(self):
        body, affect, bridge = self.start()
        bridge.receive(message())
        before = bridge.status()
        with self.assertRaisesRegex(ValueError, 'already enabled'):
            body_dialogue.DialogueBodyBridge.enable(body, affect)
        self.assertEqual(bridge.status(), before)
