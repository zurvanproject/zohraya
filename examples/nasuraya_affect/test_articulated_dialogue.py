from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from .engine import AffectiveAgent
from .fixtures import event
from .articulated_dialogue import ArticulatedDialogue, Blocked, KEY, validate_measurement


def message(identifier='m1', intent='explore'):
    return dict(id=identifier, text='Constructed test input', intent=intent, steps=2,
                appraisal=event(goal_congruence=1., novelty=1.)['appraisal'])


def measurement(success=True):
    return dict(requested_steps=2, accepted_steps=2 if success else 0, walk_pass=success,
                steps=[dict(accepted=True), dict(accepted=True)] if success else [], trace=[],
                failure=None if success else 'support gate', nonfoot_ground_contacts=[],
                max_joint_limit_excess_rad=0., max_motor_torque_fraction=1.,
                simulated_seconds=17., pelvis_displacement_xyz_m=[.08, 0., 0.])


class ArticulatedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'affect.sqlite'
        self.agent = AffectiveAgent(self.path)
        self.bridge = ArticulatedDialogue.enable(self.agent)

    def tearDown(self):
        self.agent.close(); self.tmp.cleanup()

    def test_measured_feedback_cold_replay_and_budget(self):
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial', return_value=measurement()) as execute:
            result = self.bridge.receive(message())
            self.assertEqual(result['this_call_trials'], 1)
            self.assertEqual(result['plan']['baseline_selected_action'], 'observe')
            self.assertEqual(result['plan']['selected_action'], 'walk')
            self.assertGreater(result['affect_after']['joy'], 0.)
            self.agent.close(); self.agent = AffectiveAgent(self.path)
            self.bridge = ArticulatedDialogue(self.agent)
            revision = self.agent.state()['revision']
            replay = self.bridge.receive(message())
            self.assertEqual(replay['measurement'], result['measurement'])
            self.assertEqual(replay['this_call_trials'], 0)
            self.assertEqual(self.agent.state()['revision'], revision)
            with self.assertRaises(Blocked): self.bridge.receive(message('m2'))
            execute.assert_called_once_with(2)

    def test_unknown_execution_blocks_repeat_and_allows_stop(self):
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial', side_effect=RuntimeError('interrupted')) as execute:
            with self.assertRaises(RuntimeError): self.bridge.receive(message())
            with self.assertRaises(Blocked): self.bridge.receive(message())
            self.bridge.receive(message('stop1', 'stop'))
            self.assertFalse(self.bridge.status()['enabled'])
            with self.assertRaises(Blocked): self.bridge.receive(message('new'))
            execute.assert_called_once()

    def test_measured_recovery_no_repeat_or_duplicate_feedback(self):
        original = self.bridge._save
        def interrupted(state):
            if state['messages']['m1']['stage'] == 'complete':
                raise RuntimeError('crash after feedback before final receipt')
            original(state)
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial', return_value=measurement()) as execute:
            with patch.object(self.bridge, '_save', side_effect=interrupted):
                with self.assertRaises(RuntimeError): self.bridge.receive(message())
            revision = self.agent.state()['revision']
            self.agent.close(); self.agent = AffectiveAgent(self.path)
            result = ArticulatedDialogue(self.agent).receive(message())
            self.assertTrue(result['replayed'])
            self.assertEqual(result['this_call_trials'], 0)
            self.assertEqual(self.agent.state()['revision'], revision)
            execute.assert_called_once()

    def test_failure_does_not_become_success_from_positive_appraisal(self):
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial', return_value=measurement(False)):
            result = self.bridge.receive(message())
        self.assertFalse(result['measurement']['walk_pass'])
        self.assertIn('کامل نشد', result['reply_fa'])
        self.assertGreater(result['affect_after']['frustration'], 0.)

    def test_observe_reflect_and_stop_do_not_move(self):
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial') as execute:
            for intent in ('observe', 'reflect', 'stop'):
                result = self.bridge.receive(message(intent, intent))
                self.assertEqual(result['this_call_trials'], 0)
            with self.assertRaises(Blocked): self.bridge.receive(message())
            execute.assert_not_called()
        self.assertEqual(self.bridge.status()['trials_remaining'], 1)

    def test_conflicting_replay_and_invalid_input(self):
        self.bridge.receive(message('o', 'observe'))
        altered = message('o', 'observe'); altered['text'] = 'different'
        with self.assertRaises(ValueError): self.bridge.receive(altered)
        for bad in (True, 0, 3, 2.0):
            invalid = message(); invalid['steps'] = bad
            with self.assertRaises(ValueError): self.bridge.receive(invalid)
        with self.assertRaises(Blocked): ArticulatedDialogue.enable(self.agent)

    def test_invalid_measurement_retains_unknown_barrier(self):
        invalid = measurement(); invalid['accepted_steps'] = 0
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial', return_value=invalid):
            with self.assertRaises(ValueError): self.bridge.receive(message())
        with self.assertRaises(Blocked): self.bridge.receive(message())
        self.assertEqual(self.bridge.status()['trials_remaining'], 0)

    def test_source_drift_and_tamper_rejected(self):
        with patch('examples.nasuraya_affect.articulated_dialogue.provenance', return_value={}):
            with self.assertRaises(Blocked): self.bridge.status()
        self.agent.db.execute('UPDATE meta SET value=replace(value,?,?) WHERE key=?', ('"enabled":true', '"enabled":false', KEY))
        with self.assertRaises(Blocked): self.bridge.status()

    def test_explicit_walk_uses_existing_gates_and_budget(self):
        with patch('examples.nasuraya_affect.articulated_dialogue.execute_trial', return_value=measurement()) as execute:
            result = self.bridge.receive(message(intent='walk'))
            self.assertEqual(result['plan']['selected_action'], 'walk')
            self.assertEqual(result['plan']['baseline_selected_action'], 'walk')
            self.assertEqual(result['this_call_trials'], 1)
            with self.assertRaises(Blocked): self.bridge.receive(message('next', 'walk'))
            execute.assert_called_once_with(2)

    def test_lock_rejects_concurrent_caller(self):
        from examples.nasuraya_agent_loop.guided import _session_lock
        with _session_lock(self.path):
            with self.assertRaises(BlockingIOError): self.bridge.receive(message())
        self.assertEqual(self.agent.state()['revision'], 0)


if __name__ == '__main__': unittest.main()
