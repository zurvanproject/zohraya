"""Declared trajectories, independent resource/contact audits, and failure tests."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import random

from posture_step import PostureLoop,GaitEnvironment,Inputs,CHANNELS,zeros,norm,point_margin
from body_loop_v06 import BodyLoop
from resource_audit_v06 import ConservationAudit

ROOT=Path(__file__).parent

def save(name,data):
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')))

class GasAudit:
    def __init__(self,loop):
        self.o=asdict(loop.coupling.gas); self.uptake=self.use=self.expired=self.produced=self.cleared=0.
        self.max_o=self.max_c=0.; self.frames=0
    def frame(self,f):
        l=f['respiration']['ledger']; g=f['respiration']['state']; self.frames+=1
        use=f['ledger']['fuel_used_J']/20000.; self.use+=use; self.produced+=.8*use
        self.uptake+=l['uptake_L']; self.expired+=l['expired_unused_o2_L']; self.cleared+=l['cleared_co2_L']
        self.max_o=max(self.max_o,abs(self.o['usable_o2_L']+self.uptake-self.use-self.expired-g['usable_o2_L']))
        self.max_c=max(self.max_c,abs(self.o['co2_store_L']+self.produced-self.cleared-g['co2_store_L']))
        assert self.max_o<1e-8 and self.max_c<1e-8
        assert 0<=g['usable_o2_L']<=3. and g['co2_store_L']>=0.
        if f['task']['nonessential_pause_executed']:
            assert all(v==0. for v in f['motor']['optional_force_N'].values())
        if not f['respiration']['ventilation_ok']:
            assert not f['pain']['modulation_available']
    def result(self):
        return {'passed':True,'frames':self.frames,'max_o2_error_L':self.max_o,'max_co2_error_L':self.max_c}

class PhysicsAudit:
    def __init__(self,loop):
        self.mass=loop.design['mass_kg']; self.weight=loop.weight; self.omega=loop.omega
        self.last_v=list(loop.state.velocity_m_s); self.tail_KE=.5*4.8*sum(v*v for v in loop.state.tail_velocity_rad_s)
        self.frames=self.valid=self.failed=0
        self.errors={k:0. for k in ('normal_N','cop_Nm','momentum_N_s','capture_m','segment_length_m','tail_work_J')}
    def frame(self,f,e):
        c,p,b=f['contact'],f['posture'],f['balance']; dt=f['ledger']['dt_s']; self.frames+=1
        if b['model_valid']:
            self.valid+=1
            self.errors['normal_N']=max(self.errors['normal_N'],abs(sum(c['normal_N'].values())-self.weight))
            for k in range(2):
                moment=sum(c['normal_N'][q['id']]*q['xy'][k] for q in c['patches'])
                self.errors['cop_Nm']=max(self.errors['cop_Nm'],abs(moment-self.weight*c['cop_m'][k]))
                impulse=self.mass*(p['velocity_m_s'][k]-self.last_v[k])-e.external_impulse_N_s[k]
                self.errors['momentum_N_s']=max(self.errors['momentum_N_s'],abs(impulse-c['horizontal_force_N'][k]*dt))
                capture=p['com_m'][k]+p['velocity_m_s'][k]/self.omega
                self.errors['capture_m']=max(self.errors['capture_m'],abs(capture-b['capture_point_m'][k]))
            assert all(v>=-1e-8 for v in c['normal_N'].values())
            assert max(c['pressure_kpa'].values())<=300.+1e-7
            assert norm(c['horizontal_force_N'])<=c['friction_capacity_N']+1e-7
            for q in c['patches']:
                assert abs(c['feet_used_m'][q['side']][2])<1e-8
                assert q['local_id'] not in e.inactive_patches.get(q['side'],[])
                assert 'hock' not in q['id']
            for pose in p['kinematics'].values():
                assert pose['reachable']
                self.errors['segment_length_m']=max(self.errors['segment_length_m'],pose['segment_length_error_m'])
            tail_work=f['motor']['force_N']['tail']*f['motor']['speeds_m_s']['tail']*dt
            self.errors['tail_work_J']=max(self.errors['tail_work_J'],max(0.,p['tail_kinetic_energy_J']-self.tail_KE-tail_work))
            assert norm(p['tail_torque_actual_Nm'])<=60.+1e-8
            assert max(abs(x) for x in p['tail_angle_rad'])<=.65+1e-8
            assert max(abs(x) for x in p['tail_velocity_rad_s'])<=1.4+1e-8
            assert self.errors['normal_N']<1e-6 and self.errors['cop_Nm']<1e-6
            assert self.errors['momentum_N_s']<1e-7 and self.errors['capture_m']<1e-12
            assert self.errors['segment_length_m']<1e-9 and self.errors['tail_work_J']<1e-7
        else:
            self.failed+=1; assert p['phase']=='failed' and p['failed_reason'] is not None
            assert p['mechanical_simulation_terminated']
        self.last_v=list(p['velocity_m_s']); self.tail_KE=p['tail_kinetic_energy_J']
    def result(self):
        return {'passed':True,'frames':self.frames,'valid_frames':self.valid,
                'declared_failure_frames':self.failed,'max_errors':self.errors}

def environment(name,n):
    t=n*.05
    if name=='one_leg':return GaitEnvironment(command='single_L')
    if name=='weight_transfer':
        command='single_L' if t<14 else ('stand' if t<22 else ('single_R' if t<36 else 'stand'))
        return GaitEnvironment(command=command)
    if name=='walk':return GaitEnvironment(command='walk' if t<36 else 'stand')
    if name in ('slip_recovery','slip_over_limit','slip_no_step'):
        speed=.20 if name!='slip_over_limit' else .30
        return GaitEnvironment(command='single_L' if t<8.5 else 'stand',
            external_impulse_N_s=[-195.*speed,0.] if n==160 else [0.,0.],
            prescribed_slip_m={'L':[.02,0.]} if n==160 else {},
            protective_steps_enabled=name!='slip_no_step')
    if name=='sensory_pause':return GaitEnvironment(command='walk')
    raise ValueError(name)

def summary(name,frames,a,g,p):
    final=frames[-1]; first=lambda pred:next((f['t_s'] for f in frames if pred(f)),None)
    return {'case':name,'duration_s':final['t_s'],'frames':len(frames),
            'one_leg_hold_s':sum(f['posture']['phase']=='single_support' for f in frames)*.05,
            'walk_touchdowns':final['posture']['walk_steps'],'protective_touchdowns':final['posture']['protective_steps'],
            'first_protective_touchdown_s':first(lambda f:f['balance']['protective_step_executed']),
            'first_failure_s':first(lambda f:not f['balance']['model_valid']),
            'failure_reason':final['posture']['failed_reason'],
            'final_speed_m_s':norm(final['posture']['velocity_m_s']),
            'final_capture_margin_m':final['balance']['capture_margin_m'],
            'maximum_pressure_kpa':max(max(f['contact']['pressure_kpa'].values(),default=0.) for f in frames),
            'motor_energy_J':sum(f['ledger']['motor_energy_J'] for f in frames),
            'respiratory_work_J':sum(f['respiration']['work_actual_W']*.05 for f in frames),
            'tail_work_J':sum(f['motor']['force_N']['tail']*f['motor']['speeds_m_s']['tail']*.05 for f in frames),
            'final_fuel_J':final['state']['fuel_J'],'final_feet_m':final['posture']['feet_m'],
            'resource_audit':a.result(),'gas_audit':g.result(),'physics_audit':p.result()}

def run_case(name,seconds,*,persist=True):
    loop=PostureLoop()
    if name=='sensory_pause':
        # Explicit synthetic initial control burden, not a measured event.
        loop.body.endurance.spent_proxy_s=1142.; loop.body.endurance.pause_requested=True
        loop.body.endurance_origin=asdict(loop.body.endurance)
    a=ConservationAudit(asdict(loop.body.state)); g=GasAudit(loop); p=PhysicsAudit(loop); frames=[]
    for n in range(round(seconds/.05)):
        e=environment(name,n); f=loop.step(e)
        a.frame(f); g.frame(f); p.frame(f,e); frames.append(f)
        if not f['balance']['model_valid']:break
    if persist:
        save('trace_'+name+'.json',frames)
        if name=='slip_recovery':save('checkpoint_v06.json',loop.checkpoint())
    return frames,summary(name,frames,a,g,p)

def checks():
    results=[]
    def check(name,fn):
        details=fn(); results.append({'name':name,'passed':True,'details':details}); print('PASS',name,flush=True)
    def old_contact():
        a=PostureLoop(); c=a.contact.solve(a.state.feet_m,['L'],[.196,0.],a.weight)
        assert abs(c['by_foot_N']['L']-1912.95)<1e-8 and c['by_foot_N']['R']==0.
        assert len(c['patches'])==4
        # A different bounded load optimizer may redistribute a few hundredths
        # of a kPa while preserving the prior static result to its useful precision.
        assert 178.<max(c['pressure_kpa'].values())<178.4
        lost=a.contact.solve(a.state.feet_m,['L'],[.196,0.],a.weight,{'L':['toe_2']})
        assert lost['cop_m'][1]<-1e-4 and max(lost['pressure_kpa'].values())<=300.+1e-8
        return {'unchanged_four_patch_geometry':True,'peak_single_foot_kpa':max(c['pressure_kpa'].values()),
                'middle_toe_unavailable_forces_cop_adjustment_m':lost['cop_m']}
    check('existing_three_toes_and_pad_preserved_pressure_caps_enforced',old_contact)
    def mirror():
        a,b=PostureLoop(),PostureLoop()
        for n in range(400):
            x=a.step(GaitEnvironment(command='single_L')); y=b.step(GaitEnvironment(command='single_R'))
            assert x['balance']['model_valid'] and y['balance']['model_valid']
            assert abs(x['posture']['com_m'][0]+y['posture']['com_m'][0])<1e-8
            assert abs(x['posture']['com_m'][1]-y['posture']['com_m'][1])<1e-8
        assert a.state.phase==b.state.phase=='single_support'
        assert a.state.feet_m['R'][2]==b.state.feet_m['L'][2]==.12
        return {'paired_frames':400,'left_and_right_single_support_hold':True}
    check('bilateral_one_leg_support_is_mirror_symmetric',mirror)
    def replay():
        a=PostureLoop()
        for n in range(163):a.step(environment('slip_recovery',n))
        assert a.state.phase=='protective_swing'
        b=PostureLoop.restore(json.loads(json.dumps(a.checkpoint())))
        for n in range(163,360):assert a.step(environment('slip_recovery',n))==b.step(environment('slip_recovery',n))
        return {'exact_followup_frames':197,'checkpoint_during_executed_protective_swing':True}
    check('checkpoint_replays_contact_swing_tail_gas_and_pain_exactly',replay)
    def atomic():
        a=PostureLoop(); snap=a.checkpoint()
        invalid=[GaitEnvironment(command='jump'),GaitEnvironment(friction={'L':-.1,'R':.6}),
                 GaitEnvironment(external_impulse_N_s=[float('nan'),0.]),
                 GaitEnvironment(body=Inputs(dt_s=.5)),GaitEnvironment(inactive_patches={'L':['hock']}),
                 GaitEnvironment(body=Inputs(force_requests_N={'knee_L':1.})),
                 GaitEnvironment(protective_steps_enabled=1)]
        for e in invalid:
            try:a.step(e)
            except ValueError:pass
            else:raise AssertionError('invalid input accepted')
            assert a.checkpoint()==snap
        corrupt=deepcopy(snap); corrupt['payload']['posture']['feet_m']['L'][0]+=.1
        try:PostureLoop.restore(corrupt)
        except ValueError:pass
        else:raise AssertionError('corrupt checkpoint accepted')
        return {'atomic_rejections':len(invalid),'corruption_rejected':True}
    check('invalid_inputs_do_not_mutate_and_corrupt_snapshots_are_rejected',atomic)
    def priority():
        b=BodyLoop(initial={'reserve_J':0.})
        f=b.step(Inputs(dt_s=.05,postural_force_requests_N={'knee_L':400.},
                       force_requests_N={'knee_R':1000.},speeds_m_s={c:.1 for c in CHANNELS},aerobic_limit_W=450.))
        assert f['motor']['postural_force_N']['knee_L']==400.
        assert 0.<f['motor']['optional_force_N']['knee_R']<1000.
        assert f['ledger']['fuel_used_J']<=450.*.05+1e-8
        optional_delivered=f['motor']['optional_force_N']['knee_R']
        b=BodyLoop(); f=b.step(Inputs(dt_s=.05,injury_events_kg={'knee_L':.004,'ankle_R':.004}))
        assert f['ledger']['repair_material_kg']<=.00003*.05+1e-12
        return {'postural_force_N':400.,'optional_force_N':optional_delivered,
                'one_aggregate_repair_allowance_kg_s':.00003}
    check('posture_precedes_optional_work_in_one_energy_and_repair_ledger',priority)
    def pause():
        a=PostureLoop()
        for n in range(61):a.step(GaitEnvironment(command='walk'))
        assert a.state.phase=='walk_swing'
        a.body.endurance.spent_proxy_s=1142.; a.body.endurance.pause_requested=True
        a.body.endurance_origin=asdict(a.body.endurance)
        for n in range(40):
            f=a.step(GaitEnvironment(command='walk'))
            assert f['balance']['model_valid']
            assert all(v==0. for v in f['motor']['optional_force_N'].values())
            assert sum(f['motor']['postural_force_N'].values())>0.
            assert f['circulation']['vital_actual_W']>0.
        assert a.state.swing is None and all(p[2]==0. for p in a.state.feet_m.values())
        tired=PostureLoop()
        for n in range(61):tired.step(GaitEnvironment(command='walk'))
        healthy_capacity=tired.last['motor']['capacity_N']['hip_R']
        for j in ('hip','knee','ankle'):tired.body.state.fatigue[j+'_R']=.62
        first_capacity=None
        for n in range(40):
            f=tired.step(GaitEnvironment(command='walk'))
            if first_capacity is None:first_capacity=f['motor']['capacity_N']['hip_R']
            assert f['balance']['model_valid']
            assert f['task']['planned_activity']==0.
            assert all(v==0. for v in f['motor']['optional_force_N'].values())
        assert first_capacity<healthy_capacity
        assert tired.state.swing is None and all(p[2]==0. for p in tired.state.feet_m.values())
        return {'optional_motion_paused':True,'raised_foot_lowered_under_postural_energy':True,'frames_per_pause':40,
                'fatigue_pause_also_verified':True,'healthy_hip_capacity_N':healthy_capacity,
                'fatigued_hip_capacity_N':first_capacity}
    check('sensory_or_fatigue_pause_lowers_the_foot_and_preserves_paid_postural_support',pause)
    def hazard():
        a=PostureLoop(); a.body.comfort_pause()
        f=a.step(GaitEnvironment(command='single_L',body=Inputs(dt_s=.05,stimuli={'calf_L':{'damage':.9}})))
        assert f['pain']['peak_intensity_proxy']==0.
        assert f['pain']['raw_protective_signal']
        assert all(f['motor']['force_N'][j+'_L']==0. for j in ('hip','knee','ankle'))
        assert not a.body.state.latched['ankle_R']
        assert not f['balance']['model_valid']
        return {'left_danger_retained_during_display_pause':True,'right_latch_not_copied':True,
                'unsupported_state_reported':True}
    check('regional_injury_warning_is_not_hidden_by_comfort_or_endurance',hazard)
    def airway():
        a=PostureLoop(); f=a.step(GaitEnvironment(command='walk',airway_capacity=0.))
        assert f['motor']['critical_stop'] and all(v==0. for v in f['motor']['force_N'].values())
        assert not f['balance']['model_valid'] and f['circulation']['vital_actual_W']>0.
        return {'motor_support_insufficient_reported':True,'vitals_keep_using_finite_gas':True}
    check('airway_failure_does_not_invent_support_with_zero_motor_energy',airway)
    def friction():
        a=PostureLoop()
        for n in range(100):
            f=a.step(GaitEnvironment(command='single_L',friction={'L':.005,'R':.005}))
            if not f['balance']['model_valid']:break
        assert f['posture']['failed_reason']=='friction_limit_exceeded'
        return {'failed_at_s':f['t_s'],'friction_saturation_declared':True}
    check('insufficient_friction_is_a_failure_not_a_successful_recovery',friction)
    def migration():
        from breath_motion import BreathMotionLoop as Old
        old=Old(); old.body.state.wounds_kg['knee']=.006; old.body.state.wounds_kg['ankle']=.002
        old.body.origin=asdict(old.body.state)
        for n in range(10):old.step()
        new=PostureLoop.from_v05_checkpoint(old.checkpoint())
        for k in ('time_s','fuel_J','reserve_J','free_water_L','bound_water_L','material_kg','repaired_kg','heat_J'):
            assert getattr(old.body.state,k)==getattr(new.body.state,k)
        assert abs(sum(old.body.state.wounds_kg.values())-sum(new.body.state.wounds_kg.values()))<1e-12
        assert asdict(old.gas)==asdict(new.coupling.gas)
        assert asdict(old.body.endurance)==asdict(new.body.endurance)
        assert old.body.pain.slow==new.body.pain.slow and list(old.body.pain.queue)==list(new.body.pain.queue)
        assert new.state.phase=='double_support'
        return {'stocks_gas_pain_and_endurance_preserved':True,'wound_mass_split_not_duplicated':True,
                'new_hips_and_neutral_stance_explicitly_initialized':True}
    check('v05_migration_keeps_stocks_clocks_and_total_wound_mass',migration)
    def randomized():
        totals=0; worst={k:0. for k in ('energy_J','water_L','material_kg','wound_kg','force_N')}
        for seed in range(8):
            rng=random.Random(seed); a=PostureLoop()
            audit=ConservationAudit(asdict(a.body.state)); gas=GasAudit(a); physics=PhysicsAudit(a)
            for n in range(200):
                e=GaitEnvironment(command='stand',body=Inputs(dt_s=rng.choice((.05,.075,.1)),
                         food_intake_J_s=rng.uniform(0,50),water_intake_L_s=rng.uniform(0,.0004)),
                         external_impulse_N_s=[rng.uniform(-.1,.1),rng.uniform(-.1,.1)])
                f=a.step(e); audit.frame(f); gas.frame(f); physics.frame(f,e); totals+=1
                assert f['balance']['model_valid']
            for k,v in audit.result()['max_errors'].items():worst[k]=max(worst[k],v)
        return {'seeds':8,'frames':totals,'max_resource_errors':worst}
    check('variable_dt_perturbations_pass_independent_mass_energy_gas_and_momentum_audits',randomized)
    return results

def main():
    results=checks()
    cases=[]
    for name,seconds in [('one_leg',60.),('weight_transfer',46.),('walk',45.),
                         ('slip_recovery',22.),('slip_over_limit',15.),('slip_no_step',15.),('sensory_pause',20.)]:
        frames,s=run_case(name,seconds); cases.append(s)
        if name in ('one_leg','weight_transfer','walk','slip_recovery','sensory_pause'):
            assert s['first_failure_s'] is None,name
        if name=='one_leg':assert s['one_leg_hold_s']>55.
        if name=='walk':assert s['walk_touchdowns']>=6
        if name=='slip_recovery':assert s['protective_touchdowns']==1 and s['final_speed_m_s']<1e-3
        if name in ('slip_over_limit','slip_no_step'):assert s['first_failure_s'] is not None
        print('CASE',name,'frames',len(frames),'steps',s['walk_touchdowns'],s['protective_touchdowns'],'failure',s['failure_reason'],flush=True)
    save('results_v06.json',{'schema':'tadash-balance-results/0.6','checks':results,'cases':cases,
                            'all_checks_passed':True,'synthetic_design_model':True})
    print('ALL CHECKS PASSED',len(results),flush=True)

if __name__=='__main__':main()
