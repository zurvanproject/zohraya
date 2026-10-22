"""Verify saved synthetic route accounting in a fresh process, without ticks.

This validates saved consistency; rerun evaluate_spiral.py to reproduce dynamics.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

from evaluate_spiral import HERE, NATIVE, native_hashes
from extension_state import checkpoint, restore, StarMotion
from unified_body_v2 import UnifiedBody
from persistent_embodiment_v1 import PersistentEmbodiment
from posture_step import PostureLoop
from coordinated_support import CoordinatedSupport


def verify(directory):
    d=Path(directory)
    r=json.loads((d/'result.json').read_text())
    protocol=json.loads((HERE/'spiral_protocol.json').read_text())
    assert set(r['native_source_sha256']) == set(native_hashes()), 'missing native source coverage'
    assert set(r['experiment_source_sha256']) == {
        'evaluate_spiral.py','spiral_protocol.json','coordinated_support.py',
        'extension_state.py','run_bounded_route.py'}, 'missing experiment source coverage'
    for root,field in ((HERE,'experiment_source_sha256'),(NATIVE,'native_source_sha256')):
        for name,h in r[field].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h, f'source mismatch: {name}'
    with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('forbidden tick')), \
         patch.object(PersistentEmbodiment,'_simulate',side_effect=AssertionError('forbidden tick')), \
         patch.object(PostureLoop,'step',side_effect=AssertionError('forbidden tick')), \
         patch.object(CoordinatedSupport,'step',side_effect=AssertionError('forbidden tick')):
        initial=restore(json.loads((d/'initial.json').read_text()))
        raw=json.loads((d/'checkpoint.json').read_text());final=restore(raw)
        assert checkpoint(final)==raw
        if r['recovery_executed']:
            stopped=json.loads((d/'stopped.json').read_text());pause=restore(stopped)
            assert checkpoint(pause)==stopped
            assert pause.owner.physical.state.phase=='double_support'
            assert pause.owner.physical.state.swing is None
            assert not pause.owner.physical.star_enabled
        rows,frames=r['rows'],r['frames']
        assert len(rows)==r['seconds'] and len(frames)==10*len(rows)
        assert abs(final.owner.physical.state.time_s-initial.owner.physical.state.time_s-len(rows))<1e-7
        fuel=sum(x['fuel_J'] for x in rows)
        assert abs(fuel-r['fuel_J'])<1e-7
        assert abs(initial.owner.owner.body.state.fuel_J-final.owner.owner.body.state.fuel_J-fuel)<5e-5
        assert abs(sum(f['motor_J'] for f in frames)-r['motor_J'])<1e-7
        assert r['initial_native_sha256']==initial.checkpoint()['sha256']
        assert all(x['audit']['energy_error_J']<5e-5 and x['audit']['water_error_L']<1e-8 for x in rows)
        confirmed=[e for e in r['touchdowns'] if e.get('kind')=='walk']
        assert len(confirmed)==r['confirmed_landings']
        for s in ('L','R'):
            got=[e['position_m'] for e in confirmed if e['side']==s]
            assert got==r['plan'][s][:len(got)]
            assert len(got)==final.owner.physical.star_started[s]
        assert r['requested_landings']==sum(map(len,r['plan'].values()))
        complete=all(final.owner.physical.star_started[s]==len(r['plan'][s]) for s in ('L','R'))
        assert complete==r['complete']
        valid=all(f['valid'] for f in frames)
        assert valid==r['valid'] and valid==all(row['valid'] for row in rows)
        support=min(f['support'] for f in frames)
        assert support==r['minimum_support']
        error=max(math.dist(final.owner.physical.state.feet_m[s],initial.owner.physical.state.feet_m[s]) for s in ('L','R'))
        assert error==r['final_home_error_m']
        assert final.owner.physical.state.phase==r['final_phase']
        assert final.owner.body()['minimum_state']['balance']==r['final_balance']
        speed=math.hypot(*final.owner.physical.state.velocity_m_s)
        assert speed==r['final_speed_m_s']
        assert r['prediction_error_max']==max(row['prediction_error'] for row in rows)
        assert abs(r['prediction_error_mean']-sum(row['prediction_error'] for row in rows)/len(rows))<1e-15
        accepted=(complete and valid and r['stop_reason'] is None and error<=protocol['foot_error_max_m']
            and r['final_phase']=='double_support' and final.owner.physical.state.swing is None
            and speed<=protocol['speed_max_m_s'] and support>=protocol['support_min']
            and (not r['recovery'] or r['recovery_executed']))
        assert accepted==r['accepted']
        assert r['movement_seconds']==sum(row['phase']=='route' for row in rows)<=protocol['movement_max_s']
        return dict(case=d.name,passed=True,accepted=accepted,cold_restore_exact=True,executed_ticks=0,
                    scope='saved consistency and source checks; not dynamics reproduction')


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('directories',nargs='+');args=a.parse_args()
    print(json.dumps([verify(d) for d in args.directories],indent=2))
