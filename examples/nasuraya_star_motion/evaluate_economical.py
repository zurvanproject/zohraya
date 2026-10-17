"""Authored deterministic native-posture comparison, no private user state."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[2]
NATIVE=REPO/'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06'
sys.path.insert(0,str(NATIVE))
from posture_step import PostureLoop, GaitEnvironment, Inputs
from coordinated_support import CoordinatedSupport
from economical_support import EconomicalSupport, checkpoint, restore


def run_case(case, cls, seconds, dt):
    b=cls()
    origin=b.checkpoint()
    rows=[]
    for i in range(round(seconds/dt)):
        env=GaitEnvironment(body=Inputs(dt_s=dt), command='stand',
            friction={'L':case['friction'],'R':case['friction']},
            external_impulse_N_s=case['impulse'] if i==0 else [0.,0.])
        f=b.step(env)
        rows.append(dict(t_s=b.state.time_s, valid=f['balance']['model_valid'],
            reason=b.state.failed_reason, com_m=list(b.state.com_m),
            velocity_m_s=list(b.state.velocity_m_s),
            fuel_J=f['ledger']['fuel_used_J'],motor_J=f['ledger']['motor_energy_J'],
            support=f['contact']['joint_support_fraction'],margin_m=f['balance']['capture_margin_m'],
            diagnostics=f['posture'].get('economical_governor'),
            conservation=deepcopy(f.get('conservation',{}))))
        if not f['balance']['model_valid']:
            break
    return dict(origin=origin,rows=rows,final=checkpoint(b) if cls is EconomicalSupport else b.checkpoint(),
        valid=all(r['valid'] for r in rows), fuel_J=sum(r['fuel_J'] for r in rows),
        motor_J=sum(r['motor_J'] for r in rows),
        terminal_position_m=math.hypot(*b.state.com_m),
        terminal_speed_m_s=math.hypot(*b.state.velocity_m_s),
        actual_ticks=len(rows), minimum_support=min(r['support'] for r in rows))


def run(protocol_path, output):
    protocol_path=Path(protocol_path)
    protocol=json.loads(protocol_path.read_text())
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    results=[]
    for case in protocol['cases']:
        arms={k:run_case(case,c,protocol['seconds'],protocol['dt']) for k,c in
              [('native',PostureLoop),('coordinated',CoordinatedSupport),('economical',EconomicalSupport)]}
        results.append(dict(case=case,arms=arms))
        print(json.dumps({'case':case,'fuel_J':{k:v['fuel_J'] for k,v in arms.items()},
                          'valid':{k:v['valid'] for k,v in arms.items()}}),flush=True)
    savings=[1-row['arms']['economical']['fuel_J']/row['arms']['coordinated']['fuel_J'] for row in results]
    safe=all(row['arms']['economical']['valid'] for row in results)
    terminal=all(row['arms']['economical']['terminal_position_m']<=protocol['terminal_position_m']
                 and row['arms']['economical']['terminal_speed_m_s']<=protocol['terminal_speed_m_s'] for row in results)
    useful=sum(savings)/len(savings)>=protocol['minimum_mean_fuel_saving']
    result=dict(schema='nasuraya-native-gravity-comparison/1',protocol=protocol,
        protocol_sha256=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        results=results,mean_fuel_saving=sum(savings)/len(savings),all_valid=safe,
        all_terminal_contracts=terminal,accepted=safe and terminal and useful,
        native_owner_ticks=sum(a['actual_ticks'] for r in results for a in r['arms'].values()),
        canonical_cycles=0,api_calls=0,wall_seconds=time.perf_counter()-started,
        limitations=['native posture layer only, not whole-body arbitration',
          'authored deterministic cases; not blinded or human/robot measurements',
          'constant-height model has no flight and no vertical running bounce',
          'fuel is native model bookkeeping; CPU prediction cost is separate'])
    (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('results','protocol')}),flush=True)
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--protocol',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.protocol,a.output)
