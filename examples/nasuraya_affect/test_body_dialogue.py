from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_body_loop.host import BodyLoop
from .engine import AffectiveAgent, CHECKS
from .body_dialogue import DialogueBodyBridge, BridgeBlocked


def message(identifier='one', intent='explore'):
    checks = dict.fromkeys(CHECKS, 0.)
    checks.update(relevance=1., certainty=1., goal_congruence=.8, novelty=.8, controllability=.7)
    return dict(id=identifier, text='آزمون صریح اتصال پیام به بدن نرم‌افزاری',
                intent=intent, appraisal=checks, duration_s=.1)


class BodyDialogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def start(self, fixture='normal', max_actions=3):
        body = BodyLoop.start(self.path/'body.sqlite', fixture=fixture, max_actions=max_actions)
        self.addCleanup(body.close)
        affect = AffectiveAgent(self.path/'affect.sqlite')
        self.addCleanup(affect.close)
        return body, affect, DialogueBodyBridge.enable(body, affect)

    def test_message_executes_native_body_and_returns_measured_feedback(self):
        body, affect, bridge = self.start()
        before = body.body().revision
        result = bridge.receive(message())
        self.assertEqual(result['native_receipt']['actual_action'], 'walk')
        self.assertEqual(result['plan']['baseline_selected_action'], 'observe')
        self.assertEqual(result['this_call_body_cycles'], 1)
        self.assertEqual(body.body().revision, before+1)
        self.assertEqual(affect.state()['revision'], 2)
        audit = result['native_receipt']['body_audit']
        self.assertLess(abs(audit['energy_error_J']), 1e-6)
        self.assertLess(abs(audit['water_error_L']), 1e-9)

    def test_sleep_guard_keeps_excitement_from_requesting_walk(self):
        _, _, bridge = self.start(fixture='sleep')
        result = bridge.receive(message())
        self.assertIn('sleep_pressure', result['restrictions'])
        self.assertEqual(result['native_receipt']['actual_action'], 'observe')

    def test_explicit_observe_cannot_turn_into_walk(self):
        _, _, bridge = self.start()
        result = bridge.receive(message(intent='observe'))
        self.assertEqual(result['native_receipt']['actual_action'], 'observe')

    def test_reflection_and_stop_do_not_advance_body(self):
        body, _, bridge = self.start()
        before = body.body().checkpoint()
        bridge.receive(message('reflection', 'reflect'))
        bridge.receive(message('stop', 'stop'))
        self.assertEqual(body.body().checkpoint(), before)
        with self.assertRaises(BridgeBlocked):
            bridge.receive(message('blocked'))
        bridge.resume()
        self.assertEqual(bridge.status()['body']['actions_remaining'], 3)

    def test_replay_is_idempotent_and_conflicting_message_rejected(self):
        body, affect, bridge = self.start()
        bridge.receive(message())
        before = (body.body().checkpoint(), affect.state())
        self.assertEqual(bridge.receive(message())['this_call_body_cycles'], 0)
        with self.assertRaises(ValueError):
            bridge.receive(dict(message(), text='different'))
        self.assertEqual((body.body().checkpoint(), affect.state()), before)

    def test_budget_is_not_extended_by_new_messages_or_resume(self):
        body, _, bridge = self.start(max_actions=1)
        bridge.receive(message())
        bridge.resume()
        with self.assertRaises(BridgeBlocked):
            bridge.receive(message('two'))
        self.assertEqual(body.status()['completed_cycles'], 1)

    def test_committed_native_outcome_recovered_without_reexecution(self):
        body, affect, bridge = self.start()
        with patch.object(bridge, '_finish', side_effect=OSError('lost result write')):
            with self.assertRaises(OSError):
                bridge.receive(message())
        self.assertEqual(body.status()['completed_cycles'], 1)
        with patch.object(body, 'step', side_effect=AssertionError('duplicate execution')):
            result = bridge.receive(message())
        self.assertEqual(result['this_call_body_cycles'], 0)
        self.assertEqual(affect.state()['revision'], 2)

    def test_unknown_native_outcome_blocks_reexecution(self):
        body, _, bridge = self.start()
        with patch.object(body, 'step', side_effect=OSError('worker interrupted')):
            with self.assertRaises(OSError):
                bridge.receive(message())
        with self.assertRaises(BridgeBlocked):
            bridge.receive(message())
        with self.assertRaises(BridgeBlocked):
            bridge.receive(message('other'))
        bridge.pause()
        self.assertFalse(bridge.status()['enabled'])
        self.assertEqual(body.status()['completed_cycles'], 0)

    def test_foreign_native_receipt_cannot_be_adopted(self):
        body, _, bridge = self.start()
        body.observe(); body.step(decision_id='dialogue-body:one')
        with self.assertRaises(BridgeBlocked):
            bridge.receive(message())

    def test_pause_blocks_a_reserved_but_unexecuted_message(self):
        body, affect, bridge = self.start()
        with patch.object(affect, 'step', side_effect=OSError('planning interrupted')):
            with self.assertRaises(OSError):
                bridge.receive(message())
        bridge.pause()
        with self.assertRaises(BridgeBlocked):
            bridge.receive(message())
        self.assertEqual(body.status()['completed_cycles'], 0)
        bridge.resume()
        self.assertEqual(bridge.receive(message())['this_call_body_cycles'], 1)

    def test_native_veto_still_wins_if_upper_guard_is_wrong(self):
        _, _, bridge = self.start(fixture='sleep')
        from . import body_dialogue
        original = body_dialogue.snapshot
        def mistaken(body):
            value = original(body)
            value['audit']['upper_controller_walk_guard_allows'] = True
            value['audit']['walking_restrictions'] = []
            return value
        with patch.object(body_dialogue, 'snapshot', side_effect=mistaken):
            result = bridge.receive(message())
        self.assertEqual(result['native_receipt']['actual_action'], 'protect')
        self.assertNotIn('راه‌رفتن اجرا کرد', result['reply_fa'])


if __name__ == '__main__':
    unittest.main()
