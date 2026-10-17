"""Evidence about whether a frozen energy estimate changes my next choice.

This diagnostic neither learns nor executes. It preserves costs, choices and
coverage separately; a changed score alone is not recorded as behavioral benefit.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from . import planning as base
from .energy import features,score as calibrated_score,POLICY as ENERGY_POLICY
from .route_trial import selection,sources as trial_sources
from .monitor import digest

SCHEMA='nasuraya-decision-relevance/1'


def sources():
    return {**trial_sources(),'decision_relevance.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def assess(plan,spent,model,mode):
    if model.stage!='frozen':raise ValueError('frozen calibration required')
    initial=plan['initial'];learning=plan['calibration'];candidates=plan['candidates']
    old,old_reason=selection('old',initial['goal_phase'],initial,candidates,learning,spent,model)
    new,new_reason=selection('calibrated',initial['goal_phase'],initial,candidates,learning,spent,model)
    if mode not in ('old','calibrated') or plan['chosen']!={'old':old,'calibrated':new}[mode]:
        raise ValueError('assessment differs from executing policy')
    coverage={};scores={}
    for name,c in candidates.items():
        prior=initial;corrected=0;unseen=0;sparse=0;withheld=0
        for i,step in enumerate(c['series']):
            f=features(prior,step,i);key=digest(f)
            n=len(model.training.get(key,[]));v=model.validation.get(key,dict(n=0))
            enough=n>=ENERGY_POLICY['min_train'] and v['n']>=ENERGY_POLICY['min_validation']
            corrected+=model.correction(f)!=0.;unseen+=n==0;sparse+=n>0 and not enough
            withheld+=enough and not v['corrected']<(1.-ENERGY_POLICY['required_gain'])*v['raw']
            prior=step
        coverage[name]=dict(steps=len(c['series']),corrected_steps=corrected,
            unseen_steps=unseen,insufficient_evidence_steps=sparse,withheld_by_validation_steps=withheld)
        scores[name]=dict(old=base.score(c,learning),calibrated=calibrated_score(c,initial,model,learning))
    changed_cost=any(abs(s['old']-s['calibrated'])>1e-9 for s in scores.values())
    reason='choice_changed' if old!=new else 'cost_changed_choice_unchanged' if changed_cost else 'no_cost_or_choice_change'
    p=dict(schema=SCHEMA,sources=sources(),origin_goal_sha=plan['origin_goal_sha'],mode=mode,
        model_sha256=model.checkpoint()['sha256'],spent=deepcopy(spent),old_choice=old,calibrated_choice=new,
        old_reason=old_reason,calibrated_reason=new_reason,cost_changed=changed_cost,choice_changed=old!=new,
        selection_constraint='required_goal_phase' if initial['goal_phase']!='route' else
            'current_body_need' if old_reason=='current body need before route progress' else 'cost_ranking_with_native_guards',
        classification=reason,scores=scores,coverage=coverage,
        claim='prospective decision diagnostic; executed benefit is unmeasured here')
    return dict(payload=p,sha256=digest(p))


def verify(envelope,plan,spent,model,mode):
    if envelope!=assess(plan,spent,model,mode):raise ValueError('decision relevance evidence mismatch')
    return True
