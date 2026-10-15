"""Bounded admission control, distinct from a verbal self-report.

All learning comes from the existing verified SelfModel. A read-only refresh
can remove staleness, but cannot create experience in an unseen context.
The native journal retains execution authority and unknown-outcome blocking.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from .monitor import SelfModel, snapshot, digest, POLICY as MONITOR_POLICY, source
from .regulation import KnowledgeView, MotionJournal
from unified_body_v2 import UnifiedBody

SCHEMA = 'nasuraya-metacognitive-control/1'
ARMS = ('control', 'report_only', 'memory_disabled', 'native_only')
POLICY = dict(max_read_only_refreshes=1, max_native_requests=1,
              min_samples=MONITOR_POLICY['min_samples'],
              continue_threshold=MONITOR_POLICY['continue_threshold'])


def sources():
    return dict(controller=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                monitor=source())


def select(knowledge, observation, request, *, arm, now_s, refreshed=False):
    """No outcomes, body previews or mutable model are accepted here."""
    if arm not in ARMS:
        raise ValueError('unknown metacognitive arm')
    if knowledge['pending']:
        raise ValueError('unresolved training outcome; reconcile before control')
    if arm == 'native_only':
        return dict(choice='request_walk', reasons=['native arbitration only'],
                    report=None, probability=None)
    state = deepcopy(knowledge)
    if arm == 'memory_disabled':
        state = dict(counts={}, pending=[], episodes=0, last=None)
    report = SelfModel.inspect(KnowledgeView(state), observation, request,
                               at_simulated_s=now_s)
    result = dict(report=report, probability=report['inferred']['probability'])
    reasons = report['reasons']
    # Give report-only and control the same current evidence. The ablation
    # removes control authority, not access to a fresh read-only report.
    if not refreshed and 'stale_body_evidence' in reasons:
        return dict(result, choice='refresh_observation', reasons=reasons)
    if arm == 'report_only':
        return dict(result, choice='request_walk', reasons=['report has no control authority'])
    if not reasons:
        return dict(result, choice='request_walk', reasons=['evidence gate passed; native guards still apply'])
    # Refresh only uncertainty/staleness, not a known present body restriction.
    refreshable = set(reasons) <= {'stale_body_evidence', 'insufficient_context_experience',
                                   'low_observed_self_efficacy'}
    uncertain = ('stale_body_evidence' in reasons or
                 report['inferred']['samples'] < POLICY['min_samples'])
    if not refreshed and refreshable and uncertain:
        return dict(result, choice='refresh_observation', reasons=reasons)
    return dict(result, choice='defer', reasons=reasons)


class ControlTrial:
    """One optional walk, with at most one read-only observation refresh.

