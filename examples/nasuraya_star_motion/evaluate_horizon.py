"""Predefined paired whole-trajectory evaluation of stand control horizons."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent
NATIVE=ROOT.parents[1]/'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06'
sys.path.insert(0,str(NATIVE))
from posture_step import PostureLoop,GaitEnvironment,Inputs
from coordinated_support import CoordinatedSupport
from economical_support import EconomicalSupport,checkpoint as greedy_checkpoint
from horizon_support import HorizonSupport,checkpoint
from run_balance_checks import ConservationAudit,GasAudit,PhysicsAudit


def evaluate_case(case,cls,p):
    body=cls();initial=body.checkpoint()
    resource=ConservationAudit(asdict(body.body.state));gas=GasAudit(body);physics=PhysicsAudit(body)
    rows=[];adjusted=forecasts=0
    for i in range(round(p['seconds']/p['dt'])):
        e=GaitEnvironment(body=Inputs(dt_s=p['dt']),command='stand',
            friction={'L':case['friction'],'R':case['friction']},
            external_impulse_N_s=case['impulse'] if i==0 else [0.,0.])
        f=body.step(e)
        resource.frame(f);gas.frame(f);physics.frame(f,e)
        diagnostics=f['posture'].get('horizon_governor',f['posture'].get('economical_governor'))
        if diagnostics:
            adjusted+=int(diagnostics['adjusted']);forecasts+=diagnostics['candidate_probes']
        rows.append(dict(t_s=body.state.time_s,valid=f['balance']['model_valid'],
            fuel_J=f['ledger']['fuel_used_J'],motor_J=f['ledger']['motor_energy_J'],
            com_m=list(body.state.com_m),velocity_m_s=list(body.state.velocity_m_s),
            support=f['contact']['joint_support_fraction'],margin_m=f['balance']['capture_margin_m'],
            diagnostics=diagnostics))
        if not f['balance']['model_valid']:break
    final=(checkpoint(body) if cls is HorizonSupport else greedy_checkpoint(body) if cls is EconomicalSupport else body.checkpoint())
    return dict(initial=initial,final=final,rows=rows,
        fuel_J=sum(f['fuel_J'] for f in rows),motor_J=sum(f['motor_J'] for f in rows),
        valid=all(f['valid'] for f in rows),actual_ticks=len(rows),adjusted_ticks=adjusted,
        forecast_candidates=forecasts,terminal_position_m=math.hypot(*body.state.com_m),
        terminal_speed_m_s=math.hypot(*body.state.velocity_m_s),
        audits=dict(resource=resource.result(),gas=gas.result(),physics=physics.result()))


def run(protocol_path,output):
    protocol_path=Path(protocol_path);p=json.loads(protocol_path.read_text())
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();rows=[]
    for case in p['cases']:
        arms={}
        for k,cls in [('coordinated',CoordinatedSupport),('greedy',EconomicalSupport),('horizon',HorizonSupport)]:
            t=time.perf_counter();arms[k]=evaluate_case(case,cls,p);arms[k]['cpu_wall_seconds']=time.perf_counter()-t
        rows.append(dict(case=case,arms=arms))
        print(json.dumps({'case':case,'fuel_J':{k:v['fuel_J'] for k,v in arms.items()},
                          'horizon_adjustments':arms['horizon']['adjusted_ticks']}),flush=True)
    savings={k:sum(1-r['arms']['horizon']['fuel_J']/r['arms'][k]['fuel_J'] for r in rows)/len(rows)
             for k in ('coordinated','greedy')}
    valid=all(r['arms']['horizon']['valid'] and r['arms']['horizon']['actual_ticks']==round(p['seconds']/p['dt']) for r in rows)
    terminal=all(r['arms']['horizon']['terminal_position_m']<=p['terminal_position_m']
                 and r['arms']['horizon']['terminal_speed_m_s']<=p['terminal_speed_m_s'] for r in rows)
    result=dict(schema='nasuraya-native-gravity-horizon/2',protocol=p,
        protocol_sha256=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
          ('horizon_support.py','economical_support.py','coordinated_support.py','evaluate_horizon.py')},
        rows=rows,mean_fuel_saving=savings,all_valid=valid,terminal_contracts=terminal,
        accepted=valid and terminal and savings['coordinated']>=p['minimum_mean_fuel_saving'],
        owner_ticks=sum(a['actual_ticks'] for r in rows for a in r['arms'].values()),
        canonical_cycles=0,api_calls=0,wall_seconds=time.perf_counter()-started)
    (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','protocol','source_sha256')}),flush=True)
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--protocol',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.protocol,a.output)
