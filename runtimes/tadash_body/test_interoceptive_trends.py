"""Source parity, temporal evidence, replay and real native-body integration."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import random
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from interoceptive_trends import CONFIG, InteroceptiveTrends, InteroceptiveBody
from river_page_hinkley import PageHinkley
from river_page_hinkley_support import stats, DriftDetector
from neuropelvic_body import NeuroPelvicBody
from persistent_embodiment_v1 import digest, instant
from synthetic_fixture import prepare_defaults, synthetic_body


def sample(monitor, i, hr=70., rr=15.):
    return monitor.observe(event_id=str(i), time_s=float(i), values=dict(HR=hr, RR=rr))


def request(body):
    bridge = body.bridge
    return dict(event_id='observed-' + str(bridge.revision + 1),
                at_utc=(instant(bridge.body.owner.wall_utc) + timedelta(seconds=1)).isoformat(),
                duration_s=1., expected_revision=bridge.revision)


class DetectorChecks(unittest.TestCase):
    def test_vendored_source_has_only_documented_import_change(self):
        root = Path(__file__).resolve().parent
        upstream = (root/'third_party/river/page_hinkley_upstream.py.txt').read_text()
        adapted = (root/'river_page_hinkley.py').read_text().split('\n', 1)[1]
        self.assertEqual(adapted, upstream.replace('from river import stats\nfrom river.base import DriftDetector',
                         'from river_page_hinkley_support import stats, DriftDetector'))

    def test_unchanged_upstream_detector_matches_every_update(self):
        source = (Path(__file__).resolve().parent/'third_party/river/page_hinkley_upstream.py.txt').read_text()
        package, base = ModuleType('river'), ModuleType('river.base')
        package.stats, base.DriftDetector = stats, DriftDetector
        namespace = {}
        with patch.dict(sys.modules, {'river': package, 'river.base': base}):
            exec(compile(source, 'pinned_upstream_page_hinkley', 'exec'), namespace)
        rng = random.Random(712)
        stream = [rng.gauss((i//250)%3, .08) for i in range(2000)]
        for mode in ('up', 'down', 'both'):
            actual = PageHinkley(**dict(CONFIG, mode=mode))
            reference = namespace['PageHinkley'](**dict(CONFIG, mode=mode))
            for value in stream:
                actual.update(value); reference.update(value)
                self.assertEqual(actual.drift_detected, reference.drift_detected)
                for key in ('_sum_increase', '_sum_decrease', '_min_increase', '_max_decrease'):
                    self.assertEqual(getattr(actual, key), getattr(reference, key))
                self.assertEqual(actual._x_mean.get(), reference._x_mean.get())

    def test_river_documented_example_detects_at_1006(self):
        rng, detector = random.Random(12345), PageHinkley()
        stream = rng.choices([0, 1], k=1000) + rng.choices(range(4, 8), k=1000)
        changes = []
        for i, value in enumerate(stream):
            detector.update(value)
            if detector.drift_detected:
                changes.append(i)
        self.assertEqual(changes, [1006])

    def test_constant_stream_and_warmup(self):
        monitor = InteroceptiveTrends()
        records = [sample(monitor, i) for i in range(1, 101)]
        self.assertEqual(records[18]['channels']['HR']['status'], 'warming_up')
        self.assertEqual(records[19]['channels']['HR']['status'], 'no_change_detected')
        self.assertFalse(any(c['direction'] for r in records for c in r['channels'].values()))

    def test_both_directions_are_reported(self):
        for sign, direction in ((1, 'up'), (-1, 'down')):
            monitor = InteroceptiveTrends()
            records = [sample(monitor, i, 70. + (10. * sign if i > 60 else 0.)) for i in range(1, 101)]
            changes = [r for r in records if r['channels']['HR']['direction']]
            self.assertTrue(changes)
            self.assertEqual(changes[0]['channels']['HR']['direction'], direction)
            self.assertLessEqual(changes[0]['sample_count'] - 61, 20)
            self.assertFalse(any(r['channels']['RR']['direction'] for r in records))

    def test_json_continuation_preserves_post_change_reset(self):
        first = InteroceptiveTrends()
        for i in range(1, 90):
            r = sample(first, i, 80. if i > 60 else 70.)
            if r['channels']['HR']['direction']:
                break
        restored = InteroceptiveTrends.restore(json.loads(json.dumps(first.checkpoint(), allow_nan=False)))
        for j in range(i+1, i+30):
            self.assertEqual(sample(first, j, 80.), sample(restored, j, 80.))
        self.assertEqual(first.checkpoint(), restored.checkpoint())

    def test_empty_checkpoint_is_standard_json(self):
        monitor = InteroceptiveTrends()
        state = json.loads(json.dumps(monitor.checkpoint(), allow_nan=False))
        self.assertEqual(InteroceptiveTrends.restore(state).checkpoint(), state)

    def test_invalid_second_channel_is_atomic(self):
        for value in (True, None, float('nan'), float('inf'), -1.):
            monitor = InteroceptiveTrends()
            sample(monitor, 1)
            before = monitor.checkpoint()
            with self.assertRaises(ValueError):
                sample(monitor, 2, rr=value)
            self.assertEqual(monitor.checkpoint(), before)

    def test_cadence_duplicates_and_missing_signal_rejected(self):
        monitor = InteroceptiveTrends()
        sample(monitor, 1)
        before = monitor.checkpoint()
        for time_s in (1, 1.5, 3, True):
            with self.assertRaises(ValueError):
                sample(monitor, time_s)
        with self.assertRaises(ValueError):
            monitor.observe(event_id='2', time_s=2, values={'HR': 70})
        with self.assertRaises(ValueError):
            monitor.observe(event_id='1', time_s=2, values={'HR': 70, 'RR': 15})
        self.assertEqual(monitor.checkpoint(), before)

    def test_corrupt_detector_counts_rejected(self):
        monitor = InteroceptiveTrends()
        sample(monitor, 1)
        for n in (True, -1, 2):
            state = monitor.checkpoint()
            state['detectors']['HR']['n'] = n
            with self.assertRaises(ValueError):
                InteroceptiveTrends.restore(state)


class NativeObserverChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_defaults()
        cls.template = synthetic_body()

    def body(self):
        return InteroceptiveBody(NeuroPelvicBody(deepcopy(self.template)))

    def test_attachment_and_cycle_preserve_unobserved_body(self):
        plain = NeuroPelvicBody(deepcopy(self.template))
        observed = InteroceptiveBody(deepcopy(plain))
        self.assertEqual(plain.checkpoint(), observed.bridge.checkpoint())
        for _ in range(3):
            kwargs = request(observed)
            actual = observed.cycle(**kwargs)
            obs = actual.pop('interoception')
            self.assertEqual(actual, plain.cycle(**kwargs))
            self.assertEqual(plain.checkpoint(), observed.bridge.checkpoint())
            self.assertEqual(obs['channels']['HR']['value'], actual['after_body']['HR'])
            self.assertEqual(actual['owner_ticks'], 10)

    def test_replay_does_not_duplicate_observation(self):
        body = self.body()
        kwargs = request(body)
        receipt = body.cycle(**kwargs)
        body.cycle(**request(body))
        before = body.checkpoint()
        self.assertEqual(body.cycle(**kwargs), receipt)
        self.assertEqual(body.checkpoint(), before)

    def test_conflicting_replay_is_atomic(self):
        body = self.body()
        kwargs = request(body)
        body.cycle(**kwargs)
        before = body.checkpoint()
        with self.assertRaises(ValueError):
            body.cycle(**dict(kwargs, requested='walk'))
        self.assertEqual(body.checkpoint(), before)

    def test_json_cold_restore_and_continue(self):
        body = self.body()
        for _ in range(3):
            body.cycle(**request(body))
        resumed = InteroceptiveBody.restore(json.loads(json.dumps(body.checkpoint(), sort_keys=True)))
        self.assertEqual(resumed.checkpoint(), body.checkpoint())
        kwargs = request(body)
        self.assertEqual(body.cycle(**kwargs), resumed.cycle(**kwargs))
        self.assertEqual(body.checkpoint(), resumed.checkpoint())

    def test_wrong_cadence_does_not_execute_body(self):
        body = self.body()
        before = body.checkpoint()
        with self.assertRaises(ValueError):
            body.cycle(**dict(request(body), duration_s=.5))
        self.assertEqual(body.checkpoint(), before)

    def test_external_advance_is_detected(self):
        body = self.body()
        body.bridge.cycle(**request(body))
        with self.assertRaises(ValueError):
            body.cycle(**request(body))

    def test_tampered_observer_envelope_rejected(self):
        body = self.body()
        body.cycle(**request(body))
        envelope = body.checkpoint()
        envelope['payload']['monitor']['sample_count'] += 1
        with self.assertRaises(ValueError):
            InteroceptiveBody.restore(envelope)
        envelope['sha256'] = digest(envelope['payload'])
        with self.assertRaises(ValueError):
            InteroceptiveBody.restore(envelope)

    def test_pre_attachment_replay_is_not_an_observation(self):
        body = self.body()
        kwargs = request(body)
        body.bridge.cycle(**kwargs)
        attached = InteroceptiveBody(body.bridge)
        before = attached.checkpoint()
        with self.assertRaises(ValueError):
            attached.cycle(**kwargs)
        self.assertEqual(attached.checkpoint(), before)


if __name__ == '__main__':
    unittest.main()
