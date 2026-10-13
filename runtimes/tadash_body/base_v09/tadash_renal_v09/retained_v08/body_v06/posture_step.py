"""Bounded bilateral posture and executed stepping on the finite V06 body.

A constant-height, two-horizontal-axis inverted pendulum with a bounded tail
flywheel, centre-contact pressure limits, and 3-link inverse kinematics.
This is a reduced engineering simulation, not a full musculoskeletal solver.
Slip inputs prescribe support displacement; friction failure is reported, not
turned into an invented successful recovery or a solved sliding-foot model.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import math
from pathlib import Path

from body_loop_v06 import CHANNELS, Inputs, number, unit, clamp
from pain_resilience_v04 import ResilientBody
from breath_motion_v06 import BreathMotionLoop, Environment, checksum
from contacts import ContactModel, norm, point_margin

ROOT=Path(__file__).parent
SCHEMA='tadash-posture-step/0.6'
COMMANDS={'stand','single_L','single_R','walk'}
PHASES={'double_support','shift','lift','single_support','walk_swing','lower',
        'protective_swing','settle','failed'}

def fingerprint():
    return checksum({n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
                     for n in ('posture_step.py','contacts.py','contact_design_v06.json',
                               'body_loop_v06.py','bilateral_sections.py')})

def zeros():
    return {c:0. for c in CHANNELS}

def cross3(a,b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

def smooth(p):
    return p*p*p*(10.-15.*p+6.*p*p)

def vec2(v,name,limit):
    if not isinstance(v,(list,tuple)) or len(v)!=2:
        raise ValueError(name+': two coordinates required')
    return [number(x,name,-limit,limit) for x in v]

@dataclass(frozen=True)
class GaitEnvironment:
    body: Inputs=field(default_factory=lambda:Inputs(dt_s=.05))
    command: str='stand'
    step_length_m: float=.12
    friction: dict=field(default_factory=lambda:{'L':.6,'R':.6})
    inactive_patches: dict=field(default_factory=dict)
    external_impulse_N_s: list=field(default_factory=lambda:[0.,0.])
    prescribed_slip_m: dict=field(default_factory=dict)
    airway_capacity: float=1.
    ambient_oxygen_factor: float=1.
    request_paced_breath: bool=False
    protective_steps_enabled: bool=True
    tail_enabled: bool=True

@dataclass
class PostureState:
    time_s: float=0.
    com_m: list=field(default_factory=lambda:[0.,0.])
    velocity_m_s: list=field(default_factory=lambda:[0.,0.])
    reference_com_m: list=field(default_factory=lambda:[0.,0.])
    feet_m: dict=field(default_factory=lambda:{'L':[.196,0.,0.],'R':[-.196,0.,0.]})
    phase: str='double_support'
    stance: str='L'
    next_swing: str='R'
    swing: dict|None=None
    settle_s: float=0.
    walk_steps: int=0
    protective_steps: int=0
    last_command: str='stand'
    failed_reason: str|None=None
    reflex_recovery: bool=False
    tail_angle_rad: list=field(default_factory=lambda:[0.,0.])
    tail_velocity_rad_s: list=field(default_factory=lambda:[0.,0.])
    joint_rates_rad_s: dict=field(default_factory=zeros)
    previous_guard_fraction: dict=field(default_factory=lambda:{c:1. for c in CHANNELS})
    events: list=field(default_factory=list)

class PostureLoop:
    def __init__(self,*,coupling=None,design=None,initial_posture=None):
        self.coupling=coupling if coupling is not None else BreathMotionLoop()
        fixture=json.loads((ROOT/'contact_design_v06.json').read_text())
        if design is not None and design!=fixture:raise ValueError('contact design fixture mismatch')
        self.design=deepcopy(fixture)
        self.contact=ContactModel(self.design)
        self.state=PostureState(**deepcopy(initial_posture or {}))
        self.state.time_s=self.coupling.body.state.time_s
        self.origin=asdict(self.state)
        self.last=None
        self._validate_state()

    @property
    def body(self):
        return self.coupling.body

    @property
    def weight(self):
        return self.design['mass_kg']*self.design['gravity_m_s2']

    @property
    def omega(self):
        return math.sqrt(self.design['gravity_m_s2']/self.design['com_height_m'])

    def _validate_state(self):
        s=self.state
        number(s.time_s,'posture clock')
        if abs(s.time_s-self.body.state.time_s)>1e-8:
            raise ValueError('posture/body clock mismatch')
        vec2(s.com_m,'COM',100.); vec2(s.velocity_m_s,'velocity',100.)
        vec2(s.reference_com_m,'COM reference',100.)
        if set(s.feet_m)!={'L','R'}:
            raise ValueError('two feet required')
        for f in s.feet_m.values():
            if not isinstance(f,list) or len(f)!=3:
                raise ValueError('foot coordinates invalid')
            for x in f[:2]:number(x,'foot coordinate',-100.,100.)
            number(f[2],'foot height',0.,.3)
        if s.phase not in PHASES or s.stance not in ('L','R') or s.next_swing not in ('L','R'):
            raise ValueError('invalid posture phase/side')
        if s.last_command not in COMMANDS:
            raise ValueError('invalid posture command')
        number(s.settle_s,'settle timer')
        for k in ('walk_steps','protective_steps'):
            v=getattr(s,k)
            if type(v) is not int or v<0:raise ValueError('invalid step counter')
        if s.failed_reason is not None and not isinstance(s.failed_reason,str):
            raise ValueError('invalid failure reason')
        if type(s.reflex_recovery) is not bool:raise ValueError('invalid reflex recovery flag')
        vec2(s.tail_angle_rad,'tail angle',self.design['tail_angle_limit_rad']+1e-8)
        vec2(s.tail_velocity_rad_s,'tail speed',self.design['tail_speed_limit_rad_s']+1e-8)
        if set(s.joint_rates_rad_s)!=set(CHANNELS):
            raise ValueError('joint rate channels mismatch')
        for v in s.joint_rates_rad_s.values():number(v,'joint rate',-100.,100.)
        if set(s.previous_guard_fraction)!=set(CHANNELS):raise ValueError('guard channels mismatch')
        for v in s.previous_guard_fraction.values():unit(v,'previous guard fraction')
        if len(s.events)>128:raise ValueError('unbounded event log')
        if s.swing is not None:
            q=s.swing
            if set(q)!={'side','kind','start','target','progress','duration_s'}:
                raise ValueError('invalid swing state')
            if q['side'] not in ('L','R') or q['kind'] not in ('lift','lower','walk','protective'):
                raise ValueError('invalid swing type')
            unit(q['progress'],'swing progress'); number(q['duration_s'],'swing duration',.2,2.)
            for k in ('start','target'):
                if len(q[k])!=3:raise ValueError('invalid swing coordinates')
                for v in q[k][:2]:number(v,'swing coordinate',-100.,100.)
                number(q[k][2],'swing height',0.,.3)

    def _validate_environment(self,e):
        if not isinstance(e,GaitEnvironment) or not isinstance(e.command,str) or e.command not in COMMANDS:
            raise ValueError('GaitEnvironment with supported command required')
        dt,_=self.body._validate_input(e.body)
        number(dt,'posture dt',.05,.1)
        number(e.step_length_m,'step length',.04,.30)
        if not isinstance(e.friction,dict) or set(e.friction)!={'L','R'}:raise ValueError('two friction coefficients required')
        for v in e.friction.values():number(v,'friction',0.,1.5)
        vec2(e.external_impulse_N_s,'external impulse',500.)
        if not isinstance(e.prescribed_slip_m,dict) or set(e.prescribed_slip_m)-{'L','R'}:raise ValueError('unknown slipping side')
        for v in e.prescribed_slip_m.values():vec2(v,'prescribed slip',.30)
        if not isinstance(e.inactive_patches,dict) or set(e.inactive_patches)-{'L','R'}:raise ValueError('unknown contact side')
        ids={p['id'] for p in self.design['patches']}
        for v in e.inactive_patches.values():
            if not isinstance(v,list) or any(not isinstance(x,str) for x in v) or len(v)!=len(set(v)) or set(v)-ids:
                raise ValueError('invalid inactive patch set')
        for k in ('airway_capacity','ambient_oxygen_factor'):unit(getattr(e,k),k)
        for k in ('request_paced_breath','protective_steps_enabled','tail_enabled'):
            if type(getattr(e,k)) is not bool:raise ValueError('boolean required: '+k)
        # This layer owns all joint requests and their speed/pacing/gas coupling.
        defaults=Inputs()
        for k in ('force_requests_N','postural_force_requests_N','speeds_m_s',
                  'respiratory_work_requested_W','aerobic_limit_W','oxygen_fraction',
                  'co2_adequacy_proxy','ventilation_ok','paced_breath','inhale_s','exhale_s'):
            if getattr(e.body,k)!=getattr(defaults,k):
                raise ValueError('posture controller owns input: '+k)
        return dt

    def _event(self,name,**kw):
        event={'t_s':self.state.time_s,'name':name,**kw}
        self.state.events.append(event); self.state.events=self.state.events[-128:]
        return event

    def _active(self):
        return [s for s in ('L','R') if self.state.feet_m[s][2]<1e-9
                and (self.state.swing is None or s!=self.state.swing['side'])]

    def _capture(self):
        return [c+v/self.omega for c,v in zip(self.state.com_m,self.state.velocity_m_s)]

    def _mean_feet(self):
        return [(self.state.feet_m['L'][k]+self.state.feet_m['R'][k])/2. for k in range(2)]

    def _target(self,e):
        s=self.state
        if self._pending_rest(e) and s.swing is None and s.phase!='single_support':
            return self._mean_feet()
        if s.phase in ('protective_swing','settle'):
            feet=deepcopy(s.feet_m)
            if s.swing is not None:feet[s.swing['side']]=s.swing['target']
            return [(feet['L'][k]+feet['R'][k])/2. for k in range(2)]
        if s.swing is not None or s.phase=='single_support':
            return s.feet_m[s.stance][:2]
        if e.command.startswith('single_'):
            return s.feet_m[e.command[-1]][:2]
        if e.command=='walk':
            return s.feet_m[s.stance][:2]
        return self._mean_feet()

    def _pose(self,feet=None,com=None):
        feet=feet or self.state.feet_m; com=com or self.state.com_m; d=self.design
        l1,l2,l3=d['leg_lengths_m']; hz=d['hock_height_m']
        hock_back=math.sqrt(l3*l3-hz*hz)
        result={}
        for side in ('L','R'):
            sign=1. if side=='L' else -1.
            hip=[com[0]+sign*d['hip_half_width_m'],com[1],d['hip_height_m']]
            foot=feet[side]; hock=[foot[0],foot[1]-hock_back,foot[2]+hz]
            delta=[b-a for a,b in zip(hip,hock)]; length=norm(delta)
            reachable=abs(l1-l2)+1e-8<length<l1+l2-1e-8
            u=[v/max(1e-12,length) for v in delta]
            a=(l1*l1-l2*l2+length*length)/(2.*max(1e-12,length))
            bend=math.sqrt(max(0.,l1*l1-a*a))
            forward=[-u[0]*u[1],1.-u[1]*u[1],-u[2]*u[1]]
            scale=norm(forward); forward=[v/max(1e-12,scale) for v in forward]
            knee=[hip[k]+a*u[k]+bend*forward[k] for k in range(3)]
            thigh=[knee[k]-hip[k] for k in range(3)]
            calf=[hock[k]-knee[k] for k in range(3)]
            flex=math.pi-math.acos(max(-1.,min(1.,(l1*l1+l2*l2-length*length)/(2*l1*l2))))
            angles={'hip_pitch':math.atan2(thigh[1],-thigh[2]),
                    'hip_roll':math.atan2(thigh[0],-thigh[2]),
                    'knee':flex,'ankle':math.atan2(calf[1],-calf[2])+math.atan2(hock_back,hz)}
            joints={'hip':hip,'knee':knee,'ankle':hock,'foot_anchor':list(foot)}
            error=max(abs(norm([knee[k]-hip[k] for k in range(3)])-l1),
                      abs(norm([hock[k]-knee[k] for k in range(3)])-l2),
                      abs(norm([foot[k]-hock[k] for k in range(3)])-l3))
            result[side]={'joints_m':joints,'angles_rad':angles,'reachable':reachable,
                          'segment_length_error_m':error}
        return result

    def _start_swing(self,side,kind,target,duration):
        s=self.state; s.stance='R' if side=='L' else 'L'
        s.swing={'side':side,'kind':kind,'start':list(s.feet_m[side]),
                 'target':list(target),'progress':0.,'duration_s':duration}
        s.phase={'lift':'lift','lower':'lower','walk':'walk_swing','protective':'protective_swing'}[kind]
        if kind=='protective':s.reflex_recovery=True
        self._event(kind+'_started',side=side,target_m=list(target))

    def _swing_feet(self,progress):
        feet=deepcopy(self.state.feet_m); q=self.state.swing
        if q is None:return feet
        p=clamp(progress); h=smooth(p)
        f=[a+(b-a)*h for a,b in zip(q['start'],q['target'])]
        if q['kind'] in ('walk','protective'):
            f[2]+=self.design['swing_height_m']*math.sin(math.pi*p)**2
        feet[q['side']]=f
        return feet

    def _pending_rest(self,e):
        b,g=self.body.state,self.coupling.gas
        raw=max((max((v for k,v in row.items() if k!='touch'),default=0.)
                 for row in e.body.stimuli.values()),default=0.)
        return (e.airway_capacity<.15 or g.usable_o2_L/2.<.78 or g.co2_store_L>.6
                or raw>=.65 or b.fuel_J<40000 or self.body.endurance.pause_requested
                or max(b.fatigue[c] for c in CHANNELS if '_' in c)>=.6
                or any(b.latched.values()))

    def _can_unload(self,side,e):
        s=self.state; stance='R' if side=='L' else 'L'; cp=self._capture()
        support=self.contact.solve(s.feet_m,[stance],s.feet_m[stance][:2],self.weight,e.inactive_patches)
        if not support['feasible'] or point_margin(support['polygon'],cp)<.008:
            return False
        if norm([s.com_m[k]-s.feet_m[stance][k] for k in range(2)])>.018 or norm(s.velocity_m_s)>.03:
            return False
        # Reject a lift if a supporting regional latch is already active.
        return not any(self.body.state.latched[k+'_'+stance] for k in ('hip','knee','ankle'))

    def _protective_target(self,side,e):
        stance='R' if side=='L' else 'L'; s=self.state
        cp=self._capture()
        support=self.contact.solve(s.feet_m,[stance],cp,self.weight,e.inactive_patches)
        if not support['feasible']:return None
        duration=.4
        p=support['cop_m']; future=[p[k]+(cp[k]-p[k])*math.exp(self.omega*duration) for k in range(2)]
        # Conservative centre separation for the retained 26 cm wide feet.
        if side=='L':future[0]=max(future[0],s.feet_m[stance][0]+.28)
        else:future[0]=min(future[0],s.feet_m[stance][0]-.28)
        start=s.feet_m[side]; delta=[future[k]-start[k] for k in range(2)]
        if norm(delta)>self.design['max_step_length_m']:
            return None
        target=[*future,0.]
        feet=deepcopy(s.feet_m); feet[side]=target
        ch=math.cosh(self.omega*duration); sh=math.sinh(self.omega*duration)
        future_com=[p[k]+(s.com_m[k]-p[k])*ch+s.velocity_m_s[k]/self.omega*sh for k in range(2)]
        if not all(pose['reachable'] for pose in self._pose(feet,future_com).values()):return None
        return target

    def _prepare(self,e,dt):
        s=self.state
        if s.phase=='failed':return
        pending=self._pending_rest(e)
        if s.swing is not None and s.swing['kind'] in ('walk','lift') and (pending or e.command=='stand'):
            side=s.swing['side']; self._start_swing(side,'lower',[*s.feet_m[side][:2],0.],.6)
        if s.phase=='single_support' and (pending or e.command!=s.last_command):
            side='R' if s.stance=='L' else 'L'
            self._start_swing(side,'lower',[*s.feet_m[side][:2],0.],.6)
        if s.phase=='settle':
            s.settle_s+=dt
            if s.settle_s>=.5 and norm(s.velocity_m_s)<.05:
                s.phase='double_support'; s.settle_s=0.; s.reflex_recovery=False
        # A physical capture-point margin, rather than the old balance proxy.
        current=self.contact.solve(s.feet_m,self._active(),self._capture(),self.weight,e.inactive_patches)
        margin=point_margin(current['polygon'],self._capture())
        if margin<-.008 and s.phase not in ('protective_swing','lower'):
            if e.protective_steps_enabled:
                side=s.swing['side'] if s.swing else ('R' if s.phase=='single_support' and s.stance=='L' else
                      ('L' if s.phase=='single_support' else s.next_swing))
                target=self._protective_target(side,e)
                if target is not None:
                    self._start_swing(side,'protective',target,.4)
                else:
                    self._event('protective_step_unreachable',side=side)
            else:
                self._event('protective_step_disabled')
        if s.swing is None and s.phase not in ('settle','failed') and not pending:
            if e.command.startswith('single_'):
                s.stance=e.command[-1]; side='R' if s.stance=='L' else 'L'
                if s.phase!='single_support':
                    s.phase='shift'
                    if self._can_unload(side,e):
                        self._start_swing(side,'lift',[*s.feet_m[side][:2],.12],.7)
            elif e.command=='walk':
                side=s.next_swing; s.stance='R' if side=='L' else 'L'; s.phase='shift'
                if self._can_unload(side,e):
                    target=[s.feet_m[side][0],s.feet_m[s.stance][1]+e.step_length_m,0.]
                    self._start_swing(side,'walk',target,self.design['swing_time_s'])
            elif s.phase not in ('single_support','settle'):
                s.phase='double_support'
        s.last_command=e.command

    def _tail_request(self,desired_cmp,cop,dt,enabled):
        s=self.state; d=self.design
        if not enabled:return [0.,0.]
        t=[self.weight*(desired_cmp[k]-cop[k]) for k in range(2)]
        # Restore tail slowly once ground pressure alone can do the work.
        if norm(t)<1e-8:
            t=[-18.*s.tail_angle_rad[k]-12.*s.tail_velocity_rad_s[k] for k in range(2)]
        limit=d['tail_torque_limit_Nm']; length=norm(t)
        if length>limit:t=[v*limit/length for v in t]
        inertia=d['tail_inertia_kg_m2']
        axis_limit=limit/math.sqrt(2.)
        acceleration_limit=axis_limit/inertia
        for k in range(2):
            angle=s.tail_angle_rad[k]; speed=s.tail_velocity_rad_s[k]
            def prediction(torque):
                new_speed=speed+torque/inertia*dt
                new_angle=angle+speed*dt+.5*torque/inertia*dt*dt
                lower=new_angle-min(0.,new_speed)**2/(2.*acceleration_limit)
                upper=new_angle+max(0.,new_speed)**2/(2.*acceleration_limit)
                return new_speed,lower,upper
            low,high=-axis_limit,axis_limit
            if prediction(low)[0]<-d['tail_speed_limit_rad_s'] or prediction(low)[1]<-d['tail_angle_limit_rad']:
                lo,hi=low,high
                for _ in range(40):
                    mid=(lo+hi)/2.; v,b,_=prediction(mid)
                    if v<-d['tail_speed_limit_rad_s'] or b<-d['tail_angle_limit_rad']:lo=mid
                    else:hi=mid
                low=hi
            if prediction(high)[0]>d['tail_speed_limit_rad_s'] or prediction(high)[2]>d['tail_angle_limit_rad']:
                lo,hi=low,high
                for _ in range(40):
                    mid=(lo+hi)/2.; v,_,b=prediction(mid)
                    if v>d['tail_speed_limit_rad_s'] or b>d['tail_angle_limit_rad']:hi=mid
                    else:lo=mid
                high=lo
            t[k]=max(low,min(high,t[k]))
        return t

    def _demands(self,contact,pose,next_pose,dt,grf):
        essential=zeros(); optional=zeros(); speeds=zeros(); rates=zeros()
        total=max(1e-12,contact['total_normal_N']); g=self.design['gravity_m_s2']
        swing=self.state.swing
        for side in ('L','R'):
            p=pose[side]; pn=next_pose[side]; j=p['joints_m']; angles=p['angles_rad']; na=pn['angles_rad']
            side_patches=[q for q in contact['patches'] if q['side']==side]
            load=contact.get('by_foot_N',{}).get(side,0.)
            if load>1e-9:
                cp=[sum(q['xy'][k]*contact['normal_N'][q['id']] for q in side_patches)/load for k in range(2)]+[0.]
                force=[grf[k]*load/total for k in range(2)]+[load]
            else:
                cp=list(j['foot_anchor']); force=[0.,0.,0.]
            points=[j['hip'],j['knee'],j['ankle'],j['foot_anchor']]
            masses=(14.,10.,8.)
            centres=[[(points[i][k]+points[i+1][k])/2. for k in range(3)] for i in range(3)]
            for idx,name in enumerate(('hip','knee','ankle')):
                c=name+'_'+side; joint=j[name]
                moment=cross3([cp[k]-joint[k] for k in range(3)],force)
                for centre,mass in zip(centres[idx:],masses[idx:]):
                    gravity=cross3([centre[k]-joint[k] for k in range(3)],[0.,0.,-mass*g])
                    moment=[a+b for a,b in zip(moment,gravity)]
                arm=self.body.sections[c]['external_load_arm_m']
                essential[c]=(norm(moment)+8.)/arm
                if name=='hip':
                    rate=norm([(na[a]-angles[a])/dt for a in ('hip_pitch','hip_roll')])
                else:rate=abs(na[name]-angles[name])/dt
                rates[c]=rate; speeds[c]=min(5.,arm*rate)
                inertia=(4.,2.,.6)[idx]
                motion=inertia*abs(rate-self.state.joint_rates_rad_s[c])/dt+2.*rate
                if swing is not None and side==swing['side'] and swing['kind'] in ('walk','lift'):
                    optional[c]=motion/arm
                else:essential[c]+=motion/arm
        return essential,optional,speeds,rates

    def _guarded_capacities(self,e):
        out={}; b=self.body.state
        hydration=min(1.,max(.5,b.free_water_L/110.))
        key=str(round(math.floor((hydration+1e-9)*10)/10,1))
        flow_ratio=min(1.,self.body.table[key]['flow_L_min']/self.body.table['1.0']['flow_L_min'])
        previous=self.state.previous_guard_fraction
        load_hazard={side:max(.30*clamp(b.previous_force_N[j+'_'+side]/self.body.sections[j+'_'+side]['external_force_ceiling_N'])
                             for j in ('hip','knee','ankle')) for side in ('L','R')}
        for c,a in self.body.sections.items():
            perf=e.body.regional_perfusion.get(c,1.)*flow_ratio
            tendon=e.body.tendon_integrity.get(c,1.)
            capacity=min(a['muscle_force_N']*(1.-.5*b.fatigue[c])*a['muscle_moment_arm_m']*perf,
                         a['tendon_allowable_force_N']*tendon*a['muscle_moment_arm_m'],
                         a['bone_allowable_moment_Nm'],a['joint_allowable_moment_Nm'])/a['external_load_arm_m']
            anticipated=1.-load_hazard[c[-1]] if c.startswith(('hip_','knee_','ankle_')) else 1.
            out[c]=capacity*min(previous[c],anticipated)
        return out

    def _preview(self,contact,cop,desired_cmp,proposed_feet,dt,e):
        s=self.state; tail=self._tail_request(desired_cmp,cop,dt,e.tail_enabled)
        m=self.design['mass_kg']; h=self.design['com_height_m']
        acceleration=[self.omega*self.omega*(s.com_m[k]-cop[k])-tail[k]/(m*h) for k in range(2)]
        next_com=[s.com_m[k]+s.velocity_m_s[k]*dt+.5*acceleration[k]*dt*dt for k in range(2)]
        pose=self._pose(); next_pose=self._pose(proposed_feet,next_com)
        demand=self._demands(contact,pose,next_pose,dt,[m*v for v in acceleration])
        return tail,pose,next_pose,*demand

    def step(self,e=GaitEnvironment()):
        self._validate_state(); dt=self._validate_environment(e)
        s=self.state; before=asdict(s); old_events=len(s.events)
        for k,v in enumerate(e.external_impulse_N_s):
            s.velocity_m_s[k]+=v/self.design['mass_kg']
        if norm(e.external_impulse_N_s)>0:self._event('external_impulse',impulse_N_s=e.external_impulse_N_s)
        for side,delta in e.prescribed_slip_m.items():
            if side in self._active():
                for k in range(2):s.feet_m[side][k]+=delta[k]
                self._event('prescribed_support_slip',side=side,displacement_m=delta)
        self._prepare(e,dt)
        feet_used=deepcopy(s.feet_m); cp_before=self._capture(); target=self._target(e)
        distance=norm([target[k]-s.reference_com_m[k] for k in range(2)])
        ref_fraction=min(1.,.10*dt/max(1e-12,distance))
        s.reference_com_m=[s.reference_com_m[k]+ref_fraction*(target[k]-s.reference_com_m[k]) for k in range(2)]
        reference=target if s.reflex_recovery else s.reference_com_m
        desired_a=[-9.*(s.com_m[k]-reference[k])-6.*s.velocity_m_s[k] for k in range(2)]
        accel_limit=3. if s.reflex_recovery else .6
        accel_norm=norm(desired_a)
        if accel_norm>accel_limit:desired_a=[v*accel_limit/accel_norm for v in desired_a]
        desired_cmp=[s.com_m[k]-self.design['com_height_m']/self.design['gravity_m_s2']*desired_a[k] for k in range(2)]
        contact=self.contact.solve(feet_used,self._active(),desired_cmp,self.weight,e.inactive_patches)
        if not contact['feasible']:
            s.failed_reason='no_pressure_feasible_support'; s.phase='failed'
            cop=list(s.com_m)
        else:cop=contact['cop_m']
        if contact['feasible'] and norm([desired_cmp[k]-cop[k] for k in range(2)])<1e-9:
            restoring=self._tail_request(desired_cmp,cop,dt,e.tail_enabled)
            shifted=self.contact.solve(feet_used,self._active(),
                       [desired_cmp[k]-restoring[k]/self.weight for k in range(2)],self.weight,e.inactive_patches)
            if shifted['feasible']:contact=shifted; cop=contact['cop_m']
        q=s.swing; proposal=(min(1.,q['progress']+dt/q['duration_s']) if q else 0.)
        proposed_feet=self._swing_feet(proposal)
        omega=self.omega; h=self.design['com_height_m']; m=self.design['mass_kg']; inertia=self.design['tail_inertia_kg_m2']
        preview=self._preview(contact,cop,desired_cmp,proposed_feet,dt,e)
        tail_req,pose,next_pose,essential,optional,speeds,rates=preview
        capacities=self._guarded_capacities(e)
        loaded=[j+'_'+side for side in self._active() for j in ('hip','knee','ankle')
                if contact.get('by_foot_N',{}).get(side,0.)>self.weight*.005]
        def adequate(p):
            return all(p[3][c]<=capacities[c]*.985 for c in loaded)
        adjusted=False
        if contact['feasible'] and not adequate(preview) and s.reflex_recovery:
            # Small contact-pressure adjustments, constrained by the old patch
            # geometry and current joint ceilings, before spending more force.
            best=None
            for dx in (0.,-.006,.006,-.012,.012):
                for dy in (-.004,-.008,-.012,-.02,-.03,.004,.008):
                    candidate=self.contact.solve(feet_used,self._active(),[cop[0]+dx,cop[1]+dy],self.weight,e.inactive_patches)
                    if not candidate['feasible']:continue
                    trial=self._preview(candidate,candidate['cop_m'],desired_cmp,proposed_feet,dt,e)
                    if adequate(trial):
                        cost=norm([candidate['cop_m'][k]-cop[k] for k in range(2)])
                        if best is None or cost<best[0]:best=(cost,candidate,trial)
            if best is not None:
                _,contact,preview=best; cop=contact['cop_m']; adjusted=True
                tail_req,pose,next_pose,essential,optional,speeds,rates=preview
        tail_force=norm(tail_req)/self.body.sections['tail']['external_load_arm_m']
        essential['tail']=tail_force
        tail_mid=[s.tail_velocity_rad_s[k]+.5*tail_req[k]/inertia*dt for k in range(2)]
        speeds['tail']=min(5.,self.body.sections['tail']['external_load_arm_m']*norm(tail_mid))
        if s.phase=='failed':essential=optional=zeros(); tail_req=[0.,0.]
        active_request=e.command!='stand' and s.phase!='failed'
        body_input=replace(e.body,force_requests_N=optional,postural_force_requests_N=essential,speeds_m_s=speeds)
        f=self.coupling.step(Environment(body=body_input,activity=1. if active_request else 0.,
                    support_quality=1.,ambient_oxygen_factor=e.ambient_oxygen_factor,
                    airway_capacity=e.airway_capacity,request_paced_breath=e.request_paced_breath))
        actual=f['motor']['postural_force_N']; actual_optional=f['motor']['optional_force_N']
        s.previous_guard_fraction=deepcopy(f['motor']['hazard_fraction_cap'])
        stance_channels=[j+'_'+side for side in self._active() for j in ('hip','knee','ankle')
                         if contact.get('by_foot_N',{}).get(side,0.)>self.weight*.005]
        support_gain=min((actual[c]/essential[c] for c in stance_channels if essential[c]>1e-9),default=0.)
        tail_gain=actual['tail']/tail_force if tail_force else 0.
        torque=[v*tail_gain for v in tail_req]
        new_tail_angle=[s.tail_angle_rad[k]+s.tail_velocity_rad_s[k]*dt+.5*torque[k]/inertia*dt*dt for k in range(2)]
        new_tail_speed=[s.tail_velocity_rad_s[k]+torque[k]/inertia*dt for k in range(2)]
        # Exact constant-input LIPM integration in each horizontal axis.
        cmp=[cop[k]+torque[k]/self.weight for k in range(2)]
        ch=math.cosh(omega*dt); sh=math.sinh(omega*dt)
        pos=[cmp[k]+(s.com_m[k]-cmp[k])*ch+s.velocity_m_s[k]/omega*sh for k in range(2)]
        vel=[omega*(s.com_m[k]-cmp[k])*sh+s.velocity_m_s[k]*ch for k in range(2)]
        desired_grf=[m*(vel[k]-s.velocity_m_s[k])/dt for k in range(2)]
        friction_limit=sum(e.friction[p['side']]*contact['normal_N'].get(p['id'],0.) for p in contact['patches'])
        friction_saturated=norm(desired_grf)>friction_limit+1e-8
        actual_grf=list(desired_grf)
        if friction_saturated:
            scale=friction_limit/max(1e-12,norm(desired_grf)); actual_grf=[v*scale for v in desired_grf]
            a=[v/m for v in actual_grf]
            pos=[s.com_m[k]+s.velocity_m_s[k]*dt+.5*a[k]*dt*dt for k in range(2)]
            vel=[s.velocity_m_s[k]+a[k]*dt for k in range(2)]
            s.failed_reason='friction_limit_exceeded'; s.phase='failed'
        if support_gain<.999 and s.phase!='failed':
            s.failed_reason='insufficient_joint_or_energy_support'; s.phase='failed'
        if not all(p['reachable'] for p in pose.values()) and s.phase!='failed':
            s.failed_reason='leg_reach_exceeded'; s.phase='failed'
        if (max(abs(v) for v in new_tail_angle)>self.design['tail_angle_limit_rad']+1e-8
            or max(abs(v) for v in new_tail_speed)>self.design['tail_speed_limit_rad_s']+1e-8):
            s.failed_reason='tail_motion_or_actuation_limit'; s.phase='failed'
        if s.phase!='failed':
            s.tail_angle_rad=new_tail_angle; s.tail_velocity_rad_s=new_tail_speed
            s.com_m=pos; s.velocity_m_s=vel
            if q is not None:
                side=q['side']; motion_channels=[j+'_'+side for j in ('hip','knee','ankle')]
                if q['kind'] in ('walk','lift'):
                    gain=min((actual_optional[c]/optional[c] for c in motion_channels if optional[c]>1e-9),default=1.)
                else:
                    gain=min((actual[c]/essential[c] for c in motion_channels if essential[c]>1e-9),default=1.)
                q['progress']=min(1.,q['progress']+dt/q['duration_s']*min(1.,gain))
                s.feet_m=self._swing_feet(q['progress'])
                if q['progress']>=1.-1e-10:
                    kind=q['kind']; s.feet_m[side]=list(q['target']); s.swing=None
                    if kind=='lift':s.phase='single_support'; self._event('one_leg_hold',stance=s.stance,t_s=self.body.state.time_s)
                    else:
                        if kind=='walk':s.walk_steps+=1; s.next_swing='R' if side=='L' else 'L'
                        if kind=='protective':s.protective_steps+=1
                        s.phase='settle'; s.settle_s=0.
                        self._event('touchdown',side=side,kind=kind,position_m=list(s.feet_m[side]),t_s=self.body.state.time_s)
            s.joint_rates_rad_s=rates
        elif before['phase']!='failed':
            self._event('support_failure',reason=s.failed_reason,t_s=self.body.state.time_s)
        s.time_s=self.body.state.time_s
        after_pose=self._pose(); next_contact=self.contact.solve(s.feet_m,self._active(),self._capture(),self.weight,e.inactive_patches)
        margin=point_margin(next_contact['polygon'],self._capture())
        contact['feet_used_m']=feet_used
        contact['horizontal_force_N']=actual_grf
        contact['requested_horizontal_force_N']=desired_grf
        contact['friction_capacity_N']=friction_limit
        contact['friction_saturated']=friction_saturated
        contact['joint_support_fraction']=support_gain
        contact['cop_adjusted_for_joint_limits']=adjusted
        contact['constant_height_valid']=s.phase!='failed'
        if s.phase=='failed':
            # Normal forces above are required design loads, not achieved support.
            contact['required_normal_N']=contact['normal_N']
            contact['normal_N']={k:v*support_gain for k,v in contact['normal_N'].items()}
            contact['pressure_kpa']={p['id']:contact['normal_N'][p['id']]/p['area_m2']/1000. for p in contact['patches']}
            contact['total_normal_N']=sum(contact['normal_N'].values())
            contact['by_foot_N']={side:sum(contact['normal_N'][p['id']] for p in contact['patches'] if p['side']==side) for side in ('L','R')}
        f['posture']={**asdict(s),'target_com_m':target,'kinematics':after_pose,
                      'mechanical_simulation_terminated':s.phase=='failed',
                      'command':e.command,'external_impulse_N_s':e.external_impulse_N_s,
                      'prescribed_slip_m':e.prescribed_slip_m,
                      'tail_torque_requested_Nm':tail_req,'tail_torque_actual_Nm':torque,
                      'tail_inertia_kg_m2':inertia,'tail_kinetic_energy_J':.5*inertia*sum(v*v for v in s.tail_velocity_rad_s),
                      'events_this_frame':[ev for ev in s.events if ev not in before['events']]}
        f['contact']=contact
        f['balance']={'capture_point_m':self._capture(),'capture_before_m':cp_before,
                      'capture_margin_m':margin,'support_polygon_m':next_contact['polygon'],
                      'center_of_pressure_m':cop,'centroidal_moment_point_m':cmp,
                      'model_valid':s.phase!='failed','protective_step_executed':s.protective_steps>before['protective_steps'],
                      'tail_is_ground_contact':False}
        f['motor']['support_executed']=f['balance']['protective_step_executed']
        f['task']['postural_support_preserved_during_optional_pause']=bool(
            f['task']['nonessential_pause_executed'] and s.phase!='failed' and sum(actual.values())>0)
        self.last=f
        self._validate_state()
        return f

    def checkpoint(self):
        self._validate_state()
        p={'schema':SCHEMA,'source_fingerprint':fingerprint(),'coupling':self.coupling.checkpoint(),
           'posture':asdict(self.state),'origin':self.origin,'design':self.design}
        return {'payload':deepcopy(p),'sha256':checksum(p)}

    @classmethod
    def restore(cls,checkpoint):
        try:
            c=deepcopy(checkpoint); p=c['payload']
            if set(c)!={'payload','sha256'} or c['sha256']!=checksum(p) or p['schema']!=SCHEMA:
                raise ValueError('posture checkpoint integrity/version mismatch')
            if p['source_fingerprint']!=fingerprint():raise ValueError('posture source mismatch')
            obj=cls(coupling=BreathMotionLoop.restore(p['coupling']),design=p['design'],initial_posture=p['posture'])
            obj.origin=deepcopy(p['origin']); obj._validate_state()
            return obj
        except (KeyError,TypeError,AttributeError) as exc:
            raise ValueError('malformed posture checkpoint') from exc

    @classmethod
    def from_v05_checkpoint(cls,checkpoint):
        """Keep finite stocks, pain relay, endurance and gas clocks intact.

        Old knee/ankle wounds are split equally (never duplicated); fatigue and
        latches are representative per-leg settings. Hip and neutral stance are
        new explicit initializations, not reconstructed historical movement.
        """
        from breath_motion import BreathMotionLoop as OldLoop
        old=OldLoop.restore(checkpoint)
        def convert(state):
            state=deepcopy(state)
            for name in ('wounds_kg','fatigue','previous_force_N','return_fraction'):
                prev=state[name]; new={c:0. for c in CHANNELS}
                if name=='return_fraction':new={c:1. for c in CHANNELS}
                for c in ('elbow','tail'):new[c]=prev[c]
                for joint in ('knee','ankle'):
                    for side in ('L','R'):
                        new[joint+'_'+side]=prev[joint]/2. if name in ('wounds_kg','previous_force_N') else prev[joint]
                state[name]=new
            for name in ('latched','clear_s'):
                prev=state[name]; default=False if name=='latched' else 0.
                new={c:default for c in (*CHANNELS,'systemic')}
                for c in ('elbow','tail','systemic'):new[c]=prev[c]
                for joint in ('knee','ankle'):
                    for side in ('L','R'):new[joint+'_'+side]=prev[joint]
                state[name]=new
            return state
        b=ResilientBody(old.body.table,convert(asdict(old.body.state)),**asdict(old.body.parameters),
                        body_to_pain=old.body.body_to_pain,regional_guard=old.body.regional_guard,breath_gain=old.body.pain.gain)
        b.origin=convert(old.body.origin); b.pain=deepcopy(old.body.pain)
        b.endurance=deepcopy(old.body.endurance); b.endurance_origin=deepcopy(old.body.endurance_origin)
        coupling=BreathMotionLoop(body=b,initial_gas=asdict(old.gas))
        coupling.gas_origin=deepcopy(old.gas_origin); coupling.planner=deepcopy(old.planner)
        coupling.last_aerobic_W=old.last_aerobic_W; coupling.last_motor_W=old.last_motor_W
        return cls(coupling=coupling)
