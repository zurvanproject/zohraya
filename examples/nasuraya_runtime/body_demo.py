"""Inspect executed parameters and contacts; never infer motion from action names."""
import argparse
import gzip
import json
from pathlib import Path
import platform
import time

from .adapters import native_call
from .profile import CURRENT,LEGACY,current
from .stream_study import write


def run(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();report={'python':platform.python_version(),'current_contract':current(),
        'cases':{},'external_actions':0,'empirical_physiology_validation':False}
    for kind in (LEGACY,CURRENT):
        for fixture in ('normal','sleep'):
            initial=native_call({'checkpoint':None,'fixture':fixture,'body_profile':kind})
            state=initial;receipts=[]
            for i in range(6):
                request={'checkpoint':state['checkpoint'],'body_profile':kind,'fixture':fixture,
                         'duration':1.6,'touch':0.,'requested':'walk','event_id':'walk-'+str(i)}
                state=native_call(request);receipts.append(state['receipt'])
                if i==0:
                    assert native_call(json.loads(json.dumps(request)))==state
            key=kind+'/'+fixture
            report['cases'][key]={'initial':{k:initial[k] for k in ('physical_parameters','export','clock')},
                'final':{k:state[k] for k in ('physical_parameters','export','clock')},
                'action_selection':[r['executed'] for r in receipts],
                'completed_walk_touchdowns':sum(r['physical_outcome']['walk_touchdowns'] for r in receipts),
                'energy_max_error_J':max(abs(r['audit']['energy_error_J']) for r in receipts),
                'water_max_error_L':max(abs(r['audit']['water_error_L']) for r in receipts),
                'same_owner_ticks':all(r['audit']['same_owner_ticks'] for r in receipts),
                'cold_first_cycle_reproduction':True}
            write(directory/(kind+'-'+fixture+'.json.gz'),
                  {'initial':initial,'final':state,'receipts':receipts},compressed=True)
    report['elapsed_seconds']=time.perf_counter()-start
    write(directory/'body-report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    run(args.output);print(json.dumps({'output':str(args.output)}))
