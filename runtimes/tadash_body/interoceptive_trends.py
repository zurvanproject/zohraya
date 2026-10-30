"""Opt-in streaming trend receipts from actual native simulator outputs.

Signals are sampled exactly once per simulated second. A Page-Hinkley change
means a shift of a running mean; it does not mean disease, danger, an unexpected
event, or successful recovery. The observer has no actuator authority.
"""
from copy import deepcopy
import hashlib
import json
import math
from numbers import Real
from pathlib import Path

from river_page_hinkley import PageHinkley
from neuropelvic_body import NeuroPelvicBody, wire
from persistent_embodiment_v1 import digest

SCHEMA = 'tadash-interoceptive-trends/1'
CONFIG = dict(min_instances=20, delta=.01, threshold=5., alpha=.9999, mode='both')
SCALES = dict(HR=10., RR=3.)
PH_FIELDS = ('_sum_increase', '_sum_decrease', '_min_increase', '_max_decrease')


def number(value, label, low=-1e9, high=1e9):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(label + ': finite real required')
    if not low <= value <= high:
        raise ValueError(label + ': outside supported range')
    return float(value)


def integer(value, label, low=0):
    if type(value) is not int or value < low:
        raise ValueError(label + ': integer required')
    return value


def source_fingerprints():
    root = Path(__file__).resolve().parent
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in
            ('interoceptive_trends.py', 'river_page_hinkley.py',
             'river_page_hinkley_support.py')}


def detector_state(detector):
    return dict(n=int(detector._x_mean.n), mean=detector._x_mean.get(),
                drift=detector.drift_detected,
                **{k: (getattr(detector, k) if math.isfinite(getattr(detector, k)) else None)
                   for k in PH_FIELDS})


def restore_detector(state, sample_count):
    if not isinstance(state, dict) or set(state) != {'n', 'mean', 'drift', *PH_FIELDS}:
        raise ValueError('detector fields mismatch')
    n = integer(state['n'], 'detector sample count')
    if n > sample_count or (sample_count > 0 and n == 0):
        raise ValueError('detector sample count mismatch')
    if type(state['drift']) is not bool or (state['drift'] and n < CONFIG['min_instances']):
        raise ValueError('invalid detector flag')
    obj = PageHinkley(**CONFIG)
    obj._x_mean.n = float(n)
    obj._x_mean._mean = number(state['mean'], 'mean')
    obj._drift_detected = state['drift']
    for key in PH_FIELDS:
        value = state[key]
        if n == 0 and key in ('_min_increase', '_max_decrease'):
            if value is not None:
                raise ValueError('empty detector extrema must be null')
            value = float('inf') if key == '_min_increase' else float('-inf')
        else:
            value = number(value, key, -1e15, 1e15)
        setattr(obj, key, value)
    if n == 0 and (obj._x_mean.get() != 0 or obj._sum_increase != 0 or obj._sum_decrease != 0):
        raise ValueError('empty detector has nonzero state')
    if n and (obj._min_increase > obj._sum_increase or obj._max_decrease < obj._sum_decrease):
        raise ValueError('inconsistent detector extrema')
    return obj


