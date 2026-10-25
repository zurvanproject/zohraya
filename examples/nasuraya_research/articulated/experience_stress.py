"""Predeclared secondary transfer checks; never used to tune the saved policy."""
import argparse
from datetime import datetime,timezone
import gzip,hashlib,json,math,random,time
from pathlib import Path
from .experience_balance import CANDIDATE,read_plan,select_policy,write_json,walk_trial
from .checkpoint import digest


def freeze(folder):
    folder=Path(folder);primary=read_plan(folder)
    rng=random.Random(20261025)
    cases=[dict(id='long_nominal',steps=6,friction=.6,stride=.06,push=0.),
           dict(id='long_push',steps=6,friction=.5,stride=.06,push=-8.)]
    for i in range(20):
        cases.append(dict(id=f'new_context_{i+1:02d}',steps=2,
                          friction=round(rng.uniform(.35,.8),4),
                          stride=round(rng.uniform(.045,.075),5),push=round(rng.uniform(-10,10),3)))
    p=dict(schema='nasuraya.balance-transfer/1',seed=20261025,cases=cases,
           frozen_at_utc=datetime.now(timezone.utc).isoformat(),primary_protocol_sha256=digest(primary),
           runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           purpose='secondary fixed-policy transfer, no retuning or replacement of primary criteria',
           metrics=['completed steps','pass and settle','RMS and maximum tilt','stance slide'],
           limitations='deterministic synthetic samples, not independent real-world validation')
    write_json(folder/'secondary-protocol.json',p)


def load_policy(folder):
    p=read_plan(folder);raw=(Path(folder)/'policy.json').read_bytes();policy=json.loads(raw)
    rows=[json.loads((Path(folder)/f'train-{c["id"]}-{b:+.3f}.json').read_text())
          for b in p['candidates_m'] for c in p['training']]
    if policy!=select_policy(p,rows):raise ValueError('training-bound policy required')
    return policy,raw


def run_case(folder,case,bias):
    name=f'secondary-{case["id"]}-{bias:+.3f}'
    path=Path(folder)/(name+'.json')
    if path.exists():
        r=json.loads(path.read_text())
        if r['case']!=case or r['bias_m']!=bias:raise ValueError('secondary case mismatch')
        return r
    start=time.monotonic();args={k:v for k,v in case.items() if k!='id'}
    r=walk_trial(label=name,model_dir=CANDIDATE,geometry_support=True,com_bias_x_m=bias,**args)
    trace=r.pop('trace');blob=gzip.compress(json.dumps(trace,separators=(',',':')).encode(),mtime=0)
    (Path(folder)/(name+'-trace.json.gz')).write_bytes(blob)
    row=dict(case=case,bias_m=bias,result=r,wall_seconds=time.monotonic()-start,
             trace_sha256=hashlib.sha256(blob).hexdigest(),completed_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(path,row)
    print(json.dumps(dict(case=case['id'],bias_m=bias,steps=r['accepted_steps'],
                         requested=case['steps'],pass_settled=r['walk_pass'] and r['final_max_generalized_speed']<.05,
                         rms=r['tilt_rms_deg'],max_tilt=r['max_tilt_deg'],failure=r['failure'],
                         wall_seconds=row['wall_seconds'])),flush=True)
    return row


def run(folder):
    folder=Path(folder);p=json.loads((folder/'secondary-protocol.json').read_text());primary=read_plan(folder)
    if (p['primary_protocol_sha256']!=digest(primary)
            or p['runner_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError('secondary protocol/source drift')
    policy,raw=load_policy(folder);bias=policy['selected_bias_m'];pairs=[]
    for case in p['cases']:
        b=run_case(folder,case,0.)['result']
        c=b if bias==0 else run_case(folder,case,bias)['result']
        pairs.append(dict(case=case['id'],requested_steps=case['steps'],
            baseline_pass=bool(b['walk_pass'] and b['final_max_generalized_speed']<.05),
            candidate_pass=bool(c['walk_pass'] and c['final_max_generalized_speed']<.05),
            baseline_steps=b['accepted_steps'],candidate_steps=c['accepted_steps'],
            baseline_rms=b['tilt_rms_deg'],candidate_rms=c['tilt_rms_deg'],
            baseline_max=b['max_tilt_deg'],candidate_max=c['max_tilt_deg'],
            baseline_seconds=b['simulated_seconds'],candidate_seconds=c['simulated_seconds']))
        if (folder/'policy.json').read_bytes()!=raw:raise RuntimeError('policy changed')
    report=dict(schema=p['schema'],protocol_sha256=digest(p),policy_sha256=hashlib.sha256(raw).hexdigest(),
                selected_bias_m=bias,pairs=pairs,used_for_tuning=False,native_apply_allowed=False)
    write_json(folder/'secondary-evaluation.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('phase',choices=['freeze','run'])
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    {'freeze':freeze,'run':run}[a.phase](a.output)
