"""Reproducible bounded evaluation; includes failures and independent holdouts."""
import argparse
from dataclasses import asdict,replace
import hashlib,json,subprocess
from pathlib import Path
from .running_balance import Profile,Apex,Runner,simulate

PROFILES=[Profile(),Profile('lighter_250cm_165kg',mass_kg=165),
          Profile('shorter_230cm_155kg',height_m=2.3,mass_kg=155),
          Profile('shorter_220cm_140kg',height_m=2.2,mass_kg=140)]
CASES={'nominal':{},'height_minus':{'initial':{'z':-.01}},'height_plus':{'initial':{'z':.01}},
       'speed_minus':{'initial':{'vx':-.1}},'speed_plus':{'initial':{'vx':.1}},
       'lateral_left':{'events':{5:{'vy':.1}}},'lateral_right':{'events':{5:{'vy':-.1}}},
       'mixed_repeated':{'events':{5:{'z':.01,'vx':.1,'vy':.1},15:{'z':-.01,'vx':-.1,'vy':-.1}}}}

def perturb(state,deltas):return replace(state,**{key:getattr(state,key)+delta for key,delta in deltas.items()})

def trial(p,speed,name,case,*,feedback=True,steps=30):
    runner=Runner(p,speed);runner.state=perturb(runner.state,case.get('initial',{}))
    reference=Runner(p,speed).plan()
    if not reference['ok']:return {'profile':p.name,'case':name,'passed':False,'reason':'no_nominal_plan'}
    base=reference['control'];records=[]
    for i in range(steps):
        if i in case.get('events',{}):runner.state=perturb(runner.state,case['events'][i])
        f=runner.step(feedback=feedback,fixed_control=[base[0],runner.state.side*abs(base[1]),base[2]],
                      stiffness_factor=case.get('stiffness_factor',1.))
        records.append(f)
        if not f['ok']:break
    good=[f for f in records if f['ok']];s=runner.state
    tolerance=case.get('tolerance',{'z':.002,'vx':.01,'y':.01,'vy':.02})
    errors={'z':abs(s.z-p.apex),'vx':abs(s.vx-speed),'y':abs(s.y),
            'vy':abs(s.vy-s.side*p.lateral_speed)}
    passed=len(good)==steps and all(errors[k]<tolerance[k] for k in errors)
    metrics={key:max(f['metrics'][key] for f in good) for key in good[0]['metrics'] if key!='foot_transfer_lower_bound_m_s'} if good else {}
    return {'profile':p.name,'speed':speed,'case':name,'feedback':feedback,'requested':steps,
            'completed':len(good),'passed':passed,'final_errors':errors,'tolerances':tolerance,
            'peak_metrics':metrics,'last':records[-1],'records':records}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    result={'schema':'nasuraya-running-feedback/0.1','profiles':[asdict(p) for p in PROFILES],
       'source_base':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
       'scope':'3D point-mass template, exact state feedback; NOT full-body or native runtime',
       'predeclared_selection':'At 3 m/s choose passing profile with unchanged height and lowest mass; shortening only if no unchanged-height profile passes.',
       'comparison':[],'baseline':[],'speed_validation':[],'holdout':[]}
    def checkpoint():
        (args.output/'results.json').write_text(json.dumps(result,indent=2))
    def run_into(category,p,speed,name,case,**kw):
        r=trial(p,speed,name,case,**kw);result[category].append(r)
        print(category,p.name,speed,name,r.get('completed',0),r['passed'],r.get('last',{}).get('reason',''),flush=True)
        checkpoint()
    # Body comparison is performed at identical absolute speed, controller and limits.
    for p in PROFILES:
        for name,case in CASES.items():run_into('comparison',p,3.,name,case)
    eligible=[p for p in PROFILES if all(r['passed'] for r in result['comparison'] if r['profile']==p.name)]
    same_height=[p for p in eligible if p.height_m==2.5]
    candidates=same_height or eligible
    if not candidates:
        result['selection']=None;checkpoint();return
    selected=min(candidates,key=lambda p:p.mass_kg);result['selection']=asdict(selected)
    for name,case in CASES.items():run_into('baseline',selected,3.,name,case,feedback=False)
    for speed in [2.,4.]:
        for name,case in CASES.items():run_into('speed_validation',selected,speed,name,case)
    loose={'z':.02,'vx':.08,'y':.02,'vy':.04}
    holdouts={
       'stiffness_minus_5pct':{'stiffness_factor':.95,'tolerance':loose},
       'stiffness_plus_5pct':{'stiffness_factor':1.05,'tolerance':loose},
       'unseen_lateral_position':{'events':{7:{'y':.03}},'tolerance':loose},
       'unseen_mixed_timing':{'events':{7:{'vx':.15,'vy':-.12},22:{'vx':-.12,'z':.015,'vy':.12}},'tolerance':loose}}
    for name,case in holdouts.items():run_into('holdout',selected,3.,name,case,steps=50)
    # Controls are frozen for integration convergence and work-energy checks.
    runner=Runner(selected);control=runner.plan()['control']
    coarse=simulate(selected,runner.state,control,detailed=True,max_step=.008)
    fine=simulate(selected,runner.state,control,detailed=True,max_step=.004)
    slippery=Runner(replace(selected,friction=.01));before=asdict(slippery.state);failed=slippery.step()
    result['validation']={'half_step_max_state_difference':max(abs(coarse['state'][k]-fine['state'][k]) for k in ['x','y','z','vx','vy']),
        'zero_stiffness':simulate(selected,runner.state,control,stiffness_factor=0),
        'low_friction_rejected':not failed['ok'],'low_friction_reason':failed.get('reason'),
        'low_friction_state_unchanged':before==asdict(slippery.state),
        'actuator_energy_accounting':coarse['metrics']['work_energy_relative_error']}
    checkpoint()
    print('SELECTED',selected.name,flush=True)

if __name__=='__main__':main()
