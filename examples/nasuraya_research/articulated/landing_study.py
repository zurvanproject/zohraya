"""Create-only, source-bound landing experiment with untouched holdouts.

Freeze once; run each named case/variant in a separate process; summarize all
rows including failures. No parameter search or automatic body promotion.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import time

import mujoco
import numpy as np
from .build import ROOT
from .canon_trial import CANDIDATE
from .experience_balance import write_json
from . import landing_settle

SCHEMA = 'nasuraya.landing-settle-study/1'
VARIANTS = {
    'baseline': dict(mode='unchanged', com_bias_x_m=0.),
    'prior6': dict(mode='unchanged', com_bias_x_m=.006),
    'landing6': dict(mode='landing', com_bias_x_m=.006),
    'tail6': dict(mode='tail', com_bias_x_m=.006),
    'tail0': dict(mode='tail', com_bias_x_m=0.),
    'combined6': dict(mode='combined', com_bias_x_m=.006),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    paths = [Path(__file__).with_name(n) for n in (
        'landing_study.py', 'landing_settle.py', 'stepping.py', 'balance.py',
        'support_geometry.py', 'evaluate.py', 'checkpoint.py', 'build.py', 'resize.py')]
    paths += [CANDIDATE/'nasuraya.xml', CANDIDATE/'robot.yaml']
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def runtime():
    return dict(python=platform.python_version(),
        packages={n:importlib.metadata.version(n) for n in ('mujoco','numpy','scipy','osqp','PyYAML')},
        blas={n:os.environ.get(n) for n in ('OPENBLAS_CORETYPE','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS')})


def frozen_plan():
    known = [dict(id='known_push', friction=.6, stride=.06, push=10., steps=2),
             dict(id='known_tail', friction=.3589, stride=.05475, push=-2.232, steps=2)]
    fresh = [dict(id='fresh_low_negative', friction=.38, stride=.058, push=-9., steps=2),
             dict(id='fresh_high_positive', friction=.72, stride=.065, push=11., steps=2),
             dict(id='fresh_long_negative', friction=.52, stride=.07, push=-7., steps=2),
             dict(id='fresh_half_dt', friction=.62, stride=.057, push=6., steps=2, dt=.0005),
             dict(id='fresh_six_low', friction=.46, stride=.06, push=0., steps=6),
             dict(id='fresh_six_negative', friction=.67, stride=.052, push=-10., steps=6)]
    return dict(schema=SCHEMA, frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        parent_commit='d07c8199d90004951c747e3b3197e60ca1de8bf9',
        sources_sha256=sources(), runtime=runtime(), variants=VARIANTS,
        diagnostics=known, holdouts=fresh, timing=1.,
        diagnostic_variants=list(VARIANTS), holdout_variants=['baseline','prior6','combined6'],
        candidate='combined6', no_parameter_search=True,
        evaluation=dict(settle_speed_limit=.05, maximum_extra_duration_s=.1,
            minimum_geometric_mean_reduction=.05, maximum_case_regression=.10,
            all_baselines_and_candidates_must_pass=True,
            candidate_must_pass_against_both_controls=True),
        terminal_change=dict(final_landing_bias_taper='quintic 6 mm -> 0 mm in existing 1 s landing',
            tail_task='50 * neutral_position_error - 20 * speed; weight ramps 0 -> 1',
            original_posture_task='50 * error - 12 * speed; unchanged weight 0.1'),
        unchanged=['body mass/model', 'torque/friction/pressure constraints', 'all physical guards',
            '2 s transfer / 3 s swing / 1 s landing per step', '3 s recenter / 2 s settle',
            '0.05 final speed ceiling including tail', 'external push waveform'],
        limitation='Deterministic, distinct simulator conditions; not independent biological subjects.',
        native_apply_allowed=False)


def freeze(folder):
    folder=Path(folder)
    if folder.resolve().is_relative_to((ROOT/'runtimes').resolve()):
        raise ValueError('native runtime destination forbidden')
    env=runtime()['blas']
    if env != dict(OPENBLAS_CORETYPE='SkylakeX',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'):
        raise ValueError('freeze requires original SkylakeX numerical kernel, one BLAS/OMP thread')
    folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/'protocol.json',frozen_plan())


def read_plan(folder):
    plan=json.loads((Path(folder)/'protocol.json').read_text())
    if plan['schema']!=SCHEMA or plan['sources_sha256']!=sources() or plan['runtime']!=runtime():
        raise ValueError('protocol/source/runtime drift')
    return plan


def joint_speeds(velocities):
    model,_=landing_settle.load(CANDIDATE)
    rows=[]
    for dof,speed in enumerate(velocities):
        j=int(np.searchsorted(model.jnt_dofadr,dof,side='right')-1)
        axis=int(dof-model.jnt_dofadr[j]);kind=int(model.jnt_type[j])
        unit='m/s' if kind==2 or (kind==0 and axis<3) else 'rad/s'
        rows.append(dict(joint=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,j),
                         axis=axis,dof=dof,speed=speed,unit=unit))
    return rows


def legacy_check(case,variant,result,trace):
    if case['id'] not in ('known_push','known_tail') or variant not in ('baseline','prior6'):
        return None
    stem=('holdout-holdout_push_right' if case['id']=='known_push' else 'secondary-new_context_10')
    stem += '-'+ ('+0.000' if variant=='baseline' else '+0.006')
    old=ROOT/'evidence/experience-balance-v01'
    record=json.loads((old/(stem+'.json')).read_text())
    ref=record['result']; shared=[k for k in ref if k!='label']
    ref_trace=json.loads(gzip.decompress((old/(stem+'-trace.json.gz')).read_bytes()))
    projection=[{k:row[k] for k in ref_trace[0]} for row in trace]
    return dict(source=str((old/(stem+'.json')).relative_to(ROOT)),
        shared_field_count=len(shared), all_shared_fields_identical=all(result[k]==ref[k] for k in shared),
        differing_fields=[k for k in shared if result[k]!=ref[k]],
        entire_original_trace_identical=projection==ref_trace)


def run_one(folder,case_id,variant):
    folder=Path(folder);plan=read_plan(folder)
    cases={c['id']:c for c in plan['diagnostics']+plan['holdouts']}
    if case_id not in cases:raise ValueError('unknown case')
    case=cases[case_id]
    split='diagnostics' if case in plan['diagnostics'] else 'holdouts'
    allowed=plan['diagnostic_variants' if split=='diagnostics' else 'holdout_variants']
    if variant not in allowed:raise ValueError('variant not allowed for split')
    stem=case_id+'--'+variant;dest=folder/(stem+'.json')
    if dest.exists() or (folder/(stem+'-trace.json.gz')).exists():
        raise FileExistsError('completed or partial run exists; preserve it and use a new folder')
    record=dict(case=case,variant=variant,split=split,protocol_sha256=sha(folder/'protocol.json'))
    started=time.monotonic()
    try:
        result=landing_settle.walk_trial(label=stem,**{k:v for k,v in case.items() if k!='id'},
                                        timing=plan['timing'],**plan['variants'][variant])
        trace=result.pop('trace')
        record['legacy_replay']=legacy_check(case,variant,result,trace)
        velocities=result.pop('final_qvel')
        record['final_joint_speeds']=joint_speeds(velocities)
        record['result']=result
        blob=gzip.compress(json.dumps(trace,separators=(',',':'),allow_nan=False).encode(),mtime=0)
        with (folder/(stem+'-trace.json.gz')).open('xb') as handle:handle.write(blob)
        record['trace_sha256']=hashlib.sha256(blob).hexdigest()
    except Exception as error:
        record['execution_error']=type(error).__name__+': '+str(error)
    record.update(wall_seconds=time.monotonic()-started,completed_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(dest,record)
    r=record.get('result',{})
    print(json.dumps(dict(case=case_id,variant=variant,steps=r.get('accepted_steps'),
        rms=r.get('tilt_rms_deg'),speed=r.get('final_max_generalized_speed'),
        failure=r.get('failure'),execution_error=record.get('execution_error'),
        legacy_replay=record.get('legacy_replay'),wall_seconds=record['wall_seconds'])),flush=True)
    return record


def eligible(row,case):
    r=row.get('result',{})
    return bool(not row.get('execution_error') and r.get('walk_pass')
        and r.get('accepted_steps')==case['steps'] and r.get('failure') is None
        and math.isfinite(r.get('final_max_generalized_speed',math.inf))
        and r['final_max_generalized_speed']<.05
        and math.isfinite(r.get('tilt_rms_deg',math.inf))
        and r['tilt_rms_deg']>0 and r['max_motor_torque_fraction']<=1.00000001)


def comparison(plan,records,control):
    rows=[]
    for case in plan['holdouts']:
        b=records[(case['id'],control)];c=records[(case['id'],plan['candidate'])]
        br=b.get('result',{});cr=c.get('result',{})
        comparable=(br.get('tilt_rms_deg',0)>0 and cr.get('tilt_rms_deg',0)>0)
        rows.append(dict(case=case['id'],baseline_pass=eligible(b,case),candidate_pass=eligible(c,case),
            baseline_rms=br.get('tilt_rms_deg'),candidate_rms=cr.get('tilt_rms_deg'),
            ratio=cr['tilt_rms_deg']/br['tilt_rms_deg'] if comparable else None,
            duration_pass=bool(comparable and cr['simulated_seconds']<=br['simulated_seconds']+.1),
            baseline_steps=br.get('accepted_steps'),candidate_steps=cr.get('accepted_steps'),
            baseline_speed=br.get('final_max_generalized_speed'),candidate_speed=cr.get('final_max_generalized_speed')))
    reduction=(1-math.exp(sum(math.log(x['ratio']) for x in rows)/len(rows))
               if all(x['ratio'] is not None for x in rows) else None)
    passed=bool(reduction is not None and reduction>=.05
        and all(x['baseline_pass'] and x['candidate_pass'] and x['duration_pass']
                and x['ratio']<=1.10 for x in rows))
    return dict(control=control,pairs=rows,geometric_mean_rms_reduction=reduction,performance_gate_pass=passed)


def summarize(folder):
    folder=Path(folder);plan=read_plan(folder);records={}
    for split,variant_key in (('diagnostics','diagnostic_variants'),('holdouts','holdout_variants')):
        for c in plan[split]:
            for v in plan[variant_key]:
                p=folder/(c['id']+'--'+v+'.json');r=json.loads(p.read_text())
                if r['protocol_sha256']!=sha(folder/'protocol.json') or r['case']!=c or r['variant']!=v or r['split']!=split:
                    raise ValueError('record identity drift')
                if 'result' in r:
                    tp=folder/(c['id']+'--'+v+'-trace.json.gz')
                    if sha(tp)!=r['trace_sha256']:raise ValueError('trace drift')
                records[(c['id'],v)]=r
    comparisons=[comparison(plan,records,c) for c in ('baseline','prior6')]
    failures=[]
    for (c,v),row in records.items():
        if not eligible(row,row['case']):
            failures.append(dict(case=c,variant=v,execution_error=row.get('execution_error'),
                failure=row.get('result',{}).get('failure'),
                final_speed=row.get('result',{}).get('final_max_generalized_speed')))
    replays=[r['legacy_replay'] for r in records.values() if r.get('legacy_replay')]
    exact=bool(len(replays)==4 and all(r['all_shared_fields_identical'] and r['entire_original_trace_identical'] for r in replays))
    success=bool(exact and all(c['performance_gate_pass'] for c in comparisons))
    summary=dict(schema=SCHEMA,protocol_sha256=sha(folder/'protocol.json'),rollouts=len(records),
        accepted_steps=sum(r.get('result',{}).get('accepted_steps',0) for r in records.values()),
        comparisons=comparisons,failures=failures,legacy_replays=replays,
        exact_legacy_replay_gate=exact,performance_gate_pass=success,
        promotion_allowed=False,native_apply_allowed=False,
        reason='independent performance gate failed' if not success else 'performance passed; native integration remains separate and unimplemented')
    write_json(folder/'promotion-decision.json',summary)
    print(json.dumps(summary,indent=2),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['freeze','run','summarize'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case');p.add_argument('--variant')
    args=p.parse_args()
    if args.action=='freeze':freeze(args.output)
    elif args.action=='run':run_one(args.output,args.case,args.variant)
    else:summarize(args.output)
