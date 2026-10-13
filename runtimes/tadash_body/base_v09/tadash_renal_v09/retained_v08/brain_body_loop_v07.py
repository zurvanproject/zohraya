"""One actual V06 body tick per event; finite cognition on a slower schedule.

The safety bus is read directly from the physical owner before and after
decisions. There is no second body prediction, a learned motor model, or a
second resource stock. Incremental neural metabolism is not quantified.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'body_v06'))
from posture_step import PostureLoop, GaitEnvironment, Inputs, CHANNELS, norm
from cognitive_workspace_v07 import EnvironmentBrain, Goal, Observation, CognitiveEvent, canonical, digest, numeric, identity
from interoception_v07 import SensoryRoutes

SCHEMA='tadash-brain-body-loop/0.7'


@dataclass(frozen=True)
class BrainEnvironment:
    event_id: str
    event_sequence: int
    goal: Goal=field(default_factory=Goal)
    observations: tuple[Observation,...]=()
    physical: GaitEnvironment=field(default_factory=GaitEnvironment)


class BrainBodyLoop:
    def __init__(self, *, body=None, brain=None, cognition_interval_s=.5, homeostasis=True):
        self.physical=body if body is not None else PostureLoop()
        self.brain=brain if brain is not None else EnvironmentBrain()
        if type(homeostasis) is not bool:raise ValueError('homeostasis flag must be bool')
        self.homeostasis=homeostasis
        self.sensory=SensoryRoutes(self.physical)
        self.interval_s=numeric(cognition_interval_s,'cognitive interval',.1,2.)
        self.next_tick_s=self.physical.state.time_s
        self.command='stand'
        self.last_sequence=-1
        self.cache={}
        self.body_steps=0
        self.last_cognition=None
        self.last_receipt=None
        self.last_goal_id=None

    def _snapshot(self):
        p=self.physical;f=p.last
        valid=p.state.phase!='failed'
        # Fresh current owner state, with prior-tick realized guards. The V06
        # fast loop still evaluates the current physical input independently.
        critical=bool(p.body.state.latched['systemic'] or
            (f and (f['motor']['critical_stop'] or f['motor']['systemic_stop'])))
        conservation=self.sensory.conservation_pause()
        pause=bool((self.homeostasis and conservation['requested']) or p.body.endurance.pause_requested or p.coupling.planner.rest_latched or
            (f and f['task']['nonessential_pause_executed']))
        protective=bool(p.state.reflex_recovery or p.state.phase=='protective_swing')
        return dict(sampled_at_s=p.state.time_s,critical=critical,optional_pause=pause,
            valid=valid,protective=protective,source='V06_physical_owner',
            phase=p.state.phase,body_tick=self.body_steps)

    def step(self, e):
        if not isinstance(e,BrainEnvironment):raise ValueError('BrainEnvironment required')
        identity(e.event_id,'physical event id')
        if type(e.event_sequence) is not int or e.event_sequence<0:
            raise ValueError('physical event sequence required')
        EnvironmentBrain.validate_goal(e.goal)
        # The caller supplies environment disturbances, never a competing
        # motor command. The brain owns voluntary command arbitration.
        if e.physical.command!='stand':raise ValueError('physical command is owned by brain')
        self.physical._validate_environment(e.physical)
        request=canonical(asdict(e))
        if e.event_id in self.cache:
            old=self.cache[e.event_id]
            if old['request']!=request:raise ValueError('physical event id reused with altered input')
            return deepcopy(old['result'])
        if e.event_sequence<=self.last_sequence:
            raise ValueError('physical sequence must increase')
        now=self.physical.state.time_s
        is_tick=(now>=self.next_tick_s-1e-9 or bool(e.observations) or e.goal.id!=self.last_goal_id)
        ce=CognitiveEvent(e.event_id,now,e.goal,e.observations)
        body_snapshot=self._snapshot()
        if is_tick:self.brain.validate(ce,body_snapshot)
        # A transaction also protects against unexpected computation failures,
        # not just validated external errors. Only the live committed owner
        # receives the resulting single physical tick.
        work=deepcopy(self)
        cognition=None
        if is_tick:
            cognition=work.brain.step(ce,body_snapshot)
            work.command=cognition['plan']['command']
            work.next_tick_s=now+work.interval_s
            work.last_goal_id=e.goal.id
        if body_snapshot['critical'] or body_snapshot['optional_pause'] or not body_snapshot['valid'] or body_snapshot['protective']:
            work.command='stand'
        requested_command=work.command
        physical=replace(e.physical,command=requested_command)
        before_steps=work.physical.state.walk_steps
        before_feet=deepcopy(work.physical.state.feet_m)
        f=work.physical.step(physical)
        work.body_steps+=1
        sensory=work.sensory.observe(f,work.physical)
        after=f['posture'];stop=bool(f['motor']['critical_stop'] or f['motor']['systemic_stop'] or
            f['task']['nonessential_pause_executed'] or not f['balance']['model_valid'] or
            f['resilience']['nonessential_task_pause_request'] or f['task']['rest_latched'] or after['reflex_recovery'])
        grounded=all(abs(q[2])<1e-8 for q in after['feet_m'].values())
        query_submitted=bool(cognition and cognition['query_proposal'] and not stop and
            grounded and norm(after['velocity_m_s'])<.05)
        moved=sum(norm([after['feet_m'][s][k]-before_feet[s][k] for k in range(2)])
            +abs(after['feet_m'][s][2]-before_feet[s][2]) for s in ('L','R'))
        receipt=dict(requested_command=requested_command,
            voluntary_command_delivered=bool(requested_command!='stand' and not stop),
            executed_walk_touchdowns=after['walk_steps']-before_steps,
            foot_motion_m=moved,query_submitted=query_submitted,
            query_acquisition_confirmed=False,
            body_veto=stop,body_valid=f['balance']['model_valid'],
            body_frame_id=e.event_id,body_tick=work.body_steps,
            fuel_used_J=f['ledger']['fuel_used_J'],reserve_used_J=f['ledger']['reserve_used_J'])
        if cognition:
            work.brain.record_execution(e.event_id,f['t_s'],receipt)
            cognition=deepcopy(work.brain.last)
            work.last_cognition=cognition
        work.last_receipt=receipt
        if stop:work.command='stand'
        f['cognition']=dict(tick=is_tick,current=cognition,last=deepcopy(work.last_cognition),
            sensory_routes=sensory,conservation=work.sensory.conservation_pause(),
            execution_receipt=receipt,cognitive_tick_count=work.brain.total_ticks,
            physical_tick_count=work.body_steps,
            owner_advances_per_new_event=1,
            incremental_neural_metabolism_quantified=False)
        work.last_sequence=e.event_sequence
        # Keep cached output independent from the physical owner's last frame,
        # avoiding a recursive full-cognition history inside the body snapshot.
        work.physical.last={k:v for k,v in f.items() if k!='cognition'}
        work.physical.body.last={k:v for k,v in work.physical.body.last.items() if k!='cognition'}
        work.physical.coupling.last={k:v for k,v in work.physical.coupling.last.items() if k!='cognition'}
        work.cache[e.event_id]=dict(request=request,result=deepcopy(f))
        work.cache=dict(list(work.cache.items())[-32:])
        self.__dict__=work.__dict__
        return deepcopy(f)

    def checkpoint(self):
        p=canonical(dict(schema=SCHEMA,
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            body=self.physical.checkpoint(),brain=self.brain.checkpoint(),
            sensory=self.sensory.checkpoint(),homeostasis=self.homeostasis,
            scheduler={k:deepcopy(getattr(self,k)) for k in ('interval_s','next_tick_s','command',
                'last_sequence','cache','body_steps','last_cognition','last_receipt','last_goal_id')},
            last_body_frame=deepcopy(self.physical.last)))
        return dict(payload=p,sha256=digest(p))

    @classmethod
    def restore(cls, checkpoint):
        try:
            p=deepcopy(checkpoint['payload'])
            if p['schema']!=SCHEMA or digest(p)!=checkpoint['sha256']:
                raise ValueError('brain/body checkpoint integrity/version mismatch')
            if p['source_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
                raise ValueError('brain/body source differs from checkpoint')
            obj=cls(body=PostureLoop.restore(p['body']),brain=EnvironmentBrain.restore(p['brain']),homeostasis=p['homeostasis'])
            obj.sensory=SensoryRoutes.restore(p['sensory'],obj.physical)
            for k,v in p['scheduler'].items():setattr(obj,k,v)
            obj.physical.last=deepcopy(p['last_body_frame'])
            if len(obj.cache)>32 or obj.command not in {'stand','walk','single_L','single_R'}:
                raise ValueError('invalid scheduler checkpoint')
            if obj.brain.last_time_s is not None and obj.brain.last_time_s>obj.physical.state.time_s+1e-8:
                raise ValueError('cognitive clock exceeds physical owner clock')
            return obj
        except (KeyError,TypeError,AttributeError) as exc:
            raise ValueError('malformed brain/body checkpoint') from exc