class InteroceptiveTrends:
    def __init__(self):
        self.detectors = {key: PageHinkley(**CONFIG) for key in SCALES}
        self.sample_count = 0
        self.last_time_s = None
        self.last_event = None
        self.last_values = None
        self.last_receipt = None

    def observe(self, *, event_id, time_s, values, context=None):
        if not isinstance(event_id, str) or not event_id or len(event_id) > 100:
            raise ValueError('bounded event id required')
        time_s = number(time_s, 'simulator time', 0, 1e9)
        if not isinstance(values, dict) or set(values) != set(SCALES):
            raise ValueError('exact HR and RR measurements required')
        values = {key: number(values[key], key, 0, 1e6) for key in SCALES}
        if self.last_time_s is not None and abs(time_s - self.last_time_s - 1.) > 1e-7:
            raise ValueError('observer requires one-second sampling; no interpolation')
        if event_id == self.last_event:
            raise ValueError('duplicate observation; replay through the body wrapper')
        if context is not None and (not isinstance(context, dict) or
                set(context) != {'selected_action', 'phase'} or
                any(not isinstance(v, str) or len(v) > 40 for v in context.values())):
            raise ValueError('bounded action and phase context required')
        # All inputs are checked before either channel changes.
        channels = {}
        for key, detector in self.detectors.items():
            reference = detector._x_mean.get() * SCALES[key] if detector._x_mean.n else None
            restarting = detector.drift_detected
            detector.update(values[key] / SCALES[key])
            increase = detector._sum_increase - detector._min_increase
            decrease = detector._max_decrease - detector._sum_decrease
            changed = detector.drift_detected
            direction = ('up' if increase >= decrease else 'down') if changed else None
            channels[key] = dict(value=values[key], unit='per_minute',
                reference_mean_before=reference,
                reference_restarted_after_change=restarting,
                segment_samples=int(detector._x_mean.n),
                status='change_detected' if changed else
                       'warming_up' if detector._x_mean.n < CONFIG['min_instances'] else 'no_change_detected',
                direction=direction, increase_score=increase, decrease_score=decrease)
        self.sample_count += 1
        self.last_time_s, self.last_event, self.last_values = time_s, event_id, values
        self.last_receipt = dict(schema=SCHEMA, source='native_simulator_after_cycle',
            event_id=event_id, sample_count=self.sample_count, sampled_at_body_s=time_s,
            interval_s=1., channels=channels, context=deepcopy(context),
            interpretation='running-mean shift, not a diagnosis or recovery certificate')
        return deepcopy(self.last_receipt)

    def checkpoint(self):
        return wire(dict(schema=SCHEMA, config=CONFIG, scales=SCALES,
            sample_count=self.sample_count, last_time_s=self.last_time_s,
            last_event=self.last_event, last_values=self.last_values,
            last_receipt=self.last_receipt,
            detectors={k: detector_state(v) for k, v in self.detectors.items()}))

    @classmethod
    def restore(cls, payload):
        obj = cls()
        if not isinstance(payload, dict) or set(payload) != set(obj.checkpoint()):
            raise ValueError('observer checkpoint fields mismatch')
        if payload['schema'] != SCHEMA or payload['config'] != CONFIG or payload['scales'] != SCALES:
            raise ValueError('observer configuration mismatch')
        obj.sample_count = integer(payload['sample_count'], 'observer samples')
        if not isinstance(payload['detectors'], dict) or set(payload['detectors']) != set(SCALES):
            raise ValueError('observer channels mismatch')
        obj.detectors = {k: restore_detector(v, obj.sample_count) for k, v in payload['detectors'].items()}
        if obj.sample_count == 0:
            if any(payload[k] is not None for k in ('last_time_s', 'last_event', 'last_values', 'last_receipt')):
                raise ValueError('empty observer has a receipt')
        else:
            obj.last_time_s = number(payload['last_time_s'], 'last time', 0, 1e9)
            if not isinstance(payload['last_event'], str) or not 1 <= len(payload['last_event']) <= 100:
                raise ValueError('last event required')
            obj.last_event = payload['last_event']
            values = payload['last_values']
            if not isinstance(values, dict) or set(values) != set(SCALES):
                raise ValueError('last measurements required')
            obj.last_values = {k: number(v, k, 0, 1e6) for k, v in values.items()}
            receipt = payload['last_receipt']
            if not isinstance(receipt, dict) or receipt.get('event_id') != obj.last_event or type(receipt.get('sample_count')) is not int or receipt['sample_count'] != obj.sample_count or receipt.get('sampled_at_body_s') != obj.last_time_s:
                raise ValueError('last observation mismatch')
            obj.last_receipt = deepcopy(receipt)
        return obj


