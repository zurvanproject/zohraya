"""Versioned, validation-gated energy residuals; original planner stays restorable.

Features contain only information available before an action. Actual selected
action is a diagnostic label, never a feature or a reason to omit an example.
Training, validation and frozen evaluation are explicit, irreversible stages.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from statistics import median

from .monitor import digest, NATIVE
from .planning import score as original_score, POLICY as PLANNING_POLICY, sources
from extension_state import sources as controller_sources

SCHEMA = 'nasuraya-energy-calibration/1'
POLICY = dict(min_train=3, min_validation=2, shrinkage=.5,
              correction_limit_J=250., required_gain=.05, max_examples=4096)


def fingerprints():
    # Detached calibrations must reject a different native kernel as well as a
    # different forecaster. Two generated fixture defaults are not source code.
    generated = {'initial_affect.json', 'trained_circuit.json'}
    native = {'native/'+str(p.relative_to(NATIVE)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(NATIVE.rglob('*'))
              if p.is_file() and p.suffix in ('.py', '.json') and p.name not in generated}
    return {**sources(), **native, **{'controller/'+k:v for k,v in controller_sources().items()},
            'energy.py': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('finite numeric energy value required')
    return value


def features(before, predicted, offset):
    """Both states are pre-action: current observation and saved projection."""
    if type(offset) is not int or offset < 0:
        raise ValueError('nonnegative forecast offset required')
    m = before['minimum']
    return dict(requested=predicted['requested'], posture=m['posture'],
                projected_posture=predicted['minimum']['posture'],
                forecast_age='first' if offset == 0 else 'early' if offset < 4 else 'late',
                sleep='high' if finite(m['sleep_pressure']) > .85 else 'ordinary',
                fatigue='high' if finite(m['fatigue']) > .52 else 'ordinary',
                pain='high' if finite(m['pain']) > .40 else 'ordinary')


def example(row):
    d = row['decision']; p = d['plan']; i = d['offset']
    series = p['candidates'][p['chosen']]['series']
    prior = p['initial'] if i == 0 else series[i-1]
    raw = finite(prior['fuel_J']) - finite(series[i]['fuel_J'])
    actual = finite(d['before']['fuel_J']) - finite(row['after']['fuel_J'])
    return dict(features=features(d['before'], series[i], i), raw_J=raw,
                actual_J=actual, actual_action=row['receipt']['owner']['selected_action'])


class EnergyCalibration:
    def __init__(self):
        self.stage = 'train'; self.training = {}; self.validation = {}; self.seen = set()

    def _candidate(self, key):
        values = self.training.get(key, [])
        if len(values) < POLICY['min_train']:
            return 0.
        return max(-POLICY['correction_limit_J'], min(POLICY['correction_limit_J'],
                   POLICY['shrinkage'] * median(values)))

    def correction(self, feature):
        key = digest(feature); c = self._candidate(key)
        v = self.validation.get(key, dict(n=0, raw=0., corrected=0.))
        if self.stage != 'frozen' or v['n'] < POLICY['min_validation']:
            return 0.
        return c if v['corrected'] < (1.-POLICY['required_gain'])*v['raw'] else 0.

    def predict(self, feature, raw_J):
        return finite(raw_J) + self.correction(feature)

    def add(self, event_id, item):
        if self.stage == 'frozen':
            raise ValueError('frozen calibration cannot learn')
        if not isinstance(event_id, str) or not event_id or event_id in self.seen:
            raise ValueError('unique nonempty energy event required')
        if len(self.seen) >= POLICY['max_examples']:
            raise ValueError('energy evidence budget exhausted')
        key = digest(item['features']); residual = finite(item['actual_J'])-finite(item['raw_J'])
        # Validate completely before mutation. Admission labels deliberately unused.
        self.seen.add(event_id)
        if self.stage == 'train':
            self.training.setdefault(key, []).append(residual)
        else:
            v = self.validation.setdefault(key, dict(n=0, raw=0., corrected=0.))
            v['n'] += 1; v['raw'] += abs(residual); v['corrected'] += abs(residual-self._candidate(key))

    def begin_validation(self):
        if self.stage != 'train':
            raise ValueError('validation follows training once')
        self.stage = 'validate'

    def freeze(self):
        if self.stage != 'validate':
            raise ValueError('freeze follows validation once')
        self.stage = 'frozen'

    def checkpoint(self):
        p = dict(schema=SCHEMA, sources=fingerprints(), policy=POLICY, stage=self.stage,
                 training=deepcopy(self.training), validation=deepcopy(self.validation), seen=sorted(self.seen))
        return dict(payload=p, sha256=digest(p))

    @classmethod
    def restore(cls, envelope):
        p = envelope['payload']
        if (digest(p) != envelope['sha256'] or p['schema'] != SCHEMA or
                p['sources'] != fingerprints() or p['policy'] != POLICY):
            raise ValueError('energy checksum/source/policy mismatch')
        if p['stage'] not in ('train', 'validate', 'frozen'):
            raise ValueError('energy calibration stage')
        seen = p['seen']; training = p['training']; validation = p['validation']
        if (not isinstance(seen, list) or any(not isinstance(e, str) or not e for e in seen) or
                len(set(seen)) != len(seen) or len(seen) > POLICY['max_examples']):
            raise ValueError('energy evidence identity/budget')
        for values in training.values():
            if not isinstance(values, list) or not values:
                raise ValueError('empty energy training context')
            for value in values: finite(value)
        for v in validation.values():
            if type(v['n']) is not int or v['n'] < 1 or finite(v['raw']) < 0 or finite(v['corrected']) < 0:
                raise ValueError('invalid energy validation loss')
        if sum(map(len, training.values())) + sum(v['n'] for v in validation.values()) != len(seen):
            raise ValueError('energy evidence counts')
        if p['stage'] == 'train' and validation:
            raise ValueError('validation before training finished')
        obj = cls(); obj.stage=p['stage']; obj.training=deepcopy(training)
        obj.validation=deepcopy(validation); obj.seen=set(seen)
        return obj


def score(candidate, initial, calibration, learning):
    """Explicit opt-in scoring adapter; does not alter the saved planner policy.

    Future contexts use predicted states, not future actual observations. This
    multi-step use is a policy integration seam, not measured trajectory benefit.
    """
    total=0.; prior=initial
    for i, step in enumerate(candidate['series']):
        raw=prior['fuel_J']-step['fuel_J']
        total += calibration.predict(features(prior, step, i), raw)
        prior=step
    raw_learning=deepcopy(learning); raw_learning['fuel_bias_J']={}
    return (original_score(candidate, raw_learning) + PLANNING_POLICY['fuel_seconds_per_J'] *
            (max(0., total)-max(0., candidate['fuel_debit_J'])))
