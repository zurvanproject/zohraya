"""Verify saved horizon evidence without simulating a tick or using a network."""
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

from evaluate_horizon import PostureLoop,CoordinatedSupport,EconomicalSupport,HorizonSupport
from economical_support import restore as restore_greedy,checkpoint as greedy_checkpoint
from horizon_support import restore as restore_horizon,checkpoint as horizon_checkpoint


def close(a,b,tolerance=1e-6):
    if not math.isfinite(a) or not math.isfinite(b) or abs(a-b)>tolerance:
        raise ValueError('saved numerical evidence mismatch')


def verify(path):
    r=json.loads(Path(path).read_text());p=r['protocol'];root=Path(__file__).parent
    if hashlib.sha256((root/'horizon_protocol.json').read_bytes()).hexdigest()!=r['protocol_sha256']:
        raise ValueError('protocol source mismatch')
    if json.loads((root/'horizon_protocol.json').read_text())!=p:
        raise ValueError('protocol payload mismatch')
    expected_sources={'horizon_support.py','economical_support.py','coordinated_support.py','evaluate_horizon.py'}
    if set(r['source_sha256'])!=expected_sources:raise ValueError('missing or unexpected source')
    for name,expected in r['source_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('implementation source mismatch')
    if len(r['rows'])!=len(p['cases']):raise ValueError('case count')
    ticks=0;restores=0
    with patch.object(PostureLoop,'step',side_effect=AssertionError('native replay forbidden')), \
         patch.object(CoordinatedSupport,'step',side_effect=AssertionError('native replay forbidden')), \
         patch.object(EconomicalSupport,'step',side_effect=AssertionError('native replay forbidden')), \
         patch.object(HorizonSupport,'step',side_effect=AssertionError('native replay forbidden')):
        for row,case in zip(r['rows'],p['cases']):
            if row['case']!=case or set(row['arms'])!={'coordinated','greedy','horizon'}:
                raise ValueError('case/arm identity')
            for kind,a in row['arms'].items():
                initial=PostureLoop.restore(a['initial'])
                final=(restore_horizon(a['final']) if kind=='horizon' else restore_greedy(a['final'])
                       if kind=='greedy' else PostureLoop.restore(a['final']))
                restored=(horizon_checkpoint(final) if kind=='horizon' else greedy_checkpoint(final)
                          if kind=='greedy' else final.checkpoint())
                if json.loads(json.dumps(restored))!=a['final']:
                    raise ValueError('cold checkpoint differs')
                restores+=1;ticks+=a['actual_ticks']
                if a['actual_ticks']!=len(a['rows']):raise ValueError('row count')
                close(sum(f['fuel_J'] for f in a['rows']),a['fuel_J'])
                close(sum(f['motor_J'] for f in a['rows']),a['motor_J'])
                close(initial.body.state.fuel_J-final.body.state.fuel_J,a['fuel_J'])
                close(final.state.time_s-initial.state.time_s,p['dt']*a['actual_ticks'])
                close(math.hypot(*final.state.com_m),a['terminal_position_m'])
                close(math.hypot(*final.state.velocity_m_s),a['terminal_speed_m_s'])
                if a['valid']!=all(f['valid'] for f in a['rows']):raise ValueError('validity summary')
                if any(not audit['passed'] or audit['frames']!=a['actual_ticks'] for audit in a['audits'].values()):
                    raise ValueError('audit summary')
    savings={k:sum(1-x['arms']['horizon']['fuel_J']/x['arms'][k]['fuel_J'] for x in r['rows'])/len(r['rows'])
             for k in ('coordinated','greedy')}
    for k,v in savings.items():close(v,r['mean_fuel_saving'][k],1e-12)
    valid=all(x['arms']['horizon']['valid'] and x['arms']['horizon']['actual_ticks']==round(p['seconds']/p['dt']) for x in r['rows'])
    terminal=all(x['arms']['horizon']['terminal_position_m']<=p['terminal_position_m']
                 and x['arms']['horizon']['terminal_speed_m_s']<=p['terminal_speed_m_s'] for x in r['rows'])
    if (r['all_valid']!=valid or r['terminal_contracts']!=terminal or
        r['accepted']!=(valid and terminal and savings['coordinated']>=p['minimum_mean_fuel_saving'])
        or r['owner_ticks']!=ticks or r['canonical_cycles']!=0 or r['api_calls']!=0):
        raise ValueError('decision/execution summary')
    return dict(verified=True,cold_restores=restores,saved_owner_ticks=ticks,
                verification_native_ticks=0,api_calls=0,mean_fuel_saving=savings,accepted=r['accepted'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('results');a=p.parse_args()
    print(json.dumps(verify(a.results)))
