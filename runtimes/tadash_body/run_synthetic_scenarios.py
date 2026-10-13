"""Twelve synthetic interventions, ten assertions; no canonical continuation."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path

from unified_body_v2 import UnifiedBody,ROOT,instant,atomic_json
from audit_self_model import assess

from synthetic_fixture import synthetic_body

def probe(body,name,external=None,requested='observe',duration=.5):
    r=body.cycle(event_id=name+'-'+str(body.revision),
        at_utc=(instant(body.owner.wall_utc)+timedelta(seconds=duration)).isoformat(),
        duration_s=duration,external=external or {},requested=requested)
    f=body.owner.physical.last
    return dict(name=name,external=external or {},requested=requested,
        duration_s=duration,initial=r['owner']['before_selection'],
        final=r['owner']['outcome_minimum_state'],selected=r['owner']['selected_action'],
        prediction=r['owner']['prediction'],whole_body_audit=r['whole_body_audit'],
        gas=asdict(body.owner.physical.coupling.gas),respiration=f['respiration'],
        organ_metabolism_J=r['organ_metabolism_J'],body_model_valid=r['owner']['physical_model_valid'],
        self_model=assess(body),trace=r['trace'])

def main():
    start=datetime.now(timezone.utc).isoformat()
    base=synthetic_body()
    cases=[]
    for name,ext,action in [
        ('baseline',{},'observe'),('current_activity_request',{},'walk'),
        ('gas_exchange_failure',{'capacities':{'lung':0.}},'observe'),
        ('airway_obstruction',{'native':{'airway_capacity':0.}},'observe'),
        ('renal_capacity_reduction',{'capacities':{'kidney':.2}},'observe'),
        ('meal_water_light',{'meal_J':10000,'drink_L':.2,'irradiance_w_m2':600},'observe')]:
        b=deepcopy(base)
        if name == 'current_activity_request':
            b.owner.aux['sleep_pressure']=.95
        cases.append(probe(b,name,ext,action))
        if name in ('gas_exchange_failure','airway_obstruction'):
            cases.append(probe(b,name+'_recovery',{},'observe',1.))
    # These two are declared fault fixtures. They are NOT saved as canonical
    # checkpoints and are not claims of observed spontaneous bodily events.
    for name,fuel,heat,action in [('low_energy',20000.,None,'walk'),('heat_load',None,450000.,'cool')]:
        b=deepcopy(base)
        changes={}
        if fuel is not None:
            b.owner.owner.body.state.fuel_J=fuel;changes['fuel_J']=fuel
        if heat is not None:
            b.owner.owner.body.state.heat_J=heat;changes['heat_J']=heat
        row=probe(b,name,{},action)
        row['fixture_changes']=changes;row['canonical_state_modified']=False;cases.append(row)
    # A prediction is locked before the outcome-only impulse. Both clones
    # receive the same prior state; the controller never sees the disturbance.
    a,b=deepcopy(base),deepcopy(base)
    clean=probe(a,'prediction_control',duration=.2)
    disturbed=probe(b,'prediction_disturbance',{'native':{'unexpected_impulse_N_s':[10.,0.]}},duration=.2)
    cases.extend([clean,disturbed])
    feedback={}
    c=deepcopy(base);t=c.owner.owner.body.state.time_s
    sample=lambda v,ts:dict(value=v,source_id='audit',sampled_at_s=ts,kind='declared_simulated_input')
    probe(c,'fresh_feedback',{'sensors':{'touch':sample(.2,t)}},duration=.1)
    for name,ts,value in [('delayed',t-1,.9),('contradictory',t,.9)]:
        before=c.checkpoint()
        try:probe(c,name,{'sensors':{'touch':sample(value,ts)}},duration=.1)
        except ValueError as e:feedback[name]=dict(rejected=True,reason=str(e),state_unchanged=c.checkpoint()==before)
        else:feedback[name]=dict(rejected=False,state_unchanged=False)
    checks={
        'zero_lung_exchange':all(cases[2]['respiration']['ledger'][k]==0. for k in ('uptake_L','cleared_co2_L')),
        'activity_veto_matches_existing_fatigue_and_sleep':cases[1]['selected']!='walk',
        'low_energy_veto':next(x for x in cases if x['name']=='low_energy')['selected']!='walk',
        'heat_response':next(x for x in cases if x['name']=='heat_load')['selected']=='cool',
        'recovery_restores_uptake':all(x['respiration']['ledger']['uptake_L']>0. for x in cases if x['name'].endswith('_recovery')),
        'energy_water_neural_invariants':all(x['whole_body_audit']['energy_error_J']<5e-5 and x['whole_body_audit']['water_error_L']<1e-8 and x['whole_body_audit']['neural_clock_error_s']<1e-7 for x in cases),
        'no_prediction_leakage':clean['prediction']['predicted']==disturbed['prediction']['predicted'],
        'outcome_error_detected':disturbed['prediction']['mean_scaled_absolute_error']>0.,
        'invalid_feedback_transactional':all(v['rejected'] and v['state_unchanged'] for v in feedback.values()),
        'expired_self_model_requests_evidence':assess(base,at_simulated_s=base.owner.owner.body.state.time_s+6)['request_new_evidence'],
    }
    result=dict(schema='tadash-synthetic-scenarios/1',
        start_utc=start,end_utc=datetime.now(timezone.utc).isoformat(),
        fixture='defaults plus explicit synthetic fault injections',
        scenario_count=len(cases), checks=checks,
        passed_checks=sum(checks.values()),
        empirical_validation=False, canonical_state_loaded=False,
        canonical_state_modified=False,
        max_energy_error_J=max(x['whole_body_audit']['energy_error_J'] for x in cases),
        max_water_error_L=max(x['whole_body_audit']['water_error_L'] for x in cases),
        max_neural_clock_error_s=max(x['whole_body_audit']['neural_clock_error_s'] for x in cases))
    print(json.dumps(result,sort_keys=True))
    if not all(checks.values()):raise RuntimeError('scenario checks failed')

if __name__=='__main__':main()
