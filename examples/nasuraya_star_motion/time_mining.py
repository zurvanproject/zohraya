"""Bounded evidence reuse experiment, not a scheduler or autonomous executor.

Exact result requests may reuse checked receipts. Explicit reproductions always
execute. Every native job starts from the same declared synthetic defaults.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

from evaluate_horizon import evaluate_case,CoordinatedSupport,PostureLoop,NATIVE,ROOT


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def sources():
    repo=ROOT.parents[1]
    files=list((repo/'runtimes/tadash_body').rglob('*.py'))+list((repo/'runtimes/tadash_body').rglob('*.json'))
    files += [ROOT/n for n in ('time_mining.py','evaluate_horizon.py','coordinated_support.py',
                              'horizon_support.py','economical_support.py')]
    return {str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def validate_task(task):
    if not isinstance(task,dict) or set(task)!={'impulse','friction','seconds','dt'}:
        raise ValueError('exact bounded task required')
    if not isinstance(task['impulse'],list) or len(task['impulse'])!=2:
        raise ValueError('two impulse coordinates required')
    for value in [*task['impulse'],task['friction'],task['seconds'],task['dt']]:
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite task values required')
    if (max(map(abs,task['impulse']))>6 or not .1<=task['friction']<=.6
        or not .1<=task['seconds']<=6 or task['dt']!=.1
        or abs(task['seconds']/.1-round(task['seconds']/.1))>1e-8):
        raise ValueError('task outside experiment grant')
    return deepcopy(task)


def compute(task):
    validate_task(task)
    result=evaluate_case({'impulse':task['impulse'],'friction':task['friction']},
                        CoordinatedSupport,task)
    return json.loads(json.dumps(result))


def receipt(task,result):
    payload=dict(schema='nasuraya-time-mining-receipt/1',task=validate_task(task),sources=sources(),result=result)
    return dict(payload=payload,sha256=digest(payload))


def verify(stored,task):
    task=validate_task(task)
    if not isinstance(stored,dict) or set(stored)!={'payload','sha256'}:
        raise ValueError('receipt shape')
    p=stored['payload']
    if (not isinstance(p,dict) or set(p)!={'schema','task','sources','result'}
        or stored['sha256']!=digest(p) or p['schema']!='nasuraya-time-mining-receipt/1'
        or p['task']!=task or p['sources']!=sources()):
        raise ValueError('receipt integrity/task/source mismatch')
    r=p['result']
    with patch.object(PostureLoop,'step',side_effect=AssertionError('verification cannot simulate')), \
         patch.object(CoordinatedSupport,'step',side_effect=AssertionError('verification cannot simulate')):
        before=PostureLoop.restore(r['initial']);after=PostureLoop.restore(r['final'])
        if json.loads(json.dumps(after.checkpoint()))!=r['final']:
            raise ValueError('cold checkpoint differs')
    if r['actual_ticks']!=len(r['rows']) or r['actual_ticks']!=round(task['seconds']/task['dt']):
        raise ValueError('receipt duration incomplete')
    for a,b in [(sum(x['fuel_J'] for x in r['rows']),r['fuel_J']),
                (sum(x['motor_J'] for x in r['rows']),r['motor_J']),
                (before.body.state.fuel_J-after.body.state.fuel_J,r['fuel_J']),
                (after.state.time_s-before.state.time_s,task['seconds'])]:
        if not math.isfinite(a) or not math.isfinite(b) or abs(a-b)>1e-6:
            raise ValueError('receipt accounting mismatch')
    if r['valid']!=all(x['valid'] for x in r['rows']):raise ValueError('receipt validity summary')
    return deepcopy(r)


class EvidenceReuse:
    """Single-process local experiment store; no crash/exactly-once claim."""
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)

    def path(self,task):
        return self.directory/(digest(validate_task(task))+'.json')

    def execute(self,task,kind='get',reuse=True):
        if kind not in ('get','reproduce'):raise ValueError('unknown query contract')
        task=validate_task(task);path=self.path(task)
        prior=None
        if path.exists():
            prior=json.loads(path.read_text());verify(prior,task)
        if reuse and kind=='get' and prior is not None:
            return dict(mode='verified_reuse',receipt=prior,actual_ticks=0)
        fresh=receipt(task,compute(task));verify(fresh,task)
        if prior is not None and fresh!=prior:
            raise ValueError('new reproduction differs from stored deterministic receipt')
        if prior is None:
            # Exclusive creation: never overwrite an existing experience.
            with path.open('x') as f:f.write(json.dumps(fresh,indent=2)+'\n')
        return dict(mode='fresh_reproduction' if kind=='reproduce' else 'fresh_compute',
                    receipt=fresh,actual_ticks=fresh['payload']['result']['actual_ticks'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--store',required=True);p.add_argument('--task',required=True)
    p.add_argument('--kind',choices=('get','reproduce'),default='get');a=p.parse_args()
    result=EvidenceReuse(a.store).execute(json.loads(Path(a.task).read_text()),a.kind)
    print(json.dumps({'mode':result['mode'],'actual_ticks':result['actual_ticks'],'receipt_sha256':result['receipt']['sha256']}))
