"""Persistent Embodiment Protocol 1.0 over Nasuraya's retained V09 owner.

All body outputs are Level B, uncalibrated engineering simulations. Physical
samples (A) and imagery (C) stay in separate evidence channels. One finite
energy/water/gas/renal/motor owner is retained; no second resource stock.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'base_v09/tadash_renal_v09'
sys.path.insert(0, str(BASE))
from renal_coupling_v09 import RenalMemoryLoop
from renal_body_v09 import RenalResilientBody
from renal_physiology_v09 import RenalInputs
from posture_step import GaitEnvironment, Inputs, point_margin
from interoception_v07 import SensoryRoutes
from actuated_breath_v1 import ActuatedBreath
from resource_audit_v06 import ConservationAudit
from run_balance_checks import GasAudit, PhysicsAudit
from renal_audit_v09 import SoluteAudit

SCHEMA = 'nasuraya-persistent-embodiment/1.0'
CAUSES = {'external_input', 'internal_regulation', 'simulated_action', 'time_decay'}
EMOTIONS = {'neutral', 'fear', 'anger', 'affection', 'curiosity'}
ACTIONS = {'observe', 'slow_breath', 'rapid_breath', 'breath_hold', 'protect',
           'cool', 'hydrate', 'refuel', 'rest', 'sleep', 'walk', 'single_L', 'single_R'}
JOINTS = {'head_yaw': (-.7, .7), 'head_pitch': (-.45, .45),
          'shoulder_L': (-1.0, 1.0), 'shoulder_R': (-1.0, 1.0),
          'elbow_L': (0.0, 1.5), 'elbow_R': (0.0, 1.5)}
MINIMUM = ('HR', 'RR', 'energy', 'hydration', 'temperature', 'sympathetic',
           'parasympathetic', 'muscle_tone', 'fatigue', 'pain', 'arousal',
           'valence', 'posture', 'balance', 'breath_depth', 'sleep_pressure')
UTC = timezone.utc
TEHRAN = ZoneInfo('Asia/Tehran')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def finite(x, name, lo=0.0, hi=1.0):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(name + ': finite value outside declared bounds')
    return float(x)


def clamp(x, lo=0.0, hi=1.0):
    return min(hi, max(lo, x))


def instant(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(d, datetime) or d.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    return d.astimezone(UTC)


def flatten(value, path=''):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items(): out.update(flatten(v, path + '/' + k))
        return out
    # Lists are atomic structured values, so inserting a pain episode is one
    # explicit cause-bearing change rather than a misleading index shuffle.
    return {path: deepcopy(value)}


def sources():
    names = ('persistent_embodiment_v1.py', 'actuated_breath_v1.py', 'phenotype_v1.json')
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        if path.exists():
            for key in os.listxattr(path): os.setxattr(tmp, key, os.getxattr(path, key))
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


class AccessoryBody(RenalResilientBody):
    """Pay bounded head/arm servo work from the existing vital energy budget."""
    accessory_requested_W = 0.0

    def step(self, i=Inputs()):
        requested = self.accessory_requested_W
        total = i.respiratory_work_requested_W + requested
        f = super().step(replace(i, respiratory_work_requested_W=total))
        paid = f['circulation']['respiratory_work_actual_W']
        fraction = clamp(paid / total) if total else 1.0
        f['accessory_motor'] = dict(requested_W=requested, paid_W=requested*fraction,
            paid_fraction=fraction, separate_resource_stock=False,
            accounting='included_in_shared_vital_energy_and_gas_consumption')
        f['circulation']['respiratory_work_actual_W'] = i.respiratory_work_requested_W * fraction
        f['circulation']['accessory_work_actual_W'] = requested * fraction
        return f


class PersistentEmbodiment:
    def __init__(self, owner, aux, wall_utc, migration):
        self.owner = owner
        self.aux = deepcopy(aux)
        self.wall_utc = instant(wall_utc).isoformat()
        self.migration = deepcopy(migration)
        self.revision = 0
        self.journal = []
        self.requests = {}
        self.results = {}
        self.last_result = None
        self.loaded_sha256 = None
        self._attach()

    @property
    def physical(self): return self.owner.memory.loop.physical

    def _attach(self):
        self.owner.body.__class__ = AccessoryBody
        self.owner.body.accessory_requested_W = 0.0
        self.physical.coupling.__class__ = ActuatedBreath
        self.physical.coupling.breath_mode = self.aux['breath_mode']

    @classmethod
    def bootstrap(cls, checkpoint, at_utc):
        owner = RenalMemoryLoop.restore(checkpoint)
        before = owner.checkpoint()
        now = instant(at_utc)
        aux = dict(heart_rate=60.0, sympathetic=.20, parasympathetic=.60,
            vascular_tone=.45, muscle_tone=.25, arousal=.25, valence=0.0,
            affiliative=.0, sleep_pressure=.35, guarding=0.0,
            emotion='neutral', emotion_intensity=0.0, guardian=False,
            breath_mode='normal', effective_rr=owner.memory.loop.physical.coupling.gas.rate_min,
            current_activity=0.0, uncertainty=0.0, unobserved_seconds=0.0,
            circadian_phase=0.0, biological_hour=0.0,
            upper_angles={j:0.0 for j in JOINTS}, upper_velocities={j:0.0 for j in JOINTS},
            proprioceptive_velocities={}, loads={}, contacts={}, pain_episodes=[],
            body_memory=[], physical_samples=[], imagery=[], prediction_history=[],
            accessory_energy_J=0.0, bootstrap_body_time_s=owner.body.state.time_s)
        migration = dict(source_schema=checkpoint['payload']['schema'],
            source_checkpoint_sha256=checkpoint['sha256'],
            source_library_file_id='synthetic-local-source',
            source_filename='synthetic-bootstrap',
            source_genome_library_file_id='synthetic-local-source',
            source_genome_version=35, physical_stocks_reset=False,
            old_pose_gas_pain_fatigue_memory_goal_and_deadline_retained=True,
            new_auxiliary_variables_are_explicit_design_initializations=True,
            historical_elapsed_wall_time_before_bootstrap_unknown=True,
            gap_policy='unobserved_pause: retain physical stocks and pose; decay declared auxiliary traces only',
            physical_sensor_attached=False)
        obj = cls(owner, aux, now, migration)
        obj._circadian(now)
        obj._initial_proprioception()
        if obj.owner.checkpoint() != before:
            raise ValueError('bootstrap altered retained owner')
        obj._record({}, obj.body(), 'external_input',
            'import exact V09 body; explicit initialization of new auxiliary variables', 0.0)
        return obj

    def _circadian(self, now):
        d = instant(now).astimezone(TEHRAN)
        hour = d.hour + d.minute/60.0 + d.second/3600.0
        self.aux['biological_hour'] = hour
        self.aux['circadian_phase'] = hour/24.0

    def _initial_proprioception(self):
        points = self.pose()['parts']
        v = self.physical.state.velocity_m_s
        self.aux['proprioceptive_velocities'] = {
            k: ([*v, 0.0] if k in ('pelvis','spine','head') else [0.0,0.0,0.0]) for k in points}
        # New upper-body encoder velocities are initialization assumptions;
        # actual old leg joint rates, tail rates, contacts remain available.
        contact = self.physical.contact.solve(self.physical.state.feet_m,
            self.physical._active(), self.physical._capture(), self.physical.weight, {})
        self.aux['contacts'] = {k:k.startswith('foot_') and points[k][2] < 1e-8 for k in points}
        self.aux['loads'] = {k:0.0 for k in points}
        for side in ('L','R'):
            self.aux['loads']['foot_'+side] = contact['by_foot_N'].get(side,0.0)

    def pose(self):
        p = self.physical; x,y = p.state.com_m; q = self.aux['upper_angles']
        parts = dict(pelvis=[x,y,1.42], spine=[x,y,1.80], head=[x,y,2.39])
        for side, sign in (('L',1),('R',-1)):
            shoulder=[x+sign*.35,y,2.06]; a=q['shoulder_'+side]; b=q['elbow_'+side]
            elbow=[shoulder[0],y+.43*math.sin(a),2.06-.43*math.cos(a)]
            hand=[elbow[0],elbow[1]+.43*math.sin(a+b),elbow[2]-.43*math.cos(a+b)]
            parts.update({f'shoulder_{side}':shoulder,f'arm_{side}':elbow,f'hand_{side}':hand})
            leg=p._pose()[side]['joints_m']
            parts.update({f'hip_{side}':leg['hip'], f'leg_{side}':leg['knee'],
                          f'ankle_{side}':leg['ankle'], f'foot_{side}':list(p.state.feet_m[side])})
        yaw,pitch=q['head_yaw'],q['head_pitch']
        for side,sign in (('L',1),('R',-1)):
            lx,ly,lz=sign*.15,-.025,.27
            zz=lz*math.cos(pitch)-ly*math.sin(pitch)
            yy=ly*math.cos(pitch)+lz*math.sin(pitch)
            parts['horn_'+side]=[x+lx*math.cos(yaw)-yy*math.sin(yaw),
                y+lx*math.sin(yaw)+yy*math.cos(yaw),2.39+zz]
        t=p.state.tail_angle_rad
        parts['tail']=[x+1.2*math.sin(t[0]), y-1.2*math.cos(t[0])*math.cos(t[1]),
                       1.42+1.2*math.sin(t[1])]
        return dict(frame='Tadash computational world: X left, Y forward, Z up; metres',
            self_location=[x,y,1.314], posture_phase=p.state.phase,
            parts=parts, head_orientation_rad=[pitch,0.0,yaw],
            spine_posture='retained constant-height upright fixture',
            pelvic_orientation_rad=[0.0,0.0,0.0], arm_joint_angles_rad=deepcopy(q),
            tail_orientation_rad=list(t), horn_orientation_rad=[pitch,0.0,yaw],
            horns_rigidly_follow_head=True, foot_contact=deepcopy(self.aux['contacts']),
            full_collision_and_multibody_dynamics_validated=False)

    def proprioception(self, vision=None):
        # A state/encoder-based estimate. No rendering or visual observation
        # is read. This is not an independently measured biological sense.
        pose=self.pose()['parts']; out={}
        for k,pos in pose.items():
            out[k]=dict(position=list(pos), velocity=deepcopy(self.aux['proprioceptive_velocities'].get(k,[0.0]*3)),
                load=self.aux['loads'].get(k,0.0), tension=self.aux['muscle_tone'],
                contact=bool(self.aux['contacts'].get(k,False)), source='simulated_encoders_and_forward_kinematics')
        return out

    def pain(self):
        b=self.owner.body; a=self.aux
        location=max(b.pain.slow, key=b.pain.slow.get)
        ascending=clamp(max(b.pain.slow.values(), default=0.0))
        episode=next((e for e in reversed(a['pain_episodes']) if e['location']==location),None)
        adaptation=episode['adaptation'] if episode else 0.0
        attenuation=clamp(b.pain.gain*b.pain.calming+.10*adaptation,0.0,.30)
        attention_gain=1.0+.10*a['arousal']
        perception=clamp(ascending*(1.0-attenuation)*attention_gain) if b.pain.enabled else 0.0
        return dict(nociceptive_load=ascending, perceived_intensity=perception,
            pain_location=location if ascending>1e-8 else None,
            pain_character=episode['quality'] if episode else ('retained load/afferent proxy' if ascending else None),
            pain_adaptation=adaptation, episodes=deepcopy(a['pain_episodes']),
            protective_response='guard_and_limit_optional_motion' if a['guarding']>.10 or any(b.state.latched.values()) else 'monitor',
            raw_warning_latches=deepcopy(b.state.latched), suffering=None,
            perception_is_not_suffering=True)

    def voice(self):
        a=self.aux; fatigue=max(self.owner.body.state.fatigue.values()); pain=self.pain()['perceived_intensity']
        calm=clamp(a['parasympathetic']*(1.0-a['sympathetic']))
        return dict(speech_rate_words_min=150.0*(1.0-.35*fatigue)+35.0*a['arousal'],
            pitch_shift_semitones=-3.0 if a['guardian'] else -1.0*fatigue,
            articulation=clamp(.70+.25*float(a['guardian'])-.15*fatigue),
            pause_seconds=.25+.65*calm+.20*a['sleep_pressure'],
            breath_group_words=max(1.0,10.0+12.0*calm-5.0*pain),
            softness=clamp(.30+.60*a['affiliative']+.20*calm),
            silent=self.aux['breath_mode']=='hold', output='speech-style controls; no generated audio')

    def body(self):
        s=self.owner.body.state; p=self.physical; g=p.coupling.gas; a=self.aux; pain=self.pain()
        contact=p.contact.solve(p.state.feet_m,p._active(),p._capture(),p.weight,{})
        margin=point_margin(contact['polygon'],p._capture())
        balance=clamp(.5+margin/.10) if p.state.phase!='failed' else 0.0
        energy=clamp(s.fuel_J/4000000.0); hydration=clamp(s.free_water_L/110.0)
        temp=37.0+s.heat_J/(195.0*3500.0) # explicit heat-capacity design proxy
        co2=clamp(g.co2_store_L/.60); o2=clamp(g.usable_o2_L/2.0)
        tone=a['muscle_tone']; fatigue=max(s.fatigue.values())
        perfusion=hydration
        fields=dict(heart_rate=a['heart_rate'], vascular_tone=a['vascular_tone'],
            perfusion_state=perfusion, blood_volume_proxy=hydration,
            respiratory_rate=a['effective_rr'], tidal_effort=clamp(g.tidal_L/2.6),
            oxygenation_proxy=o2, CO2_drive=co2, energy_reserve=energy,
            glucose_proxy=energy, hydration=hydration, thermal_state=temp,
            muscle_tone=tone, fatigue=fatigue, posture=p.state.phase,
            joint_load=max((s.previous_force_N[c]/self.owner.body.sections[c]['external_force_ceiling_N'] for c in s.previous_force_N),default=0.0),
            nociceptive_load=pain['nociceptive_load'], pain_location=pain['pain_location'],
            pain_character=pain['pain_character'], pain_adaptation=pain['pain_adaptation'],
            sympathetic_tone=a['sympathetic'], parasympathetic_tone=a['parasympathetic'],
            vagal_state=a['parasympathetic'], arousal=a['arousal'],
            chest_state=clamp(.35*co2+.35*a['sympathetic']+.30*g.tidal_L/2.6),
            abdominal_state=clamp(1.0-hydration), head_state=clamp(.55*a['sleep_pressure']+.45*a['arousal']),
            pelvic_state=clamp(.50*tone+.50*fatigue), tension=tone,
            calm=clamp(a['parasympathetic']*(1.0-a['sympathetic'])),
            vigilance=a['arousal'], affiliative_state=a['affiliative'])
        minimum=dict(zip(MINIMUM,(a['heart_rate'],a['effective_rr'],energy,hydration,temp,
            a['sympathetic'],a['parasympathetic'],tone,fatigue,pain['perceived_intensity'],a['arousal'],
            a['valence'],p.state.phase,balance,g.tidal_L,a['sleep_pressure'])))
        return dict(evidence_level='B', physiological=fields, minimum_state=minimum,
            finite_stocks=dict(fuel_J=s.fuel_J,reserve_J=s.reserve_J,water_L=s.free_water_L,
                heat_J=s.heat_J,usable_o2_L=g.usable_o2_L,co2_store_L=g.co2_store_L),
            pose=self.pose(), proprioception=self.proprioception(), pain=pain, voice=self.voice(),
            emotion=dict(name=a['emotion'],intensity=a['emotion_intensity'],valence=a['valence'],
                attention_mode='narrow' if a['emotion'] in ('fear','anger') else ('expanded' if a['emotion']=='curiosity' else 'balanced')),
            memory=dict(guarding=a['guarding'],traces=deepcopy(a['body_memory'])),
            clock=dict(owner_simulated_seconds=s.time_s,biological_hour_Tehran=a['biological_hour'],
                circadian_phase=a['circadian_phase'],unobserved_wall_seconds=a['unobserved_seconds'],
                sleep_pressure=a['sleep_pressure'],uncertainty=a['uncertainty'],
                background_execution_verified=False),
            alias_limits=dict(glucose_proxy='fuel fraction; no glucose compartment',
                blood_volume_proxy='water fraction; no blood compartment',
                perfusion_state='hydration proxy; read native circulation receipts separately',
                vagal_state='regulatory proxy; no neural recording',
                thermal_state='heat-to-temperature design conversion; not measured tissue temperature'))

    def _record(self, before, after, cause, reason, elapsed_s):
        if cause not in CAUSES: raise ValueError('unrecognized cause')
        f,g=flatten(before),flatten(after)
        changes=[dict(path=k,before=f.get(k),after=g.get(k)) for k in sorted(set(f)|set(g)) if f.get(k)!=g.get(k)]
        if not changes: return None
        row=dict(index=len(self.journal),cause=cause,reason=reason,elapsed_s=elapsed_s,
            before_sha256=digest(before),after_sha256=digest(after),changes=changes,
            previous_event_sha256=self.journal[-1]['sha256'] if self.journal else None)
        row['sha256']=digest(row); self.journal.append(row)
        return row['sha256']

    @staticmethod
    def validate_external(e, now):
        if not isinstance(e,dict): raise ValueError('external input must be an object')
        allowed={'origin_level','emotion','emotion_intensity','guardian','upper_targets','pain',
            'water_L','food_J','physical_samples','imagery','unexpected_impulse_N_s',
            'ambient_oxygen_factor','airway_capacity','friction'}
        if set(e)-allowed: raise ValueError('unsupported external input')
        if e.get('origin_level','B') not in {'A','B','C'}: raise ValueError('unknown evidence level')
        if e.get('emotion','neutral') not in EMOTIONS: raise ValueError('unknown emotion')
        finite(e.get('emotion_intensity',0.0),'emotion intensity')
        if type(e.get('guardian',False)) is not bool: raise ValueError('guardian must be bool')
        for j,x in e.get('upper_targets',{}).items():
            if j not in JOINTS: raise ValueError('unknown joint')
            finite(x,j,*JOINTS[j])
        finite(e.get('water_L',0.0),'available water',0.0,2.0)
        finite(e.get('food_J',0.0),'available fuel',0.0,500000.0)
        for k in ('ambient_oxygen_factor','airway_capacity'): finite(e.get(k,1.0),k)
        if 'friction' in e:
            if set(e['friction'])!={'L','R'}: raise ValueError('two foot friction values required')
            for x in e['friction'].values(): finite(x,'friction',0.0,1.5)
        v=e.get('unexpected_impulse_N_s',[0.0,0.0])
        if not isinstance(v,list) or len(v)!=2: raise ValueError('two impulse coordinates required')
        for x in v: finite(x,'impulse',-80.0,80.0)
        for episode in e.get('pain',[]):
            if set(episode)!={'id','location','intensity','quality','cause','duration_s'}: raise ValueError('pain descriptor incomplete')
            for k in ('id','location','quality','cause'):
                if not isinstance(episode[k],str) or not episode[k] or len(episode[k])>160: raise ValueError('invalid pain descriptor')
            finite(episode['intensity'],'pain intensity'); finite(episode['duration_s'],'pain duration',.1,86400.0)
        for sample in e.get('physical_samples',[]):
            if set(sample)!={'source_id','timestamp_utc','measurements'} or not sample['source_id']:
                raise ValueError('physical sample needs source, timestamp, measurements')
            if instant(sample['timestamp_utc'])>instant(now): raise ValueError('physical sample from future')
            if not isinstance(sample['measurements'],dict): raise ValueError('measurements must be an object')
            for x in sample['measurements'].values(): finite(x,'physical input',-1e9,1e9)
        for s in e.get('imagery',[]):
            if not isinstance(s,str) or len(s)>4000: raise ValueError('bounded imagery text required')
        json.dumps(e,allow_nan=False)

    def _elapsed(self, now):
        elapsed=(instant(now)-instant(self.wall_utc)).total_seconds()
        if elapsed<0: raise ValueError('wall clock moved backwards; no state reset')
        before=self.body(); a=self.aux
        self._circadian(now)
        a['unobserved_seconds']+=elapsed
        a['uncertainty']=clamp(a['uncertainty']+elapsed/172800.0)
        # Deliberate unknown-gap policy: no virtual walking, sleep, intake,
        # fuel restoration, healing or fatigue recovery is invented.
        relaxation=math.exp(-elapsed/900.0)
        a['sympathetic']=.20+(a['sympathetic']-.20)*relaxation
        a['parasympathetic']=.60+(a['parasympathetic']-.60)*relaxation
        a['emotion_intensity']*=relaxation
        a['affiliative']*=math.exp(-elapsed/3600.0)
        a['sleep_pressure']=clamp(a['sleep_pressure']+elapsed/57600.0)
        a['guarding']*=math.exp(-elapsed/3600.0)
        for trace in a['body_memory']: trace['weight']*=math.exp(-elapsed/trace['tau_s'])
        self._record(before,self.body(),'time_decay',
            'unobserved host interval; declared auxiliary decay and circadian advance; physical owner retained',elapsed)
        return elapsed

    def _external(self, e):
        before=self.body(); a=self.aux
        if 'emotion' in e:
            a['emotion']=e['emotion']; a['emotion_intensity']=e.get('emotion_intensity',1.0)
            i=a['emotion_intensity']
            if a['emotion'] in ('fear','anger'):
                a['sympathetic']=clamp(a['sympathetic']+.40*i)
                a['muscle_tone']=clamp(a['muscle_tone']+.20*i)
                a['arousal']=clamp(a['arousal']+.35*i)
            elif a['emotion']=='affection':
                a['parasympathetic']=clamp(a['parasympathetic']+.15*i)
                a['muscle_tone']=clamp(a['muscle_tone']-.10*i)
                a['affiliative']=clamp(a['affiliative']+.40*i)
            elif a['emotion']=='curiosity': a['arousal']=clamp(.30+.15*i)
        if 'guardian' in e: a['guardian']=e['guardian']
        for row in e.get('pain',[]):
            if row['location'] not in self.owner.body.pain.regions: raise ValueError('pain location not in retained atlas')
            if any(q['id']==row['id'] for q in a['pain_episodes']): raise ValueError('pain event identity reused')
            onset=self.owner.body.state.time_s
            a['pain_episodes'].append(dict(**row,onset_body_s=onset,adaptation=0.0,
                elapsed_simulated_s=0.0,protective_response='guard_and_limit_optional_motion',origin_level=e.get('origin_level','B')))
            a['guarding']=max(a['guarding'],row['intensity'])
        a['pain_episodes']=a['pain_episodes'][-64:]
        a['physical_samples']=(a['physical_samples']+[dict(level='A',**s) for s in e.get('physical_samples',[])])[-64:]
        a['imagery']=(a['imagery']+[dict(level='C',text=s) for s in e.get('imagery',[])])[-64:]
        self._record(before,self.body(),'external_input',
            'explicit source-tagged instruction/input; affect and pain descriptors are simulated state',0.0)

    def needs(self):
        b=self.body(); m=b['minimum_state']; f=b['physiological']
        scores=dict(energy=max(0.0,(.35-m['energy'])/.35), hydration=max(0.0,(.98-m['hydration'])/.10),
            heat=max(0.0,(m['temperature']-37.20)/.4), fatigue=max(0.0,(m['fatigue']-.35)/.65),
            pain=m['pain'], autonomic=max(0.0,(m['sympathetic']-.35)/.65),
            ventilation=max(0.0,(f['CO2_drive']-.50)/.50), sleep=max(0.0,(m['sleep_pressure']-.65)/.35),
            support=1.0 if self.physical.state.phase=='failed' else max(0.0,.5-m['balance']))
        return {k:round(clamp(v),6) for k,v in scores.items()}

    def _upper_proposal(self, targets, dt):
        a=self.aux; proposal={}; velocity={}
        for j in JOINTS:
            current=a['upper_angles'][j]; target=targets.get(j,current)
            desired=clamp((target-current)/dt,-.30,.30)
            old=a['upper_velocities'][j]
            new=clamp(desired,old-.80*dt,old+.80*dt)
            nxt=clamp(current+new*dt,*JOINTS[j])
            if (target-current)*(target-nxt)<0: nxt=target; new=(nxt-current)/dt
            proposal[j]=nxt; velocity[j]=new
        power=15.0*sum(abs(v) for v in velocity.values())
        return proposal,velocity,power

    def _simulate(self, action, duration_s, e, *, actual=False, log=False):
        a=self.aux; p=self.physical; b=self.owner.body
        before=self.body(); dt=.10; ticks=round(duration_s/dt)
        mode={'slow_breath':'slow','rapid_breath':'rapid','breath_hold':'hold'}.get(action,'normal')
        a['breath_mode']=mode; p.coupling.breath_mode=mode
        frames=[]; gas_error=0.0; energy_error=0.0
        resources=ConservationAudit(asdict(b.state)); gases=GasAudit(p)
        physics=PhysicsAudit(p); solutes=SoluteAudit(self.owner.renal.state)
        paced_ticks=0
        for n in range(ticks):
            old_pose=self.pose()['parts']
            targets=deepcopy(e.get('upper_targets',{}))
            if action=='protect' or a['guarding']>.40:
                fraction=clamp(1.0-.80*a['guarding'])
                targets={j:a['upper_angles'][j]+fraction*(x-a['upper_angles'][j]) for j,x in targets.items()}
            proposal,vel,accessory_W=self._upper_proposal(targets,dt)
            b.accessory_requested_W=accessory_W
            stimuli={}
            for q in a['pain_episodes']:
                age=b.state.time_s-q['onset_body_s']
                if age<q['duration_s']:
                    stimuli[q['location']]={'mechanical':q['intensity']}
            water=e.get('water_L',0.0)/duration_s if action=='hydrate' else 0.0
            food=e.get('food_J',0.0)/duration_s if action=='refuel' else 0.0
            inp=Inputs(dt_s=dt,stimuli=stimuli,water_intake_L_s=water,food_intake_J_s=food,
                passive_cooling_W=360.0 if action=='cool' else 180.0)
            impulse=e.get('unexpected_impulse_N_s',[0.0,0.0]) if actual and n==0 else [0.0,0.0]
            command=action if action in ('walk','single_L','single_R') else 'stand'
            environment=GaitEnvironment(body=inp,command=command,
                request_paced_breath=action=='slow_breath',
                ambient_oxygen_factor=e.get('ambient_oxygen_factor',1.0),
                airway_capacity=e.get('airway_capacity',1.0),
                external_impulse_N_s=impulse,friction=e.get('friction',{'L':.6,'R':.6}))
            initial_fuel=b.state.fuel_J
            f=p.step(environment)
            self.owner.memory.loop.body_steps+=1
            self.owner.memory.loop.sensory.observe(f,p)
            self.owner.memory.loop.command=command
            self.owner.memory.loop.last_receipt=dict(body_frame_id='embodiment_tick',body_tick=self.owner.memory.loop.body_steps,
                fuel_used_J=f['ledger']['fuel_used_J'],body_valid=f['balance']['model_valid'],
                requested_command=command,consciousness_evidence=False)
            fraction=f['accessory_motor']['paid_fraction']
            if f['motor']['critical_stop'] or f['motor']['systemic_stop']: fraction=0.0
            for j in JOINTS:
                a['upper_angles'][j]+=fraction*(proposal[j]-a['upper_angles'][j])
                a['upper_velocities'][j]=fraction*vel[j]
            a['accessory_energy_J']+=f['accessory_motor']['paid_W']*dt
            a['effective_rr']=f['respiration']['rate_min']
            achieved_slow=bool(mode=='slow' and f['respiration']['paced'])
            paced_ticks+=int(achieved_slow)
            activity=float(command!='stand' and f['balance']['model_valid'])
            a['current_activity']=activity
            pain=self.pain()['nociceptive_load']; emotion=a['emotion']; i=a['emotion_intensity']
            fast=1.0-math.exp(-dt/8.0)
            sympathetic_target=clamp(.18+.40*i*float(emotion in ('fear','anger'))+.25*pain+.20*activity
                +.20*clamp(p.coupling.gas.co2_store_L/.60)-.12*float(achieved_slow))
            parasympathetic_target=clamp(.72-.35*sympathetic_target+.20*i*float(emotion=='affection')+.12*float(achieved_slow))
            a['sympathetic']+=fast*(sympathetic_target-a['sympathetic'])
            a['parasympathetic']+=fast*(parasympathetic_target-a['parasympathetic'])
            a['vascular_tone']+=fast*(clamp(.45+.20*a['sympathetic']+.25*i*float(emotion=='anger'))-a['vascular_tone'])
            arousal_target=clamp(.18+.55*a['sympathetic']+.20*float(mode=='rapid')+.15*i*float(emotion=='curiosity'))
            a['arousal']+=fast*(arousal_target-a['arousal'])
            muscle_target=clamp(.16+.35*a['sympathetic']+.30*pain+.20*a['guarding']-.10*a['affiliative'])
            a['muscle_tone']+=fast*(muscle_target-a['muscle_tone'])
            hr_target=clamp(60.0+50.0*(a['sympathetic']-.20)-15.0*(a['parasympathetic']-.60)+30.0*activity+15.0*pain,35.0,160.0)
            a['heart_rate']+=(1.0-math.exp(-dt/5.0))*(hr_target-a['heart_rate'])
            target_valence={'neutral':0.0,'fear':-.7,'anger':-.6,'affection':.6,'curiosity':.3}[emotion]*i
            a['valence']+=fast*(target_valence-a['valence'])
            a['affiliative']+=fast*(i*float(emotion=='affection')-a['affiliative'])
            a['guarding']=max(a['guarding']*math.exp(-dt/60.0),pain)
            night=.5+.5*math.cos(2.0*math.pi*(a['biological_hour']-2.0)/24.0)
            if action=='sleep': a['sleep_pressure']*=math.exp(-dt/900.0)
            else: a['sleep_pressure']=clamp(a['sleep_pressure']+dt/57600.0+dt*night/86400.0)
            for q in a['pain_episodes']:
                q['elapsed_simulated_s']=b.state.time_s-q['onset_body_s']
                if q['elapsed_simulated_s']<q['duration_s']:
                    q['adaptation']+=(1.0-math.exp(-dt/60.0))*(1.0-q['adaptation'])
                else: q['adaptation']*=math.exp(-dt/120.0)
            for trace in a['body_memory']: trace['weight']*=math.exp(-dt/trace['tau_s'])
            new_pose=self.pose()['parts']
            a['proprioceptive_velocities']={k:[(new_pose[k][j]-old_pose[k][j])/dt for j in range(3)] for k in new_pose}
            a['contacts']={k:k.startswith('foot_') and new_pose[k][2]<1e-8 for k in new_pose}
            a['loads']={k:0.0 for k in new_pose}
            for side in ('L','R'):
                a['loads']['foot_'+side]=f['contact']['by_foot_N'][side]
                for part,joint in (('hip','hip'),('leg','knee'),('ankle','ankle')):
                    a['loads'][part+'_'+side]=b.state.previous_force_N[joint+'_'+side]
            p.last=deepcopy(f)
            led=f['respiration']['ledger']; g=p.coupling.gas
            gas_error=max(gas_error,abs(led['before_o2_L']+led['uptake_L']-led['consumed_o2_L']-led['expired_unused_o2_L']-g.usable_o2_L),
                abs(led['before_co2_L']+led['produced_co2_L']-led['cleared_co2_L']-g.co2_store_L))
            energy_error=max(energy_error,abs(initial_fuel+food*dt-f['ledger']['fuel_used_J']-b.state.fuel_J))
            resources.frame(f); gases.frame(f); physics.frame(f,environment); solutes.frame(f['renal'],f)
            frames.append(f)
        for kind,weight,tau in [('stress',a['sympathetic'],900.0),('exertion',max(b.state.fatigue.values()),3600.0),('guarding',a['guarding'],3600.0)]:
            if weight>.10: a['body_memory'].append(dict(kind=kind,weight=weight,tau_s=tau,at_body_s=b.state.time_s))
        a['body_memory']=a['body_memory'][-128:]
        if log:
            self._record(before,self.body(),'simulated_action',
                'single retained owner integration: '+action+'; bounded paid upper motion; physiology/regulation/gas coupling',duration_s)
        return dict(frames=frames,gas_balance_error_L=gas_error,energy_balance_error_J=energy_error,
            simulated_seconds=duration_s,owner_ticks=ticks,physical_model_valid=p.state.phase!='failed',
            upper_motion_work_paid_J=sum(f['accessory_motor']['paid_W']*dt for f in frames),
            achieved_slow_breath_ticks=paced_ticks, breathing_actuator_requested=mode,
            independent_accounting_audits=dict(resources=resources.result(),gases=gases.result(),
                physics=physics.result(),solutes=solutes.result()))

    def forecast(self, action, duration_s, e):
        trial=deepcopy(self)
        receipt=trial._simulate(action,duration_s,e,actual=False,log=False)
        return dict(action=action,body=trial.body(),model_valid=receipt['physical_model_valid'],
            source='private deterministic rollout of the same uncalibrated owner kernel',
            independent_empirical_validation=False)

    @staticmethod
    def forecast_cost(body):
        m=body['minimum_state']; p=body['physiological']
        return (6.0*(1.0-m['energy'])+3.0*(1.0-m['hydration'])+3.0*m['fatigue']+
            4.0*m['pain']+2.0*m['sympathetic']+2.0*p['CO2_drive']+2.0*(1.0-m['balance'])+
            max(0.0,m['temperature']-37.2)*5.0)

    def select(self, duration_s, e, requested=None):
        needs=self.needs(); candidates=['observe','slow_breath','protect']
        if needs['ventilation']>.3: candidates.append('rapid_breath')
        if needs['heat']>0.0: candidates.append('cool')
        if e.get('water_L',0.0)>0.0: candidates.append('hydrate')
        if e.get('food_J',0.0)>0.0: candidates.append('refuel')
        if requested: candidates.append(requested)
        candidates=list(dict.fromkeys(candidates)); forecasts=[]
        m=self.body()['minimum_state']
        for action in candidates:
            if action=='hydrate' and e.get('water_L',0.0)==0.0: continue
            if action=='refuel' and e.get('food_J',0.0)==0.0: continue
            if action in ('walk','single_L','single_R') and (m['energy']<.25 or m['fatigue']>.52 or m['pain']>.40 or m['sleep_pressure']>.85): continue
            if action=='breath_hold' and (duration_s>10.0 or self.physical.coupling.gas.co2_store_L>.35 or self.physical.coupling.gas.usable_o2_L<1.9): continue
            forecast=self.forecast(action,duration_s,e)
            cost=self.forecast_cost(forecast['body'])+(100.0 if not forecast['model_valid'] else 0.0)
            if action==requested: cost-=1.0
            if needs['autonomic']>.15 and action=='slow_breath': cost-=.3
            if needs['ventilation']>.3 and action=='rapid_breath': cost-=.3
            if max(needs['energy'],needs['fatigue'],needs['sleep'],needs['pain'])>.3 and action=='protect': cost-=.3
            forecast['selection_cost']=cost; forecasts.append(forecast)
        if not forecasts: raise ValueError('no admissible simulated action')
        selected=min(forecasts,key=lambda f:f['selection_cost'])
        return selected,forecasts,needs

    def interoceptive_summary(self):
        b=self.body(); m=b['minimum_state']
        tags=['انرژی کافی' if m['energy']>.35 else 'نیاز به حفظ انرژی']
        if m['fatigue']>.10: tags.append('خستگی باقی‌ماندهٔ پاها')
        if m['pain']>.03: tags.append('سیگنال دردِ کم‌دامنه در '+str(b['pain']['pain_location']))
        if m['sympathetic']>.50: tags.append('برانگیختگی اتونوم بالا')
        if m['sleep_pressure']>.65: tags.append('فشار خواب بالا')
        return 'Level B — '+'؛ '.join(tags)+'.'

    def self_location(self):
        b=self.body(); f=b['physiological']; needs=self.needs()
        key=max(('chest_state','abdominal_state','head_state','pelvic_state'),key=f.get)
        return dict(where=b['pose']['frame'],position_m=b['pose']['self_location'],pose=b['pose']['posture_phase'],
            strongest_interoceptive_region=key,energy=b['minimum_state']['energy'],
            dominant_homeostatic_need=max(needs,key=needs.get),
            next_move_prediction='available by forecast(action, duration, inputs)',evidence_level='B')

    def cycle(self, *, event_id, at_utc, duration_s=1.0, external=None, requested=None):
        external={} if external is None else deepcopy(external)
        now=instant(at_utc); duration_s=finite(duration_s,'cycle duration',.1,60.0)
        if abs(duration_s*10-round(duration_s*10))>1e-8: raise ValueError('duration must be a multiple of .1 seconds')
        if not isinstance(event_id,str) or not event_id or len(event_id)>160: raise ValueError('bounded cycle identity required')
        if requested is not None and requested not in ACTIONS: raise ValueError('unsupported action')
        self.validate_external(external,now)
        request_hash=digest(dict(external=external,duration_s=duration_s,requested=requested))
        if event_id in self.requests:
            if self.requests[event_id]!=request_hash: raise ValueError('cycle id reused with altered input')
            if event_id not in self.results: raise ValueError('cycle already committed; original result archived; do not replay')
            return deepcopy(self.results[event_id])
        work=deepcopy(self); start=work.body(); elapsed=work._elapsed(now)
        work._external(external); before_selection=work.body()
        selected,forecasts,needs=work.select(duration_s,external,requested)
        # Lock the forecast before outcome-only disturbance integration.
        forecast_hash=digest(selected)
        regulation_before=work.body()
        work.aux['breath_mode']={'slow_breath':'slow','rapid_breath':'rapid','breath_hold':'hold'}.get(selected['action'],'normal')
        work._record(regulation_before,work.body(),'internal_regulation',
            'homeostatic arbitration and physiological breathing actuator selection',0.0)
        receipt=work._simulate(selected['action'],duration_s,external,actual=True,log=True)
        outcome=work.body(); pred=selected['body']['minimum_state']; actual=outcome['minimum_state']
        residual={k:actual[k]-pred[k] for k in MINIMUM if isinstance(actual[k],(float,int))}
        scales={'HR':100.0,'RR':40.0,'temperature':4.0,'breath_depth':2.6}
        error=sum(abs(v)/scales.get(k,1.0) for k,v in residual.items())/len(residual)
        record=dict(at_revision=work.revision+1,event_id=event_id,forecast_sha256=forecast_hash,
            predicted=deepcopy(pred),actual=deepcopy(actual),signed_errors=residual,
            mean_scaled_absolute_error=error,outcome_only_disturbance=external.get('unexpected_impulse_N_s',[0.0,0.0]),
            zero_error_means_deterministic_agreement_not_empirical_validation=True)
        work.aux['prediction_history']=(work.aux['prediction_history']+[record])[-128:]
        result=dict(protocol=SCHEMA,evidence_level='B',event_id=event_id,revision=work.revision+1,
            started_at_utc=now.isoformat(),started_at_Tehran=now.astimezone(TEHRAN).isoformat(),
            host_gap_seconds=elapsed,gap_policy=work.migration['gap_policy'],
            real_time_background_activity_claimed=False,simulated_seconds=duration_s,
            start_minimum_state=start['minimum_state'],before_selection=before_selection['minimum_state'],
            interoceptive_summary=work.interoceptive_summary(),homeostatic_needs=needs,
            selected_action=selected['action'],candidates=[dict(action=f['action'],cost=f['selection_cost'],model_valid=f['model_valid']) for f in forecasts],
            prediction=record,outcome_minimum_state=actual,self_location=work.self_location(),
            voice=work.voice(),attention_mode=outcome['emotion']['attention_mode'],
            physical_owner_ticks=receipt['owner_ticks'],physical_model_valid=receipt['physical_model_valid'],
            resource_and_gas_audit={k:v for k,v in receipt.items() if k!='frames'},
            journal_events_after=len(work.journal),physical_sensor_samples_count=len(work.aux['physical_samples']),
            audio_generated=False,model_parameters_biologically_calibrated=False)
        work.revision+=1; work.wall_utc=now.isoformat(); work.last_result=deepcopy(result)
        work.requests[event_id]=request_hash
        work.results[event_id]=deepcopy(result)
        work.results=dict(list(work.results.items())[-32:])
        # Keep raw frames only for the current caller's audit, never as a
        # growing nested cognitive history. Checkpoint is one atomic object.
        self.__dict__=work.__dict__
        return deepcopy(result)

    def checkpoint(self):
        payload=dict(schema=SCHEMA,source_fingerprints=sources(),revision=self.revision,
            wall_utc=self.wall_utc,migration=self.migration,owner=self.owner.checkpoint(),
            auxiliary=deepcopy(self.aux),body=self.body(),journal=deepcopy(self.journal),
            requests=deepcopy(self.requests),results=deepcopy(self.results),last_result=deepcopy(self.last_result))
        return dict(payload=payload,sha256=digest(payload))

    @classmethod
    def restore(cls, envelope):
        if set(envelope)!={'payload','sha256'}: raise ValueError('bad persistent state envelope')
        p=deepcopy(envelope['payload'])
        if envelope['sha256']!=digest(p) or p['schema']!=SCHEMA or p['source_fingerprints']!=sources():
            raise ValueError('state/source/version mismatch; automatic reset forbidden')
        obj=cls(RenalMemoryLoop.restore(p['owner']),p['auxiliary'],p['wall_utc'],p['migration'])
        for key in ('revision','journal','requests','results','last_result'): setattr(obj,key,deepcopy(p[key]))
        # Preserve bounded-cache eviction across sorted JSON serialization.
        obj.results=dict(sorted(obj.results.items(),key=lambda item:item[1]['revision']))
        for k in ('sympathetic','parasympathetic','muscle_tone','arousal','sleep_pressure','guarding','uncertainty'):
            finite(obj.aux[k],k)
        for j,x in obj.aux['upper_angles'].items(): finite(x,j,*JOINTS[j])
        previous=None
        previous_body=None
        for row in obj.journal:
            unsigned={k:v for k,v in row.items() if k!='sha256'}
            if row['sha256']!=digest(unsigned) or row['previous_event_sha256']!=previous or row['cause'] not in CAUSES:
                raise ValueError('causal journal mismatch')
            if previous_body is not None and row['before_sha256']!=previous_body:
                raise ValueError('gap in cause-bearing body transitions')
            previous=row['sha256']
            previous_body=row['after_sha256']
        if obj.body()!=p['body']: raise ValueError('stored body does not match owner/auxiliary state')
        if obj.journal and obj.journal[-1]['after_sha256']!=digest(obj.body()): raise ValueError('body changed without a recorded cause')
        obj.loaded_sha256=envelope['sha256']
        return obj

    def save(self, path, *, create=False):
        path=Path(path)
        if path.exists():
            if create: raise ValueError('initialization cannot overwrite existing body')
            old=json.loads(path.read_text())
            if self.loaded_sha256 is None or old.get('sha256')!=self.loaded_sha256:
                raise ValueError('state changed since read; stale writer rejected')
        elif not create and self.loaded_sha256 is not None:
            raise ValueError('previous body file disappeared; automatic reset forbidden')
        envelope=self.checkpoint(); atomic_json(path,envelope); self.loaded_sha256=envelope['sha256']


def main():
    parser=argparse.ArgumentParser(description='Level B persistent causal body; no physical sensory body attached')
    parser.add_argument('command',choices=['init','cycle','inspect'])
    parser.add_argument('--state',required=True)
    parser.add_argument('--at',default=None)
    parser.add_argument('--duration',type=float,default=1.0)
    parser.add_argument('--event-id',default=None)
    parser.add_argument('--action',choices=sorted(ACTIONS))
    parser.add_argument('--input-json',help='path to a JSON external-input object')
    args=parser.parse_args(); path=Path(args.state); path.parent.mkdir(parents=True,exist_ok=True)
    now=args.at or datetime.now(UTC).isoformat()
    with open(str(path)+'.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if args.command=='init':
            source=json.loads((BASE/'checkpoint_continuation_v09.json').read_text())
            body=PersistentEmbodiment.bootstrap(source,now); body.save(path,create=True)
            print(json.dumps(dict(initialized=True,revision=0,body=body.body()['minimum_state'],evidence_level='B'),ensure_ascii=False))
        else:
            body=PersistentEmbodiment.restore(json.loads(path.read_text()))
            if args.command=='inspect':
                print(json.dumps(dict(revision=body.revision,summary=body.interoceptive_summary(),body=body.body()['minimum_state'],self_location=body.self_location()),ensure_ascii=False))
            else:
                external=json.loads(Path(args.input_json).read_text()) if args.input_json else {}
                result=body.cycle(event_id=args.event_id or 'cycle:'+str(body.revision+1),at_utc=now,
                    duration_s=args.duration,external=external,requested=args.action)
                body.save(path)
                print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