class InteroceptiveBody:
    """Wrap an existing NeuroPelvicBody; observe each executed one-second cycle."""
    def __init__(self, bridge):
        if not isinstance(bridge, NeuroPelvicBody):
            raise ValueError('existing NeuroPelvicBody required')
        self.bridge = bridge
        self.monitor = InteroceptiveTrends()
        self.origin_revision = bridge.revision
        self.receipts = {}

    def _check(self):
        self.bridge._check_clocks()
        if self.bridge.revision != self.origin_revision + self.monitor.sample_count:
            raise ValueError('body advanced outside observer owner')
        if self.monitor.last_time_s is not None and abs(self.monitor.last_time_s - self.bridge.body_time()) > 1e-7:
            raise ValueError('observer/body clocks diverged')

    def cycle(self, **kwargs):
        duration = number(kwargs.get('duration_s', 1.), 'sample duration')
        if duration != 1.:
            raise ValueError('observed body cycles must be exactly one second')
        self._check()
        work = deepcopy(self)
        before = work.bridge.revision
        result = work.bridge.cycle(**kwargs)
        event_id = result['event_id']
        if work.bridge.revision == before:
            if event_id not in work.receipts:
                raise ValueError('event predates observer attachment or receipt was archived')
            return deepcopy(work.receipts[event_id])
        result['interoception'] = work.monitor.observe(event_id=event_id,
            time_s=result['body_time_after_s'],
            values={k: result['after_body'][k] for k in SCALES},
            context=dict(selected_action=result['selected_action'], phase=result['neuropelvic']['phase']))
        work.receipts[event_id] = deepcopy(result)
        work.receipts = dict(list(work.receipts.items())[-16:])
        work._check()
        self.__dict__ = work.__dict__
        return deepcopy(result)

    def checkpoint(self):
        self._check()
        payload = wire(dict(schema=SCHEMA, sources=source_fingerprints(),
            bridge=self.bridge.checkpoint(), monitor=self.monitor.checkpoint(),
            origin_revision=self.origin_revision, receipts=self.receipts))
        return dict(payload=payload, sha256=digest(payload))

    @classmethod
    def restore(cls, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {'payload', 'sha256'} or digest(envelope['payload']) != envelope['sha256']:
            raise ValueError('observer envelope checksum mismatch')
        p = envelope['payload']
        if not isinstance(p, dict) or set(p) != {'schema', 'sources', 'bridge', 'monitor', 'origin_revision', 'receipts'} or p['schema'] != SCHEMA or p['sources'] != source_fingerprints():
            raise ValueError('observer source/schema mismatch')
        obj = cls(NeuroPelvicBody.restore(p['bridge']))
        obj.monitor = InteroceptiveTrends.restore(p['monitor'])
        obj.origin_revision = integer(p['origin_revision'], 'origin revision')
        if not isinstance(p['receipts'], dict) or len(p['receipts']) != min(obj.monitor.sample_count, 16):
            raise ValueError('observer receipt cache mismatch')
        obj.receipts = {}
        for key, receipt in p['receipts'].items():
            base = deepcopy(receipt)
            observation = base.pop('interoception', None)
            if base != obj.bridge.results.get(key) or not isinstance(observation, dict) or observation.get('event_id') != key or type(observation.get('sample_count')) is not int or observation['sample_count'] != base['revision'] - obj.origin_revision:
                raise ValueError('observer/native receipt mismatch')
            obj.receipts[key] = deepcopy(receipt)
        obj.receipts = dict(sorted(obj.receipts.items(), key=lambda item: item[1]['revision']))
        if obj.monitor.sample_count and obj.receipts.get(obj.monitor.last_event, {}).get('interoception') != obj.monitor.last_receipt:
            raise ValueError('latest observer receipt mismatch')
        obj._check()
        return obj
