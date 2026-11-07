"""Opt-in coupling of NeuroPelvic to the source-pinned UnifiedBody solver.

Body pain/balance gate the next sidecar update. A previous restorative sidecar
state may request the existing slow_breath action. Native arbitration, gas
gates, and resource ledgers retain authority. No new physical stock is added.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from neuropelvic import NeuroPelvic, State, NORMALIZED_FIELDS
from persistent_embodiment_v1 import ACTIONS, digest, finite, instant
from unified_body_v2 import UnifiedBody

SCHEMA = 'tadash-neuropelvic-body/1'
PHASES = {'baseline', 'rising', 'peak', 'release', 'recovery'}
MODEL_SCHEMA = 'tadash-neuropelvic-state/1'
MODEL_KEYS = {'schema', 'state', 'phase_elapsed', 'above_threshold', 'peak_count', 'events'}
CONTROL_DEFAULTS = dict(start=False, rhythm=0., intensity=0., breath_cue=0.,
                        attention=0., safe=True, stop=False)
CONTROL_KEYS = set(CONTROL_DEFAULTS) | {'source_id', 'kind'}


def wire(value):
    """Use the same JSON types before and after process restoration."""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def fingerprints():
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ('neuropelvic.py', 'neuropelvic_body.py')}


def model_payload(model):
    return dict(schema=MODEL_SCHEMA, state=asdict(model.state),
                phase_elapsed=model._phase_elapsed,
                above_threshold=model._above_threshold,
                peak_count=model.peak_count, events=deepcopy(model.events))


def restore_model(payload):
    if not isinstance(payload, dict) or set(payload) != MODEL_KEYS or payload['schema'] != MODEL_SCHEMA:
        raise ValueError('neuropelvic checkpoint schema mismatch')
    state = deepcopy(payload['state'])
    if not isinstance(state, dict) or set(state) != set(asdict(State())):
        raise ValueError('neuropelvic state fields mismatch')
    finite(state['time'], 'model time', 0, 1e12)
    if state['phase'] not in PHASES:
        raise ValueError('unknown neuropelvic phase')
    for key in NORMALIZED_FIELDS:
        finite(state[key], key)
    if not isinstance(state['chakra'], (list, tuple)) or len(state['chakra']) != 7:
        raise ValueError('seven symbolic channels required')
    for value in state['chakra']:
        finite(value, 'symbolic channel')
    state['chakra'] = tuple(state['chakra'])
    model = NeuroPelvic()
    model.state = State(**state)
    model._phase_elapsed = finite(payload['phase_elapsed'], 'phase timer', 0, state['time'] + 1e-7)
    model._above_threshold = finite(payload['above_threshold'], 'threshold timer', 0, model.PEAK_HOLD_SECONDS)
    count = payload['peak_count']
    if type(count) is not int or count < 0:
        raise ValueError('integer peak counter required')
    model.peak_count = count
    events = payload['events']
    if not isinstance(events, list):
        raise ValueError('event history required')
    previous_phase, previous_time, peaks = 'baseline', 0., 0
    transitions = {('baseline', 'rising'), ('rising', 'peak'), ('rising', 'release'),
                   ('peak', 'release'), ('release', 'recovery'), ('recovery', 'baseline')}
    for event in events:
        if not isinstance(event, dict) or set(event) != {'time', 'from', 'to', 'reason', 'arousal'}:
            raise ValueError('malformed neuropelvic event')
        finite(event['time'], 'event time', previous_time, state['time'] + 1e-7)
        finite(event['arousal'], 'event arousal')
        if event['from'] != previous_phase or (event['from'], event['to']) not in transitions:
            raise ValueError('broken neuropelvic phase history')
        if not isinstance(event['reason'], str) or not event['reason']:
            raise ValueError('event reason required')
        previous_phase, previous_time = event['to'], event['time']
        peaks += int(event['to'] == 'peak')
    if previous_phase != state['phase'] or peaks != count:
        raise ValueError('phase history/counter mismatch')
    if abs(state['time'] - previous_time - model._phase_elapsed) > 1e-6:
        raise ValueError('phase clock mismatch')
    if state['phase'] != 'rising' and model._above_threshold != 0:
        raise ValueError('stale threshold timer')
    if state['phase'] == 'peak' and model._phase_elapsed > model.PEAK_SECONDS + 1e-7:
        raise ValueError('peak duration exceeded')
    model.events = deepcopy(events)
    return model


def controls(value):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - CONTROL_KEYS:
        raise ValueError('unknown neuropelvic input')
    if value:
        if value.get('kind') != 'declared_simulated_input':
            raise ValueError('declared simulated input kind required')
        source = value.get('source_id')
        if not isinstance(source, str) or not source or len(source) > 160:
            raise ValueError('bounded input source required')
    result = dict(CONTROL_DEFAULTS)
    result.update({key: value[key] for key in CONTROL_DEFAULTS if key in value})
    for key in ('start', 'safe', 'stop'):
        if type(result[key]) is not bool:
            raise ValueError(key + ': boolean required')
    for key in ('rhythm', 'intensity', 'breath_cue', 'attention'):
        result[key] = finite(result[key], key)
    return result


class NeuroPelvicBody:
    def __init__(self, body, *, coupling=True):
        if not isinstance(body, UnifiedBody) or type(coupling) is not bool:
            raise ValueError('UnifiedBody and explicit boolean coupling required')
        self.body = body
        self.model = NeuroPelvic()
        self.coupling = coupling
        self.origin_body_s = self.body_time()
        self.origin_revision = body.revision
        self.revision = 0
        self.requests = {}
        self.results = {}

    def body_time(self):
        return self.body.owner.owner.body.state.time_s

    def _check_clocks(self):
        if abs(self.body_time() - self.origin_body_s - self.model.state.time) > 1e-7:
            raise ValueError('body/neuropelvic clock divergence')
        if self.body.revision != self.origin_revision + self.revision:
            raise ValueError('body advanced outside coupled owner')

    def cycle(self, *, event_id, at_utc, duration_s=1., neuro=None,
              external=None, requested=None, expected_revision=None):
        control = controls(neuro)
        duration_s = finite(duration_s, 'coupled duration', .1, 1.)
        if abs(duration_s * 10 - round(duration_s * 10)) > 1e-8:
            raise ValueError('coupled duration must align to .1 seconds')
        if not isinstance(event_id, str) or not event_id or len(event_id) > 100:
            raise ValueError('bounded coupled event id required')
        if requested is not None and requested not in ACTIONS:
            raise ValueError('unknown body action')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError('integer revision required')
        now = instant(at_utc)
        external = deepcopy(external if external is not None else {})
        self.body.validate_input(external, now, duration_s)
        request = digest(dict(at_utc=now.isoformat(), duration_s=duration_s,
                              neuro=neuro, external=external, requested=requested,
                              expected_revision=expected_revision))
        if event_id in self.requests:
            if self.requests[event_id] != request:
                raise ValueError('conflicting coupled event replay')
            if event_id not in self.results:
                raise ValueError('coupled receipt archived; do not replay')
            return deepcopy(self.results[event_id])
        if expected_revision is not None and expected_revision != self.revision:
            raise ValueError('stale coupled writer')
        self._check_clocks()
        work = deepcopy(self)
        before = work.body.owner.body()['minimum_state']
        neuro_before = asdict(work.model.state)
        # Native pain is an existing, differently calibrated proxy. The 0.35
        # threshold is an authored appraisal gate, not a unit conversion.
        gate = before['pain'] < .35 and before['balance'] >= .50 and before['energy'] >= .25
        gate = gate and before['posture'] != 'failed' and control['safe'] and not control['stop']
        start_accepted = work.model.start_cycle() if control['start'] and gate else False
        action = requested if requested is not None else 'observe'
        policy_requested = bool(work.coupling and requested is None and gate and
            work.model.state.phase in ('release', 'recovery') and work.model.state.settling >= .10)
        if policy_requested:
            action = 'slow_breath'
        body_before_s = work.body_time()
        receipt = work.body.cycle(event_id='neuro:' + event_id, at_utc=now.isoformat(),
            duration_s=duration_s, external=external, requested=action,
            expected_revision=work.body.revision)
        work.model.run(duration_s, dt=.1, rhythm=control['rhythm'],
            intensity=control['intensity'], breath_cue=control['breath_cue'],
            attention=control['attention'], safe=gate,
            pain=1. if before['pain'] >= .35 else 0.,
            balance=before['balance'], stop=control['stop'])
        work.revision += 1
        work._check_clocks()
        after = work.body.owner.body()['minimum_state']
        out = dict(schema=SCHEMA, event_id=event_id, revision=work.revision,
            start_accepted=start_accepted, coupling_enabled=work.coupling,
            policy_requested_slow_breath=policy_requested,
            requested_action=action, selected_action=receipt['owner']['selected_action'],
            achieved_slow_breath_ticks=receipt['owner']['resource_and_gas_audit']['achieved_slow_breath_ticks'],
            body_feedback=dict(source='previous_native_simulator_snapshot',
                sampled_at_body_s=body_before_s, gate_open=gate,
                pain=before['pain'], balance=before['balance'], energy=before['energy']),
            before_body=before, after_body=after,
            before_neuropelvic=neuro_before, neuropelvic=asdict(work.model.state),
            peak_count=work.model.peak_count,
            body_time_before_s=body_before_s, body_time_after_s=work.body_time(),
            owner_ticks=receipt['owner_ticks'], audit=receipt['whole_body_audit'],
            control_source=deepcopy(neuro), no_new_physical_stock=True,
            empirical_validation=False, background_execution_started=False)
        out = wire(out)
        work.requests[event_id] = request
        work.results[event_id] = deepcopy(out)
        work.results = dict(list(work.results.items())[-16:])
        self.__dict__ = work.__dict__
        return deepcopy(out)

    def checkpoint(self):
        self._check_clocks()
        payload = dict(schema=SCHEMA, source_fingerprints=fingerprints(),
            body=deepcopy(self.body.checkpoint()), neuro=model_payload(self.model),
            coupling=self.coupling, origin_body_s=self.origin_body_s,
            origin_revision=self.origin_revision, revision=self.revision,
            requests=deepcopy(self.requests), results=deepcopy(self.results))
        payload = wire(payload)
        return dict(payload=payload, sha256=digest(payload))

    @classmethod
    def restore(cls, envelope):
        if (not isinstance(envelope, dict) or set(envelope) != {'payload', 'sha256'}
                or digest(envelope['payload']) != envelope['sha256']):
            raise ValueError('coupled checkpoint checksum mismatch')
        p = envelope['payload']
        required = {'schema', 'source_fingerprints', 'body', 'neuro', 'coupling',
                    'origin_body_s', 'origin_revision', 'revision', 'requests', 'results'}
        if set(p) != required or p['schema'] != SCHEMA or p['source_fingerprints'] != fingerprints():
            raise ValueError('coupled schema/source mismatch')
        obj = cls(UnifiedBody.restore(p['body']), coupling=p['coupling'])
        obj.model = restore_model(p['neuro'])
        obj.origin_body_s = finite(p['origin_body_s'], 'body origin', 0, 1e12)
        for key in ('origin_revision', 'revision'):
            if type(p[key]) is not int or p[key] < 0:
                raise ValueError('integer coupled revision required')
            setattr(obj, key, p[key])
        if not isinstance(p['requests'], dict) or len(p['requests']) != obj.revision:
            raise ValueError('coupled request history mismatch')
        if not isinstance(p['results'], dict) or len(p['results']) > 16:
            raise ValueError('coupled receipt cache mismatch')
        for key, value in p['requests'].items():
            if not isinstance(key, str) or not isinstance(value, str) or len(value) != 64:
                raise ValueError('invalid coupled request fingerprint')
        for key, value in p['results'].items():
            if key not in p['requests'] or value['event_id'] != key or type(value['revision']) is not int:
                raise ValueError('invalid coupled receipt')
            if not 1 <= value['revision'] <= obj.revision:
                raise ValueError('invalid receipt revision')
        obj.requests = deepcopy(p['requests'])
        obj.results = dict(sorted(deepcopy(p['results']).items(), key=lambda row: row[1]['revision']))
        obj._check_clocks()
        return obj
