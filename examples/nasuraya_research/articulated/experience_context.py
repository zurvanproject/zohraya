"""Training-derived friction lookup, frozen before any held-out outcome.

This secondary hypothesis uses the known simulator friction, not an inferred
surface estimate. It cannot replace the primary constant-policy criterion.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from .checkpoint import digest
from .experience_balance import eligible, read_plan, run_one, select_policy, write_json
from .experience_stress import run_case


def training_records(folder, plan):
    return [json.loads((Path(folder)/f'train-{c["id"]}-{b:+.3f}.json').read_text())
            for b in plan['candidates_m'] for c in plan['training']]


def select_memory(plan, records):
    # Apply the primary grid identity/completeness checks before reading scores.
    select_policy(plan, records)
    memory=[]
    for case in plan['training']:
        rows=[r for r in records if r['case']==case]
        baseline=next(r for r in rows if r['bias_m']==0.)
        candidates=[r for r in rows if eligible(r['result']) and
                    r['result']['simulated_seconds'] <= baseline['result']['simulated_seconds']+.1]
        best=min(candidates,key=lambda r:(r['result']['tilt_rms_deg'],abs(r['bias_m']),r['bias_m']))
        gain=1-best['result']['tilt_rms_deg']/baseline['result']['tilt_rms_deg']
        chosen=best['bias_m'] if gain>=plan['selection']['minimum_training_reduction'] else 0.
        memory.append(dict(training_case=case['id'],friction=case['friction'],bias_m=chosen,
                           training_reduction=gain))
    return sorted(memory,key=lambda r:(r['friction'],r['training_case']))


def choose(memory, friction):
    if type(friction) not in (int,float) or not math.isfinite(friction) or friction<=0:
        raise ValueError('positive finite known friction required')
    # Fixed nearest-neighbour lookup; a tie uses the lower-friction experience.
    return min(memory,key=lambda r:(abs(r['friction']-friction),r['friction'],r['training_case']))['bias_m']


def freeze(folder):
    folder=Path(folder);plan=read_plan(folder);records=training_records(folder,plan)
    if any(folder.glob('holdout-*.json')) or any(folder.glob('secondary-*-+*.json')):
        raise ValueError('context hypothesis must precede held-out measurement')
    report=dict(schema='nasuraya.balance-context/1',frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                primary_protocol_sha256=digest(plan),training_observations_sha256=digest(records),
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                memory=select_memory(plan,records),
                rule='nearest training friction, ties lower friction; baseline if training gain <5%',
                origin='training revealed opposite effects at friction 0.45 and 0.60',
                status='secondary hypothesis; does not replace the original primary criterion',
                criteria=plan['evaluation'],native_apply_allowed=False,
                limitations=['known simulator friction, no learned or measured friction estimator',
                             'three training contexts; no neural weights or online adaptation'])
    write_json(folder/'context-protocol.json',report)
    print(json.dumps(report),flush=True)


def run(folder):
    folder=Path(folder);plan=read_plan(folder);records=training_records(folder,plan)
    path=folder/'context-protocol.json';raw=path.read_bytes();p=json.loads(raw)
    if (p['primary_protocol_sha256']!=digest(plan)
            or p['training_observations_sha256']!=digest(records)
            or p['memory']!=select_memory(plan,records)
            or p['runner_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError('context plan, training or source drift')
    secondary=json.loads((folder/'secondary-protocol.json').read_text())
    pairs=[]
    for split,cases in [('holdout',plan['holdouts']),('secondary',secondary['cases'])]:
        for case in cases:
            bias=choose(p['memory'],case['friction'])
            if split=='holdout':
                b=run_one(folder,case,0.,split)['result']
                c=b if bias==0 else run_one(folder,case,bias,split)['result']
            else:
                b=run_case(folder,case,0.)['result']
                c=b if bias==0 else run_case(folder,case,bias)['result']
            pairs.append(dict(case=case['id'],split=split,friction=case['friction'],bias_m=bias,
                baseline_pass=bool(b['walk_pass'] and b['final_max_generalized_speed']<.05),
                candidate_pass=bool(c['walk_pass'] and c['final_max_generalized_speed']<.05),
                baseline_steps=b['accepted_steps'],candidate_steps=c['accepted_steps'],
                baseline_rms=b['tilt_rms_deg'],candidate_rms=c['tilt_rms_deg'],
                baseline_max=b['max_tilt_deg'],candidate_max=c['max_tilt_deg'],
                reduction=1-c['tilt_rms_deg']/b['tilt_rms_deg']))
    primary=[r for r in pairs if r['split']=='holdout']
    reduction=1-math.exp(sum(math.log(r['candidate_rms']/r['baseline_rms']) for r in primary)/len(primary))
    passed=(all(r['baseline_pass'] and r['candidate_pass'] for r in primary)
            and reduction>=p['criteria']['minimum_geometric_mean_reduction']
            and min(r['reduction'] for r in primary)>=-p['criteria']['maximum_case_regression'])
    if path.read_bytes()!=raw:raise RuntimeError('context policy changed during evaluation')
    report=dict(schema=p['schema'],protocol_sha256=hashlib.sha256(raw).hexdigest(),pairs=pairs,
                six_case_geometric_mean_reduction=reduction,secondary_hypothesis_pass=passed,
                replaces_primary_result=False,retuned_on_holdouts=False,native_apply_allowed=False)
    write_json(folder/'context-evaluation.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('phase',choices=['freeze','run'])
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    {'freeze':freeze,'run':run}[a.phase](a.output)
