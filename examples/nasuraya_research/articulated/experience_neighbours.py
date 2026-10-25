"""Second prospective round: conservative memory of paired walking experience.

V01's failures remain failures. This round trains on its three training contexts
and twenty secondary contexts, then uses a NEW frozen validation set. Only known
friction and planned stride are policy inputs; future pushes are not inputs.
"""
import argparse
from datetime import datetime,timezone
import hashlib,json,math,random
from pathlib import Path
from .checkpoint import digest
from .experience_balance import eligible,read_plan,run_one,write_json


def recommend(memory,case,settings):
    k,radius,minimum_gain=settings
    ordered=sorted(memory,key=lambda r:(math.hypot((r['case']['friction']-case['friction'])/.45,
                       (r['case']['stride']-case['stride'])/.03),r['case']['id']))
    neighbours=ordered[:k]
    if len(neighbours)<k:return 0.
    for row in neighbours:
        distance=math.hypot((row['case']['friction']-case['friction'])/.45,
                            (row['case']['stride']-case['stride'])/.03)
        if distance>radius or not row['candidate_eligible'] or row['reduction']<minimum_gain:return 0.
    return .006


def choose_settings(memory,grid):
    scores=[]
    for settings in grid:
        gains=[];safe=True;selected_count=0
        for row in memory:
            train=[r for r in memory if r['case']['id']!=row['case']['id']]
            selected=recommend(train,row['case'],settings)!=0
            selected_count+=int(selected)
            safe=safe and (not selected or row['candidate_eligible'])
            gains.append(row['reduction'] if selected else 0.)
        reduction=1-math.exp(sum(math.log1p(-g) for g in gains)/len(gains))
        scores.append(dict(settings=settings,cv_reduction=reduction,worst_case_reduction=min(gains),
                           selections=selected_count,all_selected_candidates_eligible=safe))
    admissible=[r for r in scores if r['all_selected_candidates_eligible'] and r['cv_reduction']>=.05 and r['worst_case_reduction']>=-.10]
    best=min(admissible,key=lambda r:(-r['cv_reduction'],-r['settings'][0],-r['settings'][2],r['settings'][1])) if admissible else None
    return best,scores


def freeze(source,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);primary=read_plan(source)
    secondary=json.loads((Path(source)/'secondary-protocol.json').read_text())
    rng=random.Random(20261026)
    cases=[dict(id=f'v02_unseen_{i+1:02d}',friction=round(rng.uniform(.35,.8),4),
                stride=round(rng.uniform(.045,.075),5),push=round(rng.uniform(-10,10),3)) for i in range(12)]
    grid=[[k,radius,gain] for k in (2,3,5) for radius in (.2,.35,.5) for gain in (.1,.2)]
    p=dict(schema='nasuraya.balance-neighbours/1',frozen_at_utc=datetime.now(timezone.utc).isoformat(),
           primary_protocol_sha256=digest(primary),secondary_protocol_sha256=digest(secondary),
           source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),validation_cases=cases,
           seed=20261026,grid=grid,training_cases=[c['id'] for c in primary['training']]+[c['id'] for c in secondary['cases'] if c['steps']==2],
           known_prior_evidence='V01 fixed and friction-only policies regress on unseen rightward push; V01 remains unsuccessful',
           inputs=['known friction','planned stride'],excluded_input='future push',
           rule='unanimous qualifying nearest neighbours, otherwise zero; select settings only by leave-one-context-out training scores',
           minimum_cv_reduction=.05,maximum_cv_case_regression=.10,
           validation_criterion='all pass, geometric mean reduction >=5%, no case regression >10%',
           native_apply_allowed=False)
    write_json(folder/'protocol.json',p);print(json.dumps(p),flush=True)


def read_protocol(source,folder):
    p=json.loads((Path(folder)/'protocol.json').read_text())
    if (p['source_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            or p['primary_protocol_sha256']!=digest(read_plan(source))):raise ValueError('source drift')
    return p


def train(source,folder):
    source=Path(source);folder=Path(folder);p=read_protocol(source,folder);memory=[]
    for name in p['training_cases']:
        prefix='train' if name.startswith('train_') else 'secondary'
        rows=[json.loads((source/f'{prefix}-{name}-{b:+.3f}.json').read_text()) for b in (0.,.006)]
        b,c=[r['result'] for r in rows]
        if rows[0]['case']!=rows[1]['case'] or not eligible(b):raise ValueError('invalid paired baseline')
        memory.append(dict(case=rows[0]['case'],baseline_rms=b['tilt_rms_deg'],candidate_rms=c['tilt_rms_deg'],
            candidate_eligible=eligible(c) and c['simulated_seconds']<=b['simulated_seconds']+.1,
            reduction=1-c['tilt_rms_deg']/b['tilt_rms_deg'],record_hashes=[digest(r) for r in rows]))
    best,scores=choose_settings(memory,p['grid'])
    result=dict(schema=p['schema'],protocol_sha256=digest(p),memory=memory,cv_scores=scores,
                selected_settings=best['settings'] if best else None,cv_result=best,
                training_pass=best is not None,native_apply_allowed=False,
                outcome='validation eligible' if best else 'no training-qualified improvement; keep baseline')
    write_json(folder/'policy.json',result);print(json.dumps(result),flush=True)


def evaluate(source,folder):
    folder=Path(folder);p=read_protocol(source,folder);raw=(folder/'policy.json').read_bytes();policy=json.loads(raw)
    if policy['protocol_sha256']!=digest(p):raise ValueError('policy drift')
    best,scores=choose_settings(policy['memory'],p['grid'])
    if policy['cv_scores']!=scores or policy['selected_settings']!=(best['settings'] if best else None):raise ValueError('selection drift')
    if best is None:
        write_json(folder/'evaluation.json',dict(validation_run=False,success=False,
                    reason='Training gate failed; no new policy to validate',native_apply_allowed=False));return
    pairs=[]
    for case in p['validation_cases']:
        bias=recommend(policy['memory'],case,policy['selected_settings'])
        b=run_one(folder,case,0.,'validation')['result']
        c=b if bias==0 else run_one(folder,case,bias,'validation')['result']
        pairs.append(dict(case=case['id'],bias_m=bias,baseline_pass=eligible(b),candidate_pass=eligible(c),
                          baseline_rms=b['tilt_rms_deg'],candidate_rms=c['tilt_rms_deg'],
                          reduction=1-c['tilt_rms_deg']/b['tilt_rms_deg']))
    gain=1-math.exp(sum(math.log1p(-r['reduction']) for r in pairs)/len(pairs))
    success=all(r['baseline_pass'] and r['candidate_pass'] for r in pairs) and gain>=.05 and min(r['reduction'] for r in pairs)>=-.10
    if (folder/'policy.json').read_bytes()!=raw:raise ValueError('policy changed')
    write_json(folder/'evaluation.json',dict(validation_run=True,pairs=pairs,geometric_mean_reduction=gain,
                success=success,native_apply_allowed=False,original_v01_result_replaced=False))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('phase',choices=['freeze','train','evaluate'])
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    {'freeze':freeze,'train':train,'evaluate':evaluate}[a.phase](a.source,a.output)
