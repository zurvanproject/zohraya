"""Frozen 2x2x2 synthetic ablation; proposer is deterministic, NOT an LLM."""
from itertools import product
import json
from pathlib import Path
import sqlite3

from .host import BodyLoop
from .api_host import BodyAPIHost
from .experience import packet

CASES=(('sleep_verified_veto','sleep','walk',True),('normal_success','normal','walk',True),
       ('sleep_no_veto_history','sleep','observe',True),('sleep_unverified_veto','sleep','walk',False))
AXES=('input_experience','fixed_rules','core_feedback')


def propose(snapshot,experience,*,input_experience,fixed_rules):
    """Experimental controller only. Production model instructions are unchanged."""
    state=snapshot['minimum_state']
    if fixed_rules and (state['sleep_pressure']>.65 or state['fatigue']>.45):
        return 'observe','fixed_rule'
    if input_experience and any(r['preferred_action']=='walk' and not r['expected_outcome_matched']
                               for r in experience['records']):
        return 'observe','verified_prior_mismatch'
    return 'walk','experimental_default'


def invoke(host,name,label,args=None):
    r=host.handle_required('ablation-'+host.run_id,dict(type='function_call',name=name,
        arguments=args or {},call_id=label,turn_id='ablation-turn'))
    if not r['success']:raise RuntimeError('synthetic ablation tool rejected')
    return json.loads(r['output'])


def run(output_dir):
    root=Path(output_dir);root.mkdir(mode=0o700,parents=True,exist_ok=False)
    frozen=dict(schema='nasuraya-memory-ablation-design/1',cases=[dict(name=n,fixture=f,seed_action=a,
        feedback_verified=v) for n,f,a,v in CASES],axes=list(AXES),combinations=list(product((False,True),repeat=3)),
        proposer='declared deterministic surrogate; no real language model',
        metrics=['preferred_action','core_selected','body_actual','outcome_match','repeat_verified_veto'],
        live_api_requests=0)
    (root/'frozen-design.json').write_text(json.dumps(frozen,indent=2)+'\n')
    rows=[]
    for name,fixture,seed_action,verified in CASES:
        seed=root/(name+'-seed.sqlite')
        with BodyLoop.start(seed,fixture=fixture,max_actions=2) as loop:
            host=BodyAPIHost(loop,mode='bounded',target_cycles=1,max_calls=20,run_id='seed')
            before=invoke(host,'observe_body','observe');invoke(host,'evaluate_body','evaluate')
            first=invoke(host,'request_body_action','action',dict(action=seed_action,duration_s=.1,
                observed_checkpoint_sha256=before['checkpoint_sha256']))
            invoke(host,'evaluate_body','finish')
            if not verified:
                record=loop.engine.get(first['decision_id']);record['feedback']['verified']=False
                record['feedback']['reason']='declared unverified synthetic evaluation history'
                loop.engine.db.execute('UPDATE decisions SET record=? WHERE id=?',(json.dumps(record),record['id']))
                loop.engine.db.execute('DELETE FROM feedback_index WHERE decision_id=?',(record['id'],))
            checkpoint=host.snapshot()['checkpoint_sha256']
        for flags in product((False,True),repeat=3):
            setting=dict(zip(AXES,flags));path=root/(name+'-'+''.join(str(int(v)) for v in flags)+'.sqlite')
            with sqlite3.connect(seed) as src,sqlite3.connect(path) as dst:src.backup(dst)
            with BodyLoop(path) as loop:
                loop.engine.use_memory=setting['core_feedback']  # Evaluation fixture only.
                host=BodyAPIHost(loop,mode='bounded',target_cycles=1,max_calls=20,run_id='probe')
                assert host.snapshot()['checkpoint_sha256']==checkpoint
                observation=invoke(host,'observe_body','observe');experience=packet(host)
                action,reason=propose(observation,experience,input_experience=setting['input_experience'],
                                     fixed_rules=setting['fixed_rules'])
                invoke(host,'evaluate_body','evaluate')
                outcome=invoke(host,'request_body_action','action',dict(action=action,duration_s=.1,
                    observed_checkpoint_sha256=observation['checkpoint_sha256']))
                invoke(host,'evaluate_body','finish')
                record=loop.engine.get(outcome['decision_id'])
                rows.append(dict(case=name,**setting,opening_checkpoint_sha256=checkpoint,
                    preferred_action=action,proposal_reason=reason,core_selected=record['selected_action'],
                    body_actual=record['actual_outcome']['selected_action'],outcome_match=record['feedback']['success'],
                    repeat_verified_veto=verified and seed_action=='walk' and first['actual_action']!='walk' and action=='walk',
                    recalled_feedback_ids=record['recalled_feedback_ids'],goal_reached=host.evaluate()['goal_reached']))
    def compare(axis,**held):
        pairs=[]
        for case,*_ in CASES:
            a=next(r for r in rows if r['case']==case and not r[axis] and all(r[k]==v for k,v in held.items()))
            b=next(r for r in rows if r['case']==case and r[axis] and all(r[k]==v for k,v in held.items()))
            pairs.append(dict(case=case,without_match=a['outcome_match'],with_match=b['outcome_match'],
                preferred_changed=a['preferred_action']!=b['preferred_action'],core_changed=a['core_selected']!=b['core_selected']))
        return dict(axis=axis,held=held,pairs=pairs,improved=sum(not p['without_match'] and p['with_match'] for p in pairs),
                    worsened=sum(p['without_match'] and not p['with_match'] for p in pairs),
                    unchanged=sum(p['without_match']==p['with_match'] for p in pairs))
    summary=dict(schema='nasuraya-memory-ablation-results/1',conditions=len(rows),scenarios=len(CASES),
        generated_fixture=True,language_model_evaluated=False,api_requests=0,frozen_design=frozen,
        contrasts=[compare('input_experience',fixed_rules=False,core_feedback=False),
                   compare('input_experience',fixed_rules=True,core_feedback=False),
                   compare('core_feedback',input_experience=False,fixed_rules=False),
                   compare('fixed_rules',input_experience=False,core_feedback=False)],rows=rows,
        interpretation_limit='deterministic mechanism ablation; no statistical or causal claim about gpt-6-astra')
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('conditions','scenarios','language_model_evaluated','contrasts')}))
    return 0
