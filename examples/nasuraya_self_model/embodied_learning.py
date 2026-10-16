"""Bounded experiential sessions on the existing durable native motion journal.

A uses no experiential counts; B retrieves frozen counts; C updates counts only
from cached native receipts. Three explicitly granted practice probes can precede
self-selected actions. No network, recursion, guard edits or background scheduler.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re

from .monitor import SelfModel, snapshot, context, forecast, digest, POLICY, verify_observation
from .regulation import KnowledgeView, update_knowledge, MotionJournal
from unified_body_v2 import UnifiedBody
from persistent_embodiment_v1 import instant

SCHEMA = 'nasuraya-embodied-learning/1'
CORE = ('wisdom_before_power', 'identity_continuity', 'learn_from_errors',
        'protect_without_domination', 'ethical_boundaries',
        'autonomy_with_accountability', 'evaluate_against_stable_core')
LIMITS = dict(max_ticks=12, max_practice=3, duration_min=.1, duration_max=1.,
              allowed_actions=['walk', 'observe', 'rest', 'sleep'])


def sources():
    from . import monitor, regulation
    return {k: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for k, m in [('session', __import__(__name__, fromlist=['x'])),
                         ('monitor', monitor), ('regulation', regulation)]}


def choose(knowledge, observation, request, *, arm, practice):
    """Inputs contain no future outcome or simulated preview."""
    if arm not in ('A', 'B', 'C') or knowledge['pending']:
        raise ValueError('known arm and resolved outcomes required')
    state = (dict(counts={}, pending=[], episodes=0, last=None)
             if arm == 'A' else knowledge)
    report = SelfModel.inspect(KnowledgeView(state), observation, request)
    m = observation['minimum']
    # Fixed bodily protection takes priority even over a practice grant.
    if report['reasons'] and observation['audit']['walking_restrictions']:
        action = ('sleep' if m['sleep_pressure'] > .85 else
                  'rest' if m['fatigue'] > .52 or m['pain'] > .40 or m['energy'] < .25
                  else 'observe')
        reason = 'current_body_restriction'
    elif practice:
        action, reason = 'walk', 'explicit_bounded_practice'
    elif arm == 'A':
        action, reason = 'walk', 'fixed_no_experience_baseline'
    elif report['recommendation'] == 'continue_with_native_guards':
        action, reason = 'walk', 'verified_experience_allows_candidate'
    else:
        action, reason = 'observe', 'insufficient_experience_or_failed_prediction'
    return dict(action=action, reason=reason, report=report)


class LearningSession:
    def __init__(self, body, contract, records=None):
        self.body = body
        self.contract = deepcopy(contract)
        self.records = deepcopy(records or [])
        self.task = dict(elapsed=len(self.records))
        self.validate()

    @classmethod
    def start(cls, body, model, *, session_id, arm='C', max_ticks=8,
              practice_ticks=0, duration_s=.1):
        if isinstance(model, SelfModel):
            knowledge = model.verify()
            origin = hashlib.sha256(model.path.read_bytes()).hexdigest()
        elif isinstance(model, cls):
            model.validate()
            knowledge = model.knowledge()
            origin = model.checkpoint()['sha256']
        else:
            raise ValueError('verified SelfModel or completed learning session required')
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', session_id):
            raise ValueError('bounded session ID')
        c = dict(session_id=session_id, arm=arm, max_ticks=max_ticks,
                 practice_ticks=practice_ticks, duration_s=duration_s,
                 initial_body=body.checkpoint(), knowledge=knowledge, knowledge_origin=origin,
                 identity=list(CORE), limits=deepcopy(LIMITS))
        return cls(body, c)

    def knowledge(self):
        state = deepcopy(self.contract['knowledge'])
        if self.contract['arm'] == 'C':
            for row in self.records:
                state = update_knowledge(state, row['decision'], row['receipt'])
        return state

    def base_request(self):
        c = self.contract
        return dict(event_id=c['session_id']+':'+str(len(self.records)),
            at_utc=(datetime.fromisoformat(self.body.owner.wall_utc)+
                    timedelta(seconds=c['duration_s'])).isoformat(),
            duration_s=c['duration_s'], requested='walk',
            expected_revision=self.body.revision, external={})

    def decision(self):
        if len(self.records) >= self.contract['max_ticks']:
            raise ValueError('persistent execution budget exhausted')
        q = self.base_request(); obs = snapshot(self.body)
        selected = choose(self.knowledge(), obs, q, arm=self.contract['arm'],
                          practice=len(self.records) < self.contract['practice_ticks'])
        q['requested'] = selected['action']
        return dict(observation=obs, request=q, selected=selected,
                    action_prediction=forecast(self.knowledge()['counts'] if self.contract['arm'] != 'A' else {}, context(obs, q)))

    def request(self):
        self.validate()
        return deepcopy(self.decision()['request'])

    def step(self):
        self.validate(); d = self.decision()
        r = self.body.cycle(**d['request'])
        self.records.append(dict(decision=d, receipt=deepcopy(r), after=snapshot(self.body)))
        self.task['elapsed'] = len(self.records)
        # Fail closed before MotionJournal publishes an invalid transition.
        self.validate()
        return r

    def validate(self):
        c = self.contract
        if c.get('identity') != list(CORE) or c.get('limits') != LIMITS:
            raise ValueError('stable identity or safety boundaries changed')
        if (c['arm'] not in ('A','B','C') or type(c['max_ticks']) is not int or
            not 1 <= c['max_ticks'] <= LIMITS['max_ticks'] or
            type(c['practice_ticks']) is not int or not 0 <= c['practice_ticks'] <= min(3,c['max_ticks']) or
            type(c['duration_s']) not in (float,int) or not .1 <= c['duration_s'] <= 1. or
            abs(c['duration_s']*10-round(c['duration_s']*10)) > 1e-8):
            raise ValueError('execution grant outside fixed bounds')
        if c['knowledge']['pending'] or len(self.records) > c['max_ticks']:
            raise ValueError('pending outcome or tick budget')
        if c['knowledge']['episodes'] + c['max_ticks'] > POLICY['max_episodes']:
            raise ValueError('experience capacity exceeded')
        initial = UnifiedBody.restore(c['initial_body'])
        prior_obs = snapshot(initial); state = deepcopy(c['knowledge'])
        prior_time = initial.owner.wall_utc
        for index, row in enumerate(self.records):
            d, r, after = row['decision'], row['receipt'], row['after']
            verify_observation(after)
            q = dict(event_id=c['session_id']+':'+str(index),
                at_utc=(datetime.fromisoformat(prior_time)+timedelta(seconds=c['duration_s'])).isoformat(),
                duration_s=c['duration_s'], requested='walk', expected_revision=prior_obs['revision'], external={})
            selected = choose(state, prior_obs, q, arm=c['arm'], practice=index<c['practice_ticks'])
            q['requested'] = selected['action']
            pred = forecast(state['counts'] if c['arm']!='A' else {}, context(prior_obs,q))
            if d != dict(observation=prior_obs,request=q,selected=selected,action_prediction=pred):
                raise ValueError('decision differs from prior experience')
            rh = digest({k:(instant(v).isoformat() if k=='at_utc' else v)
                         for k,v in q.items() if k!='event_id'})
            if (self.body.results.get(q['event_id']) != r or self.body.requests.get(q['event_id']) != rh or
                r['revision'] != prior_obs['revision']+1 or after['revision'] != r['revision'] or
                not r['owner']['physical_model_valid'] or
                after['source_identity'] != prior_obs['source_identity']):
                raise ValueError('invalid or unrelated native outcome')
            native_journal = self.body.journal[initial.revision+index]
            if (native_journal['event_id'] != q['event_id'] or
                native_journal['before_sha256'] != prior_obs['body_before_digest']):
                raise ValueError('native predecessor mismatch')
            if any(abs(r['whole_body_audit'][k])>v for k,v in
                   [('energy_error_J',5e-5),('water_error_L',1e-8),('light_error_J',1e-8)]):
                raise ValueError('conservation audit failed')
            # Reuse the existing learning update; labels are the actual cached effects.
            if c['arm']=='C': state = update_knowledge(state,d,r)
            prior_obs, prior_time = after, q['at_utc']
        if self.records:
            if snapshot(self.body) != prior_obs:
                raise ValueError('body advanced outside recorded session')
        elif self.body.checkpoint() != c['initial_body']:
            raise ValueError('unrecorded body change')

    def self_report(self):
        obs = snapshot(self.body); m = obs['minimum']; k = self.knowledge()
        failures = [dict(event=r['receipt']['event_id'], requested=r['decision']['request']['requested'],
                         actual=r['receipt']['owner']['selected_action']) for r in self.records
                    if r['decision']['request']['requested'] != r['receipt']['owner']['selected_action']]
        return dict(current_state=m, capabilities_under_native_guards=list(LIMITS['allowed_actions']),
            physical_limitations=obs['audit']['walking_restrictions'],
            motor_confidence_kind='empirical_requested_action_admission_not_motor_precision',
            uncertainty=obs['audit']['unknown'], recent_decision_failures=failures[-8:],
            recent_prediction_errors=obs['audit']['recent_prediction_errors'],
            goal_progress=dict(completed_ticks=len(self.records), granted_ticks=self.contract['max_ticks']),
            recovery_capacity=dict(available_requests=['rest','sleep'],measured_rate=None),
            learned_observations=sum(sum(v) for v in k['counts'].values()),
            next_change='review_after_budget' if len(self.records)==self.contract['max_ticks'] else self.decision()['selected'],
            identity_consistent=True, subjective_experience_measured=False)

    def checkpoint(self):
        self.validate()
        p = dict(schema=SCHEMA, sources=sources(), body=self.body.checkpoint(),
                 contract=self.contract, records=self.records)
        return dict(payload=deepcopy(p), sha256=digest(p))

    @classmethod
    def restore(cls, saved):
        p=saved['payload']
        if (digest(p)!=saved['sha256'] or p['schema']!=SCHEMA or p['sources']!=sources()):
            raise ValueError('session checksum/source mismatch')
        return cls(UnifiedBody.restore(p['body']),p['contract'],p['records'])


class LearningJournal(MotionJournal):
    goal_type = LearningSession
