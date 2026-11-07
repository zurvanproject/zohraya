"""Behavior, causal coupling, replay, and restoration checks using real V2 fixtures."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

from synthetic_fixture import prepare_defaults, synthetic_body
from persistent_embodiment_v1 import digest, instant
from neuropelvic import NeuroPelvic
from neuropelvic_body import NeuroPelvicBody, model_payload, restore_model


def signal(**kwargs):
    return dict(source_id='synthetic-neuropelvic-test', kind='declared_simulated_input',
                intensity=.95, rhythm=.7, breath_cue=.8, attention=.7, **kwargs)


def advance(bridge, neuro=None, **kwargs):
    return bridge.cycle(event_id='test-' + str(bridge.revision + 1),
        at_utc=(instant(bridge.body.owner.wall_utc) + timedelta(seconds=1)).isoformat(),
        duration_s=1., neuro=neuro, expected_revision=bridge.revision, **kwargs)


class BodyBridgeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()
        cls.template = synthetic_body()

    def bridge(self, **kwargs):
        return NeuroPelvicBody(deepcopy(self.template), **kwargs)

    def test_attach_preserves_native_stocks_and_checkpoint(self):
        body = deepcopy(self.template)
        before = body.checkpoint()
        wrapper = NeuroPelvicBody(body)
        self.assertEqual(wrapper.body.checkpoint(), before)
        self.assertEqual(wrapper.model.state.time, 0.)

    def test_one_owner_advance_and_matching_clocks(self):
        wrapper = self.bridge()
        receipt = advance(wrapper, signal(start=True))
        self.assertTrue(receipt['start_accepted'])
        self.assertEqual(receipt['owner_ticks'], 10)
        self.assertAlmostEqual(receipt['body_time_after_s'] - receipt['body_time_before_s'], 1.)
        self.assertEqual(receipt['neuropelvic']['time'], 1.)
        self.assertTrue(receipt['audit']['same_owner_ticks'])
        self.assertLess(receipt['audit']['energy_error_J'], 5e-5)
        self.assertLess(receipt['audit']['water_error_L'], 1e-8)

    def test_missing_control_never_starts_cycle(self):
        wrapper = self.bridge()
        receipt = advance(wrapper)
        self.assertEqual(receipt['neuropelvic']['phase'], 'baseline')
        self.assertEqual(receipt['peak_count'], 0)
        self.assertFalse(receipt['policy_requested_slow_breath'])

    def test_real_body_breathing_changes_when_coupling_enabled(self):
        coupled, ablated = self.bridge(), self.bridge(coupling=False)
        actual_coupled = actual_ablated = None
        for index in range(8):
            request = signal(start=index == 0)
            actual_coupled = advance(coupled, request)
            actual_ablated = advance(ablated, request)
        self.assertEqual(actual_coupled['requested_action'], 'slow_breath')
        self.assertEqual(actual_coupled['selected_action'], 'slow_breath')
        self.assertGreater(actual_coupled['achieved_slow_breath_ticks'], 0)
        self.assertEqual(actual_ablated['selected_action'], 'observe')
        self.assertLess(actual_coupled['after_body']['RR'], actual_ablated['after_body']['RR'])
        self.assertEqual(coupled.model.peak_count, 1)

    def test_explicit_native_action_is_not_replaced(self):
        wrapper = self.bridge()
        receipt = advance(wrapper, signal(start=True), requested='observe')
        self.assertEqual(receipt['requested_action'], 'observe')
        self.assertFalse(receipt['policy_requested_slow_breath'])

    def test_explicit_stop_cuts_sidecar_signal(self):
        wrapper = self.bridge()
        advance(wrapper, signal(start=True))
        receipt = advance(wrapper, signal(stop=True))
        self.assertEqual(receipt['neuropelvic']['phase'], 'release')
        self.assertEqual(receipt['neuropelvic']['resonance'], 0)
        self.assertFalse(receipt['body_feedback']['gate_open'])

    def test_native_pain_is_feedback_not_a_user_supplied_sidecar_number(self):
        wrapper = self.bridge()
        advance(wrapper, signal(start=True), external={'native': {'pain': [
            {'id': 'synthetic-pain', 'location': 'chest_wall_L', 'intensity': 1.,
             'quality': 'pressure', 'cause': 'synthetic-fixture', 'duration_s': 10.}]}})
        receipt = advance(wrapper, signal())
        self.assertGreaterEqual(receipt['body_feedback']['pain'], .35)
        self.assertFalse(receipt['body_feedback']['gate_open'])
        self.assertEqual(receipt['neuropelvic']['phase'], 'release')

    def test_same_event_replay_does_not_advance_either_clock(self):
        wrapper = self.bridge()
        args = dict(event_id='replay', at_utc='2026-01-01T00:00:08+00:00',
                    duration_s=1., neuro=signal(start=True), expected_revision=0)
        first = wrapper.cycle(**args)
        checkpoint = wrapper.checkpoint()
        self.assertEqual(first, wrapper.cycle(**args))
        self.assertEqual(wrapper.checkpoint(), checkpoint)
        with self.assertRaises(ValueError):
            wrapper.cycle(**{**args, 'neuro': signal(start=False)})

    def test_cold_json_restart_continues_identically(self):
        original = self.bridge()
        advance(original, signal(start=True))
        restored = NeuroPelvicBody.restore(json.loads(json.dumps(original.checkpoint(), sort_keys=True)))
        self.assertEqual(original.results, restored.results)
        self.assertEqual(original.checkpoint(), restored.checkpoint())
        left, right = advance(original, signal()), advance(restored, signal())
        self.assertEqual(left, right)
        self.assertEqual(original.checkpoint(), restored.checkpoint())

    def test_invalid_inputs_are_atomic(self):
        wrapper = self.bridge()
        before = wrapper.checkpoint()
        invalid = [
            {'start': True},
            {'source_id': 'x', 'kind': 'declared_simulated_input', 'intensity': float('nan')},
            {'source_id': 'x', 'kind': 'declared_simulated_input', 'rhythm': True},
            {'source_id': 'x', 'kind': 'declared_simulated_input', 'start': 1},
            {'source_id': 'x', 'kind': 'declared_simulated_input', 'pain': .5},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                advance(wrapper, value)
            self.assertEqual(wrapper.checkpoint(), before)

    def test_checksum_and_source_fingerprint_are_enforced(self):
        wrapper = self.bridge()
        envelope = wrapper.checkpoint()
        envelope['payload']['revision'] = 2
        with self.assertRaises(ValueError):
            NeuroPelvicBody.restore(envelope)
        envelope = wrapper.checkpoint()
        envelope['payload']['source_fingerprints']['neuropelvic.py'] = '0' * 64
        envelope['sha256'] = digest(envelope['payload'])
        with self.assertRaises(ValueError):
            NeuroPelvicBody.restore(envelope)

    def test_external_body_advance_is_detected(self):
        wrapper = self.bridge()
        wrapper.body.cycle(event_id='outside', at_utc='2026-01-01T00:00:08+00:00',
                           duration_s=1., requested='observe')
        with self.assertRaises(ValueError):
            wrapper.checkpoint()

    def test_model_restore_rejects_out_of_range_or_boolean_state(self):
        model = NeuroPelvic()
        model.start_cycle()
        model.run(1., intensity=.95)
        for key, value in [('arousal', 1.1), ('arousal', True), ('time', float('nan'))]:
            state = model_payload(model)
            state['state'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                restore_model(state)
        state = model_payload(model)
        state['peak_count'] = True
        with self.assertRaises(ValueError):
            restore_model(state)

    def test_stale_writer_is_rejected(self):
        wrapper = self.bridge()
        advance(wrapper)
        before = wrapper.checkpoint()
        with self.assertRaises(ValueError):
            wrapper.cycle(event_id='stale', at_utc='2026-01-01T00:00:09+00:00',
                          duration_s=1., expected_revision=0)
        self.assertEqual(wrapper.checkpoint(), before)


if __name__ == '__main__':
    unittest.main()
