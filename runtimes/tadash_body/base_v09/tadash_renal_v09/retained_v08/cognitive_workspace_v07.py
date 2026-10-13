"""Finite environment cognition, source memory, and delayed information policy.

Extends the selected V06 mechanisms. No learned body dynamics, neural
activation access, or confidence calibration. Probabilities concern binary
environment facts under a declared synthetic sensor likelihood.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "tadash-environment-cognition/0.7"
SOURCES = {"surface_probe", "visual_probe", "weather_probe", "fixture_probe"}
COMMANDS = {"stand", "single_L", "single_R", "walk"}
LIMITS = dict(workspace=2, memory=128, topics=16, pending=8, cache=32,
              provenance=256, work_units=96, observations_per_tick=16)


def canonical(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def numeric(v, name, lo=0., hi=1e8):
    if isinstance(v, bool) or not isinstance(v, (float, int)):
        raise ValueError(name + ": number required")
    if not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(name + ": finite value outside bounds")
    return float(v)


def identity(v, name):
    if not isinstance(v, str) or not v or len(v) > 160:
        raise ValueError(name + ": bounded nonempty string required")


def entropy(p):
    return 0. if p in (0., 1.) else -p*math.log2(p)-(1-p)*math.log2(1-p)


def update(p, value, accuracy=.9):
    a = accuracy if value else 1-accuracy
    return p*a / (p*a+(1-p)*(1-a))


@dataclass(frozen=True)
class Observation:
    id: str
    topic: str
    value: int
    source: str
    source_sequence: int
    sampled_at_s: float
    correlation_id: str
    importance: float = .5
    kind: str = "simulated_observation"
    action_id: str | None = None


@dataclass(frozen=True)
class Goal:
    id: str = "steady_walk"
    topic: str = "surface_A"
    desired_command: str = "walk"
    safe_reward: float = 4.
    unsafe_cost: float = 12.
    action_cost: float = .2
    wait_cost_per_s: float = .12
    query_cost: float = .35
    query_latency_s: float = 1.5
    action_duration_s: float = 1.
    deadline_s: float = 120.


@dataclass(frozen=True)
class CognitiveEvent:
    id: str
    time_s: float
    goal: Goal
    observations: tuple[Observation, ...] = ()


class EnvironmentBrain:
    def __init__(self, *, attention=True, broadcast=True, memory=True,
                 freshness=True, correlation=True, deadline=True):
        flags = dict(attention=attention, broadcast=broadcast, memory=memory,
                     freshness=freshness, correlation=correlation, deadline=deadline)
        if any(type(v) is not bool for v in flags.values()):
            raise ValueError("ablation flags must be boolean")
        self.config = flags
        self.entries = []
        self.world = {}
        self.latest = {}
        self.pending = {}
        self.action_history = []
        self.provenance = []
        self.source_sequences = {s: -1 for s in SOURCES}
        self.cache = {}
        self.last_time_s = None
        self.last = None
        self.expired_action_count = 0
        self.total_ticks = 0

    @staticmethod
    def validate_goal(g):
        if not isinstance(g, Goal):
            raise ValueError("Goal required")
        identity(g.id, "goal id"); identity(g.topic, "goal topic")
        if g.desired_command not in COMMANDS:
            raise ValueError("unsupported goal command")
        for k in ("safe_reward", "unsafe_cost", "action_cost", "wait_cost_per_s",
                  "query_cost", "deadline_s"):
            numeric(getattr(g, k), k)
        numeric(g.query_latency_s, "query latency", .05, 60.)
        numeric(g.action_duration_s, "action duration", .05, 60.)

    def validate(self, e, body):
        if not isinstance(e, CognitiveEvent):
            raise ValueError("CognitiveEvent required")
        identity(e.id, "event id"); numeric(e.time_s, "cognitive clock")
        self.validate_goal(e.goal)
        if len(e.observations) > LIMITS['observations_per_tick']:
            raise ValueError("observation work quota exceeded")
        if not isinstance(body, dict) or set(body) != {
                'sampled_at_s', 'critical', 'optional_pause', 'valid',
                'protective', 'source', 'phase', 'body_tick'}:
            raise ValueError("body observation contract mismatch")
        if body['source'] != 'V06_physical_owner' or abs(body['sampled_at_s']-e.time_s)>1e-8:
            raise ValueError("body snapshot must come from this physical tick")
        for k in ('critical', 'optional_pause', 'valid', 'protective'):
            if type(body[k]) is not bool:
                raise ValueError("body gates require bool")
        payload = canonical(dict(event=asdict(e), body=body))
        if e.id in self.cache:
            if self.cache[e.id]['request'] != payload:
                raise ValueError("event id reused with altered request")
            return payload, True
        if self.last_time_s is not None and e.time_s <= self.last_time_s:
            raise ValueError("cognitive time must increase")
        ids = set(); action_ids=set(); sequences = dict(self.source_sequences)
        known = {r['id'] for r in self.provenance}
        topics = set(self.world)
        for o in e.observations:
            if not isinstance(o, Observation):
                raise ValueError("Observation required")
            for k in ('id', 'topic', 'correlation_id'):
                identity(getattr(o, k), k)
            if o.id in ids or o.id in known:
                raise ValueError("replayed observation")
            ids.add(o.id); topics.add(o.topic)
            if type(o.value) is not int or o.value not in (0, 1):
                raise ValueError("environment observation must be binary")
            if o.source not in SOURCES:
                raise ValueError("source outside declared simulated interface")
            if type(o.source_sequence) is not int or o.source_sequence <= sequences[o.source]:
                raise ValueError("source sequence must strictly increase")
            sequences[o.source] = o.source_sequence
            numeric(o.sampled_at_s, "sample clock", 0., e.time_s)
            numeric(o.importance, "importance", 0., 1.)
            if o.kind not in ('simulated_observation', 'imagined'):
                raise ValueError("unknown observation kind")
            if o.action_id is not None:
                if o.action_id in action_ids:
                    raise ValueError('a query can have only one receipt per tick')
                action_ids.add(o.action_id)
                p = self.pending.get(o.action_id)
                if (not p or p['topic'] != o.topic or o.kind != 'simulated_observation'
                        or o.sampled_at_s <= p['submitted_at_s']
                        or e.time_s > p['expires_at_s']):
                    raise ValueError("no matching preceding submitted query")
        topics.add(e.goal.topic)
        if len(topics)>LIMITS['topics']:
            raise ValueError("world topic capacity exceeded")
        return payload, False

    def _policy(self, e, p, conflict, body, accessible):
        g = e.goal
        remaining = g.deadline_s-e.time_s if self.config['deadline'] else math.inf
        act = p*g.safe_reward-(1-p)*g.unsafe_cost-g.action_cost
        can_act = remaining >= g.action_duration_s
        act_value = act if can_act else -math.inf
        wait = -g.wait_cost_per_s*min(g.query_latency_s, max(0., remaining))
        prob_one = .9*p+.1*(1-p)
        expected_after = (prob_one*max(0., update(p, 1)*g.safe_reward-
            (1-update(p, 1))*g.unsafe_cost-g.action_cost) +
            (1-prob_one)*max(0., update(p, 0)*g.safe_reward-
            (1-update(p, 0))*g.unsafe_cost-g.action_cost))
        information_gain = entropy(p) - prob_one*entropy(update(p,1)) - (1-prob_one)*entropy(update(p,0))
        pending = next((q for q in self.pending.values() if q['topic']==g.topic), None)
        can_query = remaining >= g.query_latency_s+g.action_duration_s and len(self.pending)<LIMITS['pending']
        query_value = expected_after-g.query_cost-g.wait_cost_per_s*g.query_latency_s if can_query else -math.inf
        # Finite decision problem: abstaining has zero terminal payoff. Waiting
        # has a stated delay cost. It is chosen only for a pending receipt.
        choice = 'act' if act_value>0. else 'abstain'
        if query_value>max(0., act_value)+1e-12 and pending is None:
            choice='query'
        if pending is not None:
            delay_left=max(0.,pending['expected_ready_s']-e.time_s)
            waiting_value=expected_after-g.wait_cost_per_s*delay_left
            if remaining>=delay_left+g.action_duration_s and waiting_value>max(0.,act_value):
                choice='wait_for_receipt'
            elif choice!='act':
                choice='wait_for_receipt'
        if not accessible:
            choice='no_shared_access'
        if body['critical'] or not body['valid'] or body['optional_pause'] or body['protective']:
            choice='hold_for_body'
        if g.desired_command=='stand':
            choice='stand'
        # JSON cannot encode infinities: infeasible alternatives use null.
        finite = lambda v: v if math.isfinite(v) else None
        return dict(kind=choice, command=g.desired_command if choice=='act' else 'stand',
            topic=g.topic, environment_probability_safe=p,
            recorded_conflict=conflict, action_value=finite(act_value),
            query_value=finite(query_value), wait_value=wait,
            expected_information_gain_bits=information_gain,
            deadline_remaining_s=finite(remaining), query_already_pending=bool(pending),
            reason='body_gate' if choice=='hold_for_body' else 'consequence_and_delay_comparison',
            probabilities_are_environment_beliefs=True)

    def step(self, e, body):
        payload, cached = self.validate(e, body)
        if cached:
            return deepcopy(self.cache[e.id]['result'])
        work = deepcopy(self)
        result = work._advance(e, body)
        work.cache[e.id] = dict(request=payload, result=deepcopy(result))
        work.cache = dict(list(work.cache.items())[-LIMITS['cache']:])
        work.last_time_s=e.time_s; work.last=deepcopy(result); work.total_ticks+=1
        self.__dict__=work.__dict__
        return deepcopy(result)

    def _advance(self, e, body):
        units=12; now=e.time_s
        expired=[a for a,p in self.pending.items() if p['expires_at_s']<now]
        for a in expired:
            units+=1; self.pending.pop(a); self.expired_action_count+=1
        if not self.config['memory']:
            self.world={}; self.latest={}
        self.world.setdefault(e.goal.topic, dict(probability=.5,last_sample_s=None,support=[]))
        expired_topics=[]
        for topic,w in self.world.items():
            units+=1
            if self.config['freshness'] and w['last_sample_s'] is not None and now-w['last_sample_s']>6.:
                w['probability']=.5; w['support']=[]; expired_topics.append(topic)

        candidates=[dict(id='goal:'+e.goal.id,topic=e.goal.topic,value=None,
            score=1.5 if self.config['attention'] else -.5,
            kind='goal',source='current_user_task',support=[])]
        for o in e.observations:
            units+=1
            if o.kind!='simulated_observation':
                continue
            fresh=not self.config['freshness'] or now-o.sampled_at_s<=6.
            if fresh:
                candidates.append(dict(id=o.id,topic=o.topic,value=o.value,
                    score=o.importance+(2. if self.config['attention'] and o.topic==e.goal.topic else 0.),
                    kind='perception',source=o.source,support=[o.id]))
        if self.config['memory']:
            for topic,o in self.latest.items():
                units+=1
                if self.config['freshness'] and now-o['sampled_at_s']>6.:
                    continue
                candidates.append(dict(id=o['id'],topic=topic,value=o['value'],
                    score=.3+(2. if self.config['attention'] and topic==e.goal.topic else 0.),
                    kind='memory',source=o['source'],support=[o['id']]))
        candidates.sort(key=lambda q:(-q['score'],q['id']))
        selected=[]; seen=set()
        for q in candidates:
            units+=1
            if q['topic'] not in seen:
                selected.append(q);seen.add(q['topic'])
            if len(selected)==LIMITS['workspace']:
                break
        packet=deepcopy(selected) if self.config['broadcast'] else []
        accessible={q['topic'] for q in packet}
        matched=[]; ignored=[]; conflicts=[]
        groups={p['group_key'] for p in self.provenance if p['used_independently']}
        group_values={}
        for q in self.provenance:
            if q.get('kind')=='simulated_observation':
                group_values.setdefault(q['group_key'],set()).add(q['value'])
        batch={};acquisition_conflicts=set()
        for o in e.observations:
            units+=1
            key=o.topic+':'+o.correlation_id
            fresh=not self.config['freshness'] or now-o.sampled_at_s<=6.
            independent=(key not in groups or not self.config['correlation'])
            inconsistent=(self.config['correlation'] and o.kind=='simulated_observation' and fresh
                and bool(group_values.get(key,set())-{o.value}))
            if inconsistent:
                acquisition_conflicts.add(o.topic)
                w=self.world.setdefault(o.topic,dict(probability=.5,last_sample_s=None,support=[]))
                w['probability']=.5;w['support']=[];w['last_sample_s']=None
            use=(o.kind=='simulated_observation' and fresh and independent and o.topic in accessible)
            use=use and not inconsistent
            if use:
                w=self.world.setdefault(o.topic,dict(probability=.5,last_sample_s=None,support=[]))
                w['probability']=min(.999,max(.001,update(w['probability'],o.value)))
                w['last_sample_s']=o.sampled_at_s
                w['support']=(w['support']+[o.id])[-8:]
                groups.add(key);batch.setdefault(o.topic,set()).add(o.value)
            elif o.kind=='simulated_observation':
                ignored.append(dict(id=o.id,reason='expired' if not fresh else
                    ('inconsistent_acquisition' if inconsistent else
                     ('correlated_acquisition' if not independent else 'outside_shared_packet'))))
            if o.action_id is not None:
                matched.append(dict(observation_id=o.id,action_id=o.action_id,
                    delay_s=now-self.pending[o.action_id]['submitted_at_s']))
                self.pending.pop(o.action_id)
                for record in self.action_history:
                    if record['event_id']==o.action_id:
                        record.update(query_acquisition_confirmed=True,confirmed_at_s=now,
                            confirmation_observation_id=o.id,confirmation_source=o.source)
                        break
            self.source_sequences[o.source]=o.source_sequence
            self.provenance.append(dict(id=o.id,group_key=key,used_independently=use,
                sampled_at_s=o.sampled_at_s,source=o.source,value=o.value,kind=o.kind))
            if o.kind=='simulated_observation':group_values.setdefault(key,set()).add(o.value)
            entry=dict(**asdict(o),received_at_s=now,origin_event=e.id,used_independently=use)
            self.entries.append(entry)
            if o.kind=='simulated_observation' and fresh:
                self.latest[o.topic]=deepcopy(entry)
        conflicts=sorted(acquisition_conflicts|{t for t,v in batch.items() if len(v)>1})
        self.entries=self.entries[-LIMITS['memory']:]
        self.provenance=self.provenance[-LIMITS['provenance']:]
        retained={r['id'] for r in self.entries}
        for topic,row in self.world.items():
            if any(s not in retained for s in row['support']):
                row['probability']=.5;row['support']=[];row['last_sample_s']=None
        self.latest={t:o for t,o in self.latest.items() if o['id'] in retained}
        w=self.world[e.goal.topic]
        p=w['probability'] if e.goal.topic in accessible else .5
        policy=self._policy(e,p,e.goal.topic in conflicts,body,e.goal.topic in accessible)
        units+=6
        if units>LIMITS['work_units']:
            raise ValueError('cognitive work quota exceeded atomically')
        ids=[q['id'] for q in packet]
        consumer_ids={k:list(ids) for k in ('world_model','planner','reporter')}
        # Supports may age out of episodic memory. Drop links together with
        # their belief, rather than allowing source-free accumulated certainty.
        for topic,row in self.world.items():
            if any(s not in retained for s in row['support']):
                row['probability']=.5;row['support']=[];row['last_sample_s']=None
        result=dict(event_id=e.id,time_s=now,goal=asdict(e.goal),
            attention=dict(capacity=LIMITS['workspace'],selected_ids=[q['id'] for q in selected],
                accessible_ids=ids,focused_topics=[q['topic'] for q in selected],
                excluded_ids=[q['id'] for q in candidates if q not in selected]),
            packet=packet,consumer_ids=consumer_ids,plan=policy,
            world=deepcopy(self.world),expired_topics=expired_topics,
            matched_receipts=matched,ignored_observations=ignored,body_observation=deepcopy(body),
            acquisition_conflict_topics=sorted(acquisition_conflicts),
            work_units=units,work_quota=LIMITS['work_units'],
            occupancy=dict(memory=len(self.entries),topics=len(self.world),pending=len(self.pending),
                provenance=len(self.provenance),event_cache=min(LIMITS['cache'],len(self.cache)+1)),
            monitor=dict(shared_packet=all(v==ids for v in consumer_ids.values()),
                support_traceable=all(s in retained for r in self.world.values() for s in r['support']),
                confidence_calibration=False,body_model_learning=False),
            query_proposal=dict(action_id=e.id,topic=e.goal.topic) if policy['kind']=='query' else None,
            physically_applied=False,excluded_reading_items=[5,6,7])
        return result

    def record_execution(self, event_id, submitted_at_s, receipt):
        """A proposal is submitted only after the actual body tick permits it.

        A query submission is not proof of acquisition: only a later external
        observation can confirm its result. Movement uses actual V06 telemetry.
        """
        identity(event_id,'action event');numeric(submitted_at_s,'action time')
        if event_id not in self.cache:
            raise ValueError('action has no preceding cognitive proposal')
        r=self.cache[event_id]['result'];proposal=r['query_proposal']
        if receipt.get('query_submitted'):
            if not proposal or len(self.pending)>=LIMITS['pending']:
                raise ValueError('query submission has no capacity or proposal')
            self.pending[event_id]=dict(topic=proposal['topic'],submitted_at_s=submitted_at_s,
                expected_ready_s=submitted_at_s+r['goal']['query_latency_s'],
                expires_at_s=submitted_at_s+30.,status='submitted_unconfirmed')
        self.action_history.append(dict(event_id=event_id,time_s=submitted_at_s,**deepcopy(receipt)))
        self.action_history=self.action_history[-LIMITS['memory']:]
        r['execution_receipt']=deepcopy(receipt)
        r['occupancy']['pending']=len(self.pending)
        if self.last and self.last['event_id']==event_id:
            self.last['execution_receipt']=deepcopy(receipt)

    def checkpoint(self):
        payload=canonical(dict(schema=SCHEMA,config=self.config,
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            state={k:deepcopy(v) for k,v in self.__dict__.items() if k!='config'}))
        return dict(payload=payload,sha256=digest(payload))

    @classmethod
    def restore(cls, checkpoint):
        try:
            p=deepcopy(checkpoint['payload'])
            if checkpoint['sha256']!=digest(p) or p['schema']!=SCHEMA:
                raise ValueError('cognitive checkpoint integrity/version mismatch')
            if p['source_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
                raise ValueError('cognitive source differs from checkpoint')
            obj=cls(**p['config']);obj.__dict__.update(p['state'])
            for k,limit in [('entries',128),('world',16),('pending',8),('action_history',128),('provenance',256),('cache',32)]:
                if len(getattr(obj,k))>limit:
                    raise ValueError('checkpoint exceeds '+k+' bound')
            if set(obj.source_sequences)!=SOURCES:
                raise ValueError('source counters differ')
            for row in obj.world.values():numeric(row['probability'],'world probability',0.,1.)
            return obj
        except (KeyError,TypeError,AttributeError) as exc:
            raise ValueError('malformed cognitive checkpoint') from exc