Frozen knowledge is a source-qualified snapshot from SelfModel.verify(), not
new training. Checkpoint hashes assume a trusted host, like RegulationJournal.
"""
    def __init__(self, body, contract, records=None):
        self.body = body
        self.contract = deepcopy(contract)
        self.records = deepcopy(records or [])
        self.task = dict(elapsed=len(self.records))  # existing durable tick boundary
        self.validate()

    @classmethod
    def start(cls, body, model, request, observation, *, arm):
        if request['requested'] != 'walk':
            raise ValueError('v0.1 controls only a bounded walk request')
        if (type(request['duration_s']) not in (int, float) or
                not math.isfinite(request['duration_s']) or not .1 <= request['duration_s'] <= 1.):
            raise ValueError('bounded walk duration 0.1..1.0 seconds required')
        if request['expected_revision'] != body.revision:
            raise ValueError('current native revision required')
        body.validate_input(request['external'], datetime.fromisoformat(request['at_utc']), request['duration_s'])
        before = body.checkpoint()
        state = json.loads(json.dumps(model.verify(), allow_nan=False))
        initial = select(state, observation, request, arm=arm,
                         now_s=body.owner.physical.state.time_s)
        fresh = snapshot(body) if initial['choice'] == 'refresh_observation' else None
        final = (select(state, fresh, request, arm=arm,
                        now_s=body.owner.physical.state.time_s, refreshed=True)
                 if fresh is not None else initial)
        if body.checkpoint() != before:
            raise ValueError('read-only refresh advanced body')
        return cls(body, dict(arm=arm, knowledge=state,
            knowledge_sha256=digest(state), model_database_sha256=hashlib.sha256(model.path.read_bytes()).hexdigest(),
            initial_body=before, request=deepcopy(request), initial_observation=deepcopy(observation),
            fresh_observation=fresh, initial_decision=initial, final_decision=final))

    def validate(self):
        c = self.contract
        if digest(c['knowledge']) != c['knowledge_sha256']:
            raise ValueError('knowledge snapshot damaged')
        initial_body = UnifiedBody.restore(c['initial_body'])
        if c['initial_observation']['source_identity'] != snapshot(initial_body)['source_identity']:
            raise ValueError('observation belongs to a different body/controller source')
        q = c['request']
        if (q['requested'] != 'walk' or q['expected_revision'] != initial_body.revision or
                type(q['duration_s']) not in (int, float) or
                not math.isfinite(q['duration_s']) or not .1 <= q['duration_s'] <= 1.):
            raise ValueError('trial request changed')
        now = initial_body.owner.physical.state.time_s
        first = select(c['knowledge'], c['initial_observation'], q, arm=c['arm'], now_s=now)
        fresh = c['fresh_observation']
        if fresh is not None:
            if first['choice'] != 'refresh_observation' or fresh != snapshot(initial_body):
                raise ValueError('refresh is not the unchanged source-pinned body')
            final = select(c['knowledge'], fresh, q, arm=c['arm'], now_s=now, refreshed=True)
        else:
            if first['choice'] == 'refresh_observation':
                raise ValueError('missing required refresh')
            final = first
        if c['initial_decision'] != first or c['final_decision'] != final:
            raise ValueError('decision differs from frozen knowledge/policy')
        if len(self.records) > POLICY['max_native_requests']:
            raise ValueError('trial request budget')
        if not self.records:
            if self.body.checkpoint() != c['initial_body']:
                raise ValueError('body advanced outside trial')
        else:
            r = self.records[0]
            if final['choice'] != 'request_walk' or self.body.results.get(q['event_id']) != r:
                raise ValueError('unrequested or unrelated native receipt')
            from persistent_embodiment_v1 import instant
            fingerprint = digest({k: (instant(v).isoformat() if k == 'at_utc' else v)
                                  for k, v in q.items() if k != 'event_id'})
            if (self.body.requests.get(q['event_id']) != fingerprint or
                    self.body.revision != initial_body.revision + 1 or
                    r['revision'] != self.body.revision or
                    self.body.journal[-1]['event_id'] != q['event_id'] or
                    self.body.journal[-1]['before_sha256'] != snapshot(initial_body)['body_before_digest']):
                raise ValueError('receipt revision/request mismatch')
            if any(abs(r['whole_body_audit'][k]) > v for k, v in
                   [('energy_error_J', 5e-5), ('water_error_L', 1e-8), ('light_error_J', 1e-8)]):
                raise ValueError('native conservation audit')

    def decision(self):
        self.validate()
        return deepcopy(self.contract['final_decision'])

    def request(self):
        self.validate()
        if self.records or self.decision()['choice'] != 'request_walk':
            raise ValueError('trial finished or deferred; no native request')
        return deepcopy(self.contract['request'])

    def step(self):
        q = self.request()
        receipt = self.body.cycle(**q)
        self.records.append(deepcopy(receipt))
        self.task['elapsed'] = len(self.records)
        self.validate()
        return receipt

    def checkpoint(self):
        self.validate()
        payload = dict(schema=SCHEMA, sources=sources(), policy=deepcopy(POLICY),
                       body=self.body.checkpoint(), contract=deepcopy(self.contract),
                       records=deepcopy(self.records))
        return dict(payload=payload, sha256=digest(payload))

    @classmethod
    def restore(cls, saved):
        if set(saved) != {'payload', 'sha256'} or digest(saved['payload']) != saved['sha256']:
            raise ValueError('trial checksum')
        p = saved['payload']
        if set(p) != {'schema', 'sources', 'policy', 'body', 'contract', 'records'}:
            raise ValueError('trial fields')
        if p['schema'] != SCHEMA or p['sources'] != sources() or p['policy'] != POLICY:
            raise ValueError('trial source/version/policy')
        return cls(UnifiedBody.restore(p['body']), p['contract'], p['records'])


class ControlJournal(MotionJournal):
    goal_type = ControlTrial
