"""Frozen, finite offline calibration using prior measured walking experience.

The selected parameter is a small COM reference offset, never a body mutation.
Training and held-out evaluation are separate commands. Held-out outcomes cannot
change the saved policy. All candidates retain the original walking guards,
timing, actuator limits and physics. No model API or live checkpoint is used.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import time

from .build import ROOT
from .canon_trial import CANDIDATE
from .checkpoint import digest
from .stepping import walk_trial

SCHEMA='nasuraya.balance-experience/1'


def frozen_plan():
    return dict(schema=SCHEMA,body='isolated v03 78 kg / 1.70 m',steps=2,
        candidates_m=[0.,-.006,-.003,.003,.006],
        training=[
            dict(id='train_nominal',friction=.6,stride=.06,push=0.),
            dict(id='train_low_mu',friction=.45,stride=.055,push=0.),
            dict(id='train_push',friction=.55,stride=.06,push=-6.)],
        holdouts=[
            dict(id='holdout_mu35',friction=.35,stride=.06,push=0.),
            dict(id='holdout_mu80',friction=.80,stride=.06,push=0.),
            dict(id='holdout_long',friction=.60,stride=.075,push=0.),
            dict(id='holdout_push_right',friction=.60,stride=.06,push=10.),
            dict(id='holdout_combined',friction=.40,stride=.07,push=8.),
            dict(id='holdout_half_dt',friction=.60,stride=.06,push=0.,dt=.0005)],
        selection=dict(rule='minimum mean training RMS tilt among all-pass candidates',
                       minimum_training_reduction=.05,maximum_extra_duration_s=.1,
                       settle_speed_limit=.05,tie_break='smallest absolute offset then signed value'),
        evaluation=dict(rule='paired fixed-scenario comparison, no holdout tuning',
                        minimum_geometric_mean_reduction=.05,maximum_case_regression=.10,
                        all_cases_must_pass=True),
        controls=['zero offset: same controller without calibrated experience',
                  'same body, timing, force limits and safety gates in each pair'],
        limitations=['hand-authored finite candidate set; offline empirical parameter selection',
                     'deterministic synthetic scenarios, not independent real-world subjects',
                     'full-state simulator feedback; no learned estimator or neural weights',
                     'no anatomy change, live state migration or automatic deployment'])


def sources():
    paths=[Path(__file__).with_name(n) for n in
           ('experience_balance.py','stepping.py','balance.py','evaluate.py','support_geometry.py')]
    paths += [CANDIDATE/'nasuraya.xml',CANDIDATE/'robot.yaml']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def write_json(path,value):
    path=Path(path)
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')


def freeze(folder):
    folder=Path(folder)
    if folder.resolve().is_relative_to((ROOT/'runtimes').resolve()):
        raise ValueError('native runtime destinations are forbidden')
    folder.mkdir(parents=True,exist_ok=True)
    p=frozen_plan()
    p['sources_sha256']=sources()
    p['packages']={n:importlib.metadata.version(n) for n in ('mujoco','numpy','scipy','osqp','PyYAML')}
    p['frozen_at_utc']=datetime.now(timezone.utc).isoformat()
    write_json(folder/'protocol.json',p)
    return p


def read_plan(folder):
    p=json.loads((Path(folder)/'protocol.json').read_text())
    if p['schema']!=SCHEMA or p['sources_sha256']!=sources():
        raise ValueError('frozen protocol/source drift')
    for name,version in p['packages'].items():
        if importlib.metadata.version(name)!=version:
            raise ValueError('package drift: '+name)
    return p


def run_one(folder,case,bias,split):
    folder=Path(folder);name=f'{split}-{case["id"]}-{bias:+.3f}'
    path=folder/(name+'.json')
    if path.exists():
        # Reuse complete measured outcomes, never rerun merely to improve a result.
        old=json.loads(path.read_text())
        if old['case']!=case or old['bias_m']!=bias or old['split']!=split:
            raise ValueError('trial identity mismatch')
        return old
    start=time.monotonic()
    kwargs={k:v for k,v in case.items() if k!='id'}
    result=walk_trial(label=name,steps=2,model_dir=CANDIDATE,geometry_support=True,
                      com_bias_x_m=bias,**kwargs)
    trace=result.pop('trace')
    trace_bytes=gzip.compress(json.dumps(trace,separators=(',',':'),allow_nan=False).encode(),mtime=0)
    trace_path=folder/(name+'-trace.json.gz');trace_path.write_bytes(trace_bytes)
    record=dict(case=case,bias_m=bias,split=split,result=result,
                wall_seconds=time.monotonic()-start,trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
                completed_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(path,record)
    print(json.dumps(dict(case=case['id'],bias_m=bias,split=split,
                         wall_seconds=record['wall_seconds'],accepted_steps=result['accepted_steps'],
                         rms_tilt_deg=result['tilt_rms_deg'],max_tilt_deg=result['max_tilt_deg'],
                         failure=result['failure'])),flush=True)
    return record


def eligible(result):
    return bool(result['walk_pass'] and result['accepted_steps']==2
                and result['final_max_generalized_speed']<.05
                and result['tilt_rms_deg'] is not None and math.isfinite(result['tilt_rms_deg']))


def select_policy(plan,records):
    ids=[c['id'] for c in plan['training']]
    cases={c['id']:c for c in plan['training']}
    expected={(case,bias) for case in ids for bias in plan['candidates_m']}
    indexed={}
    for record in records:
        key=(record['case']['id'],record['bias_m'])
        if record['split']!='train' or key not in expected or key in indexed:
            raise ValueError('selection accepts unique training observations only')
        if record['case']!=cases[key[0]]:
            raise ValueError('training scenario differs from frozen plan')
        indexed[key]=record['result']
    if set(indexed)!=expected:
        raise ValueError('complete frozen training grid required')
    rows=[]
    for bias in plan['candidates_m']:
        observations=[indexed[(case,bias)] for case in ids]
        ok=all(eligible(r) for r in observations)
        ok=ok and all(r['simulated_seconds']<=indexed[(case,0.)]['simulated_seconds']+.1
                      for case,r in zip(ids,observations))
        score=sum(r['tilt_rms_deg'] for r in observations)/len(observations) if ok else None
        rows.append(dict(bias_m=bias,eligible=ok,mean_rms_tilt_deg=score))
    baseline=next(r for r in rows if r['bias_m']==0.)
    candidates=[r for r in rows if r['eligible']]
    if not baseline['eligible']:
        raise ValueError('baseline training gate failed; no promotion')
    best=min(candidates,key=lambda r:(r['mean_rms_tilt_deg'],abs(r['bias_m']),r['bias_m']))
    reduction=1-best['mean_rms_tilt_deg']/baseline['mean_rms_tilt_deg']
    chosen=best['bias_m'] if reduction>=plan['selection']['minimum_training_reduction'] else 0.
    return dict(schema=SCHEMA,selected_bias_m=chosen,training_rows=rows,
                training_reduction=reduction,protocol_sha256=digest(plan),
                training_observations_sha256=digest(records),native_apply_allowed=False,
                model_weights_updated=False,policy_scope='offline COM reference calibration')


def train(folder):
    plan=read_plan(folder);records=[]
    for bias in plan['candidates_m']:
        for case in plan['training']:
            records.append(run_one(folder,case,bias,'train'))
    policy=select_policy(plan,records)
    write_json(Path(folder)/'policy.json',policy)
    print(json.dumps(policy),flush=True)
    return policy


def evaluate(folder):
    plan=read_plan(folder);path=Path(folder)/'policy.json'
    policy_bytes=path.read_bytes();policy=json.loads(policy_bytes)
    # Recompute solely from the persisted training rows, before any held-out run.
    records=[json.loads((Path(folder)/f'train-{c["id"]}-{b:+.3f}.json').read_text())
             for b in plan['candidates_m'] for c in plan['training']]
    if policy!=select_policy(plan,records):raise ValueError('policy differs from training experience')
    bias=policy['selected_bias_m'];pairs=[]
    for case in plan['holdouts']:
        baseline=run_one(folder,case,0.,'holdout')
        candidate=baseline if bias==0 else run_one(folder,case,bias,'holdout')
        b,c=baseline['result'],candidate['result']
        pairs.append(dict(case=case['id'],baseline_pass=eligible(b),candidate_pass=eligible(c),
                          baseline_rms=b['tilt_rms_deg'],candidate_rms=c['tilt_rms_deg'],
                          reduction=1-c['tilt_rms_deg']/b['tilt_rms_deg'],
                          baseline_max_tilt=b['max_tilt_deg'],candidate_max_tilt=c['max_tilt_deg'],
                          baseline_steps=b['accepted_steps'],candidate_steps=c['accepted_steps'],
                          baseline_slide=max((s['max_stance_slide_m'] for s in b['steps']),default=None),
                          candidate_slide=max((s['max_stance_slide_m'] for s in c['steps']),default=None)))
    reduction=1-math.exp(sum(math.log(p['candidate_rms']/p['baseline_rms']) for p in pairs)/len(pairs))
    success=(all(p['baseline_pass'] and p['candidate_pass'] for p in pairs)
             and reduction>=plan['evaluation']['minimum_geometric_mean_reduction']
             and min(p['reduction'] for p in pairs)>=-plan['evaluation']['maximum_case_regression'])
    report=dict(schema=SCHEMA,policy_sha256=hashlib.sha256(policy_bytes).hexdigest(),pairs=pairs,
                geometric_mean_rms_reduction=reduction,predeclared_success=success,
                selected_bias_m=bias,no_holdout_retuning=True,native_apply_allowed=False)
    if path.read_bytes()!=policy_bytes:raise RuntimeError('policy changed during evaluation')
    write_json(Path(folder)/'evaluation.json',report)
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['freeze','train','evaluate'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    {'freeze':freeze,'train':train,'evaluate':evaluate}[args.phase](args.output)
