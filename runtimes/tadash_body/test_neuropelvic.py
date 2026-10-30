"""Behavioral checks for the standalone Neuro-Pelvic v0.2 simulator."""
from dataclasses import asdict
from math import isfinite
import unittest

from neuropelvic import CHAKRAS, NORMALIZED_FIELDS, NeuroPelvic


class NeuroPelvicTest(unittest.TestCase):
    def started(self):
        model = NeuroPelvic()
        self.assertTrue(model.start_cycle())
        return model

    def reach_peak(self):
        model = self.started()
        for _ in range(150):
            if model.step(intensity=.95, rhythm=.7)['phase'] == 'peak':
                return model
        self.fail('intentional high-input scenario did not reach peak')

    def test_range(self):
        model = self.started()
        for state in model.run(60, intensity=1, rhythm=1, breath_cue=1, attention=1):
            for key in NORMALIZED_FIELDS:
                self.assertTrue(isfinite(state[key]) and 0 <= state[key] <= 1, key)
            self.assertEqual(len(state['chakra']), len(CHAKRAS))
            self.assertTrue(all(isfinite(v) and 0 <= v <= 1 for v in state['chakra']))

    def test_phase(self):
        model = self.started()
        phases = {s['phase'] for s in model.run(60, intensity=.95, rhythm=.7)}
        self.assertEqual(phases, {'baseline', 'rising', 'peak', 'release', 'recovery'})
        self.assertEqual(model.peak_count, 1)

    def test_recovery(self):
        model = self.started()
        seq = model.run(60, intensity=.95, rhythm=.7)
        self.assertGreater(max(s['pelvic_tone'] for s in seq), seq[-1]['pelvic_tone'])
        self.assertEqual(seq[-1]['phase'], 'baseline')
        self.assertLessEqual(model.baseline_residual(), model.REST_TOLERANCE)

    def test_invalid_dt(self):
        for value in (0, -1, 1.01, float('nan'), float('inf'), True, '0.1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                NeuroPelvic().step(dt=value)

    def test_idle_does_not_invent_peaks(self):
        model = NeuroPelvic()
        trace = model.run(60, rhythm=0, intensity=0)
        self.assertEqual(model.peak_count, 0)
        self.assertEqual({s['phase'] for s in trace}, {'baseline'})
        self.assertEqual(model.events, [])

    def test_music_and_high_input_cannot_start_idle_cycle(self):
        model = NeuroPelvic()
        trace = model.run(60, rhythm=1, intensity=1)
        self.assertEqual({s['phase'] for s in trace}, {'baseline'})
        self.assertEqual(max(s['resonance'] for s in trace), 0)

    def test_music_alone_cannot_produce_peak_after_start(self):
        model = self.started()
        model.run(60, rhythm=1, intensity=0)
        self.assertEqual(model.peak_count, 0)
        self.assertEqual(model.state.phase, 'baseline')

    def test_weak_input_times_out_without_peak(self):
        model = self.started()
        model.run(60, intensity=.25, rhythm=.2)
        self.assertEqual(model.peak_count, 0)
        self.assertIn('rising_timeout', [e['reason'] for e in model.events])
        self.assertEqual(model.state.phase, 'baseline')

    def test_peak_requires_threshold_hold(self):
        model = self.started()
        for _ in range(300):
            snapshot = model.step(intensity=.95, rhythm=.7)
            if snapshot['arousal'] >= model.PEAK_THRESHOLD:
                first_crossing = snapshot['time']
                break
        else:
            self.fail('threshold was not reached')
        self.assertEqual(model.peak_count, 0)
        model.run(.7, intensity=.95, rhythm=.7)
        self.assertEqual(model.peak_count, 0)
        model.run(2, intensity=.95, rhythm=.7)
        event = next(e for e in model.events if e['to'] == 'peak')
        self.assertGreaterEqual(event['time'] - first_crossing, 1.1)
        self.assertGreaterEqual(event['arousal'], model.PEAK_THRESHOLD)

    def test_one_peak_until_explicit_restart(self):
        model = self.started()
        model.run(120, intensity=1, rhythm=1)
        self.assertEqual(model.peak_count, 1)
        self.assertTrue(model.start_cycle())
        model.run(60, intensity=1, rhythm=1)
        self.assertEqual(model.peak_count, 2)

    def test_reentry_is_blocked_during_active_cycle_and_recovery(self):
        model = self.reach_peak()
        self.assertFalse(model.start_cycle())
        for _ in range(300):
            if model.step(intensity=.95, rhythm=.7)['phase'] == 'recovery':
                break
        else:
            self.fail('recovery was not reached')
        self.assertFalse(model.start_cycle())
        model.run(60, intensity=1, rhythm=1)
        self.assertEqual(model.peak_count, 1)

    def test_interruptions_cut_signal_and_allow_restoration(self):
        triggers = ({'pain': .8}, {'safe': False}, {'balance': .2}, {'stop': True})
        for trigger in triggers:
            for when in ('rising', 'peak'):
                with self.subTest(trigger=trigger, phase=when):
                    model = self.reach_peak() if when == 'peak' else self.started()
                    if when == 'rising':
                        model.run(1, intensity=.95, rhythm=.7)
                    count = model.peak_count
                    state = model.step(intensity=1, rhythm=1, **trigger)
                    self.assertEqual(state['phase'], 'release')
                    self.assertEqual(state['sacral_signal'], 0)
                    self.assertEqual(state['resonance'], 0)
                    model.run(60, intensity=1, rhythm=1)
                    self.assertEqual(model.peak_count, count)
                    self.assertEqual(model.state.phase, 'baseline')

    def test_input_withdrawal_ends_peak_without_retrigger(self):
        model = self.reach_peak()
        state = model.step(intensity=0, rhythm=1)
        self.assertEqual(state['phase'], 'release')
        self.assertEqual(state['resonance'], 0)
        model.run(60, intensity=1, rhythm=1)
        self.assertEqual(model.peak_count, 1)

    def test_recovery_signal_stays_off_with_continuing_music(self):
        model = self.started()
        trace = model.run(60, intensity=1, rhythm=1)
        for state in trace:
            if state['phase'] in ('release', 'recovery', 'baseline'):
                self.assertEqual(state['sacral_signal'], 0)
                self.assertEqual(state['resonance'], 0)

    def test_peak_is_time_bounded(self):
        model = self.started()
        model.run(60, intensity=1, rhythm=1)
        entry = next(e['time'] for e in model.events if e['to'] == 'peak')
        exit_time = next(e['time'] for e in model.events if e['reason'] == 'peak_complete')
        self.assertAlmostEqual(exit_time - entry, model.PEAK_SECONDS, places=6)

    def test_arousal_decreases_through_release_and_recovery(self):
        model = self.started()
        trace = model.run(60, intensity=1, rhythm=1)
        restorative = [s['arousal'] for s in trace if s['phase'] in ('release', 'recovery')]
        self.assertTrue(all(b <= a + 1e-12 for a, b in zip(restorative, restorative[1:])))

    def test_settling_cues_reduce_residual_at_fixed_time(self):
        plain, cued = self.started(), self.started()
        plain.run(10, intensity=.95, rhythm=.7)
        cued.run(10, intensity=.95, rhythm=.7, breath_cue=.8, attention=.7)
        self.assertLess(cued.state.arousal, plain.state.arousal)
        self.assertLess(cued.state.pelvic_tone, plain.state.pelvic_tone)
        # Fatigue can still determine the time of complete restoration.
        self.assertGreater(cued.state.fatigue, 0)

    def test_invalid_inputs_do_not_mutate_state(self):
        for key in ('rhythm', 'intensity', 'breath_cue', 'attention', 'pain', 'balance'):
            for value in (float('nan'), float('inf'), float('-inf'), None, True, '1'):
                with self.subTest(key=key, value=value):
                    model = self.started()
                    before = (asdict(model.state), list(model.events), model.peak_count)
                    with self.assertRaises(ValueError):
                        model.step(**{key: value})
                    self.assertEqual((asdict(model.state), model.events, model.peak_count), before)

    def test_boolean_gates_require_booleans(self):
        for key in ('safe', 'stop'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                NeuroPelvic().step(**{key: 1})

    def test_finite_out_of_range_inputs_are_bounded(self):
        model = self.started()
        trace = model.run(60, intensity=100, rhythm=-100)
        self.assertEqual(model.peak_count, 1)
        for state in trace:
            self.assertTrue(all(0 <= state[key] <= 1 for key in NORMALIZED_FIELDS))

    def test_run_duration_is_exact_and_zero_does_not_advance(self):
        model = NeuroPelvic()
        self.assertEqual(model.run(0), [])
        self.assertEqual(model.state.time, 0)
        trace = model.run(.35, dt=.1)
        self.assertEqual(len(trace), 4)
        self.assertAlmostEqual(model.state.time, .35, places=9)

    def test_invalid_run_requests(self):
        for seconds in (-1, float('nan'), float('inf'), True):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                NeuroPelvic().run(seconds)
        with self.assertRaises(ValueError):
            NeuroPelvic().run(0, rhythm=float('nan'))

    def test_timestep_variants_preserve_cycle_and_restoration(self):
        models = []
        for dt in (.05, .1, .2, 1.):
            model = self.started()
            model.run(60, dt=dt, intensity=.95, rhythm=.7, breath_cue=.8, attention=.7)
            self.assertEqual(model.peak_count, 1)
            self.assertEqual(model.state.phase, 'baseline')
            self.assertLessEqual(model.baseline_residual(), model.REST_TOLERANCE)
            models.append(model)
        times = [next(e['time'] for e in m.events if e['to'] == 'peak') for m in models]
        self.assertLessEqual(max(times) - min(times), .06)


if __name__ == '__main__':
    unittest.main()
