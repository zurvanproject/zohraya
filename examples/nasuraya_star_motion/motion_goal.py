"""Explicit bounded route goal, persisted together with the existing body.

Only completed prior goals may be followed automatically. Starting a new goal
changes its waypoint cursor, never native time, stocks, history or guards.
Saved-tick continuation is supported; arbitrary mid-tick crash recovery is not.
"""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import math
from pathlib import Path
from run_bounded_route import route_targets

SCHEMA='nasuraya-motion-goal/1'
LIMITS={'prelude':6,'route':220,'closure':4}
UPPER=dict(shoulder_L=.35,shoulder_R=.35,elbow_L=1.2,elbow_R=1.2,head_pitch=-.1,head_yaw=0.)


def runtime():
    from unified_body_v2 import UnifiedBody
    from extension_state import attach,checkpoint,restore,sources
    from persistent_embodiment_v1 import digest
    return attach,checkpoint,restore,sources,digest


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class MotionGoal:
    def __init__(self,body,task):
        self.body=body;self.task=deepcopy(task);self.validate()

    @classmethod
    def start(cls,body,direction,goal_id):
        attach,checkpoint,restore,sources,digest=runtime()
        p=body.owner.physical
        if not isinstance(goal_id,str) or not goal_id or len(goal_id)>70:
            raise ValueError('bounded unique goal id required')
        if any(e.startswith(goal_id+':') for e in body.requests):raise ValueError('goal id already used')
        if p.star_enabled or p.state.phase!='double_support' or p.state.swing is not None:
            raise ValueError('settled completed prior route required')
        if any(p.star_started[s]!=len(p.star_targets[s]) for s in ('L','R')):
            raise ValueError('incomplete prior route cannot be discarded')
        if any(p.state.feet_m[s][2]!=0. for s in ('L','R')):
            raise ValueError('grounded feet required')
        native=body.checkpoint();prior=checkpoint(body)
        home=deepcopy(p.state.feet_m);plan=route_targets(home,direction)
        attach(body,dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=plan,cursor_semantics='confirmed'))
        if body.checkpoint()!=native:raise ValueError('new goal changed native state')
        task=dict(goal_id=goal_id,direction=direction,home=home,plan=plan,phase='prelude',
            counts={k:0 for k in LIMITS},elapsed=0,vetoes=0,status='running',stop_reason=None,
            landings=[],start_time_s=p.state.time_s,start_walk_steps=p.state.walk_steps,
            start_revision=body.revision,prior_sha256=prior['sha256'],
            prior_cursor=deepcopy(prior['payload']['controller']['star_started']))
        return cls(body,task)

    def validate(self):
        t=self.task;p=self.body.owner.physical
        if not isinstance(t['goal_id'],str) or not t['goal_id'] or len(t['goal_id'])>70:
            raise ValueError('bounded goal id')
        if t['direction'] not in ('forward','reverse') or t['plan']!=route_targets(t['home'],t['direction']):
            raise ValueError('goal route contract')
        if p.star_targets!=t['plan'] or p.cursor_semantics!='confirmed':raise ValueError('goal/controller mismatch')
        if t['phase'] not in (*LIMITS,'done') or t['status'] not in ('running','completed','incomplete','physical_failure'):
            raise ValueError('goal status')
        if set(t['counts'])!=set(LIMITS) or any(type(t['counts'][k]) is not int or not 0<=t['counts'][k]<=LIMITS[k] for k in LIMITS):
            raise ValueError('goal budget')
        if type(t['elapsed']) is not int or t['elapsed']!=sum(t['counts'].values()):raise ValueError('goal clock/budget')
        if abs(p.state.time_s-t['start_time_s']-t['elapsed'])>1e-7:
            raise ValueError('goal/native time divergence')
        if self.body.revision!=t['start_revision']+t['elapsed']:raise ValueError('goal/native revision divergence')
        if len(t['landings'])!=sum(p.star_started.values()):raise ValueError('goal landing/cursor divergence')
        for side in ('L','R'):
            got=[e['position_m'] for e in t['landings'] if e['side']==side]
            if got!=t['plan'][side][:len(got)]:raise ValueError('goal touchdown order')
        if p.star_enabled!=(t['phase']=='route' and t['status']=='running'):raise ValueError('goal activation')
        if (t['phase']=='done')!=(t['status']!='running'):raise ValueError('goal terminal state')
        if t['phase']=='prelude' and (t['counts']['prelude']>=6 or t['counts']['route'] or t['counts']['closure']):
            raise ValueError('prelude budget state')
        if t['phase']=='route' and (t['counts']['prelude']!=6 or t['counts']['route']>=220 or t['counts']['closure']):
            raise ValueError('route budget state')
        if t['phase']=='closure' and (t['counts']['prelude']!=6 or t['counts']['closure']>=4):
            raise ValueError('closure budget state')

    def checkpoint(self):
        self.validate();attach,checkpoint,restore,sources,digest=runtime()
        payload=dict(schema=SCHEMA,goal_source_sha256=source_hash(),task=deepcopy(self.task),body=checkpoint(self.body))
        return dict(payload=payload,sha256=digest(payload))

    @classmethod
    def restore(cls,envelope):
        attach,checkpoint,restore,sources,digest=runtime()
        if set(envelope)!={'payload','sha256'} or digest(envelope['payload'])!=envelope['sha256']:
            raise ValueError('goal checksum')
        p=envelope['payload']
        if p['schema']!=SCHEMA or p['goal_source_sha256']!=source_hash():raise ValueError('goal source/version')
        return cls(restore(p['body']),p['task'])

    def request(self):
        self.validate();t=self.task
        if t['status']!='running':raise ValueError('goal already terminal')
        phase=t['phase'];upper=UPPER if phase!='closure' else {k:0. for k in UPPER}
        return dict(event_id=f"{t['goal_id']}:{t['elapsed']:03d}",
            at_utc=(datetime.fromisoformat(self.body.owner.wall_utc)+timedelta(seconds=1)).isoformat(),
            duration_s=1.,requested='walk' if phase=='route' else 'slow_breath',expected_revision=self.body.revision,
            external=dict(native=dict(upper_targets=deepcopy(upper)),sensors=dict(vision=dict(value=.25,
                source_id=f"{t['goal_id']}:floor:{t['elapsed']}",sampled_at_s=self.body.owner.physical.state.time_s,kind='declared_simulated_input'))))

    def step(self):
        request=self.request();t=self.task;phase=t['phase'];p=self.body.owner.physical
        before_time=p.state.time_s;before=deepcopy(p.star_started)
        receipt=self.body.cycle(**request);p=self.body.owner.physical
        new=[deepcopy(e) for e in p.state.events if e['name']=='touchdown' and e.get('kind')=='walk' and e['t_s']>before_time+1e-8]
        if len(new)!=sum(p.star_started[s]-before[s] for s in ('L','R')):
            raise ValueError('confirmed touchdown receipt mismatch')
        t['landings'].extend(new);t['counts'][phase]+=1;t['elapsed']+=1
        if not receipt['owner']['physical_model_valid']:
            t.update(phase='done',status='physical_failure',stop_reason=p.state.failed_reason);p.star_enabled=False
        elif phase=='prelude' and t['counts']['prelude']==LIMITS['prelude']:
            t['phase']='route';p.star_enabled=True
        elif phase=='route':
            t['vetoes']=t['vetoes']+1 if receipt['owner']['selected_action']!='walk' else 0
            complete=all(p.star_started[s]==len(t['plan'][s]) for s in ('L','R'))
            if complete or t['vetoes']>=3 or t['counts']['route']==LIMITS['route']:
                t['phase']='closure';p.star_enabled=False
                if not complete:t['stop_reason']='three consecutive native vetoes' if t['vetoes']>=3 else 'movement budget exhausted'
        elif phase=='closure' and t['counts']['closure']==LIMITS['closure']:
            complete=all(p.star_started[s]==len(t['plan'][s]) for s in ('L','R'))
            home=max(math.dist(p.state.feet_m[s],t['home'][s]) for s in ('L','R'))
            ok=complete and home<1e-9 and p.state.phase=='double_support'
            t['phase']='done';t['status']='completed' if ok else 'incomplete'
            if not ok and t['stop_reason'] is None:t['stop_reason']='home or closure contract'
        self.validate();return receipt
