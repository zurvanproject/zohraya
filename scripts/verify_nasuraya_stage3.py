"""Replay opened stage-3 holdout; verify every prediction before its truth reveal.

No training/selection, no novel independent evidence. Runtime source hashes are
checked before generation. Cross-Python numeric tolerance excludes wall time.
"""
import argparse
import gzip
import json
import math
from pathlib import Path
import platform

from examples.nasuraya_runtime import noise_study
from examples.tadash_interoception.state import digest

REFERENCE=Path(__file__).resolve().parents[1]/'docs/evidence/nasuraya-stage3-v01'


def compare(a,b,path='root'):
    if type(a) in (int,float) and type(b) in (int,float):
        if not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-10):raise AssertionError(path+': numeric mismatch')
    elif isinstance(a,dict) and isinstance(b,dict):
        if a.keys()!=b.keys():raise AssertionError(path+': changed keys')
        for key in a:
            if key not in ('elapsed_seconds','state_sha'):compare(a[key],b[key],path+'.'+key)
    elif isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):raise AssertionError(path+': changed length')
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,f'{path}[{i}]')
    elif type(a)!=type(b) or a!=b:raise AssertionError(path+': categorical mismatch')


def audit(lines,predictions):
    expected={f'{group}:{r["seed"]}:{r["tick"]}':r for group,rows in predictions.items() for r in rows}
    pending={};seen=set();tail='0'*64;wrong=0;count=0
    for seq,line in enumerate(lines):
        r=json.loads(line);sha=r.pop('sha256')
        if r['sequence']!=seq or r['previous']!=tail or digest(r)!=sha:raise AssertionError('observer continuity')
        tail=sha;identity=r['identity'];reference=expected[identity]
        if r['kind']=='prediction':
            if identity in seen or 'truth' in r:raise AssertionError('nonblind or repeated prediction')
            compare(reference['predictions']['candidate'],r['prediction'])
            if reference['state_sha']!=r['state_sha']:raise AssertionError('state commitment mismatch')
            pending[identity]=r;seen.add(identity)
        elif r['kind']=='revealed_outcome':
            if identity not in pending:raise AssertionError('truth before prediction')
            compare(reference['truth'],r['truth']);pending.pop(identity)
            count+=1;wrong+=int(r['wrong'])
        else:raise AssertionError('unexpected observer event')
    if pending or seen!=set(expected):raise AssertionError('incomplete observer coverage')
    return {'predictions':count,'observer_events':len(lines),'strict_errors':wrong,'tail_sha256':tail}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    original=json.loads((REFERENCE/'report.json').read_text(encoding='utf-8'))
    predictions=json.loads(gzip.decompress((REFERENCE/'predictions.json.gz').read_bytes()))
    first=audit(gzip.decompress((REFERENCE/'observer.jsonl.gz').read_bytes()).splitlines(),predictions)
    noise_study.test(args.output,REFERENCE/'frozen-model.json')
    actual=json.loads((args.output/'report.json').read_text(encoding='utf-8'))
    rows=json.loads(gzip.decompress((args.output/'predictions.json.gz').read_bytes()))
    compare(original,actual);compare(predictions,rows)
    second=audit((args.output/'observer.jsonl').read_bytes().splitlines(),rows)
    changed=sum(a['state_sha']!=b['state_sha'] for group in predictions for a,b in zip(predictions[group],rows[group]))
    result={'regression_passed':True,'python':platform.python_version(),'model_updates':0,
        'categorical_comparison':'exact','absolute_tolerance':1e-10,'relative_tolerance':1e-9,
        'reference_observer':first,'current_observer':second,'state_byte_hash_differences':changed,
        'state_hash_policy':'exact inside each transcript; numeric tolerance across Python versions',
        'timings_compared':False,'new_independent_test':False}
    noise_study.stream_study.write(args.output/'verification.json',result)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
