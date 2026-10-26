"""Frozen native paired survey and outcome-independent full-route followup."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import itertools
import json
import os
from pathlib import Path
from unittest.mock import patch

from .decision_relevance import assess,verify,sources
from .route_trial import RouteTrial
from .run_route_trial import summary
from .energy import EnergyCalibration
from .evaluate import fixture,prepare_defaults
from . import planning as base
from extension_state import attach
from motion_goal import MotionGoal
from persistent_embodiment_v1 import atomic_json
from unified_body_v2 import UnifiedBody


def cases(protocol):
    return [dict(id=f'case-{i:02d}',fatigue=f,sleep_pressure=s,direction=d)
        for i,(f,s,d) in enumerate(itertools.product(protocol['initial_channel_fatigue'],
            protocol['initial_sleep_pressure'],protocol['directions']))]


def make_goal(case):
    f=case['fatigue']
    if not isinstance(f,(int,float)) or isinstance(f,bool) or not 0<=f<=1:raise ValueError('fixture fatigue')
    body=fixture(case['sleep_pressure']);before=body.owner.body()
    state=body.owner.owner.body.state
    state.fatigue={k:float(f) for k in state.fatigue}
    body.owner._record(before,body.owner.body(),'external_input',
        'declared synthetic initial channel fatigue; not accumulated work, not a reset of saved user state',0.)
    attach(body,dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=dict(L=[],R=[]),cursor_semantics='confirmed'))
    label='-'+case['execution_epoch'] if case.get('execution_epoch') else ''
    goal=MotionGoal.start(body,case['direction'],'decision-'+case['id']+label)
    for _ in range(6):
        if goal.task['status']!='running':break
        goal.step()
    # Validate complete persistence before either trial policy can inspect it.
    return MotionGoal.restore(goal.checkpoint())


def advance(goal,count,out):
    halt=out/'halt.json'
    if halt.exists():
        saved=json.loads(halt.read_text())
        if saved['goal_sha256']!=goal.goal.checkpoint()['sha256']:raise ValueError('stale safe halt')
        return True
    for _ in range(count):
        if goal.session['status']!='running':break
        before=goal.session['records'][-1]['after_goal_sha'] if goal.session['records'] else goal.session['initial_goal_sha']
        try:d=goal.prepare()
        except base.NoSafeChoice as e:
            # Preparation uses private projections. A refusal must leave the
            # authoritative owner unchanged and must never cause a native retry.
            if goal.goal.checkpoint()['sha256']!=before:raise ValueError('safe refusal changed the owner')
            atomic_json(halt,dict(kind='no_safe_choice',reason=str(e),goal_sha256=before,
                recorded_owner_ticks=len(goal.session['records']),native_action_executed=False))
            return True
        if d['offset']==0:
            a=assess(d['plan'],base.counts(goal.session['records']),goal.model,goal.session['mode'])
            with (out/'assessments.jsonl').open('a') as log:
                log.write(json.dumps(a,allow_nan=False)+'\n');log.flush();os.fsync(log.fileno())
        goal.step()
    return False


def trial_summary(trial):
    if trial.session['records']:return summary(trial)
    initial=trial.session['initial'];final=base.state(trial.goal)
    return dict(mode=trial.session['mode'],initial=initial,final=final,goal_status=trial.task['status'],
        owner_ticks=0,fuel_used_J=0.,new_landings=0,confirmed_landings=trial.task['landings'],
        counts=trial.task['counts'],remaining_ticks=230-final['elapsed'],requested={},actual={},
        all_receipts_valid=True,measured_receipts=0,raw_fuel_mae_J=None,active_fuel_mae_J=None,
        final_goal_sha256=trial.goal.checkpoint()['sha256'],final_trial_sha256=trial.checkpoint()['sha256'],
        model_sha256=trial.model.checkpoint()['sha256'],official_state_advanced=False,model_api_calls=0)


def screen_case(args):
    case,output,model_path,ticks=args;out=Path(output)/case['id'];out.mkdir(exist_ok=False)
    goal=make_goal({**case,'execution_epoch':Path(output).name});initial=goal.checkpoint();atomic_json(out/'initial_goal.json',initial)
    if goal.task['status']!='running':
        result=dict(case=case,initial_goal_sha256=initial['sha256'],fixture_unavailable=True,
            status=goal.task['status'],requests_differ=False,first_requested_difference=None,
            initial=base.state(goal),arms={})
        atomic_json(out/'screen.json',result);return result
    model=EnergyCalibration.restore(json.loads(Path(model_path).read_text()));frozen=model.checkpoint()
    result=dict(case=case,initial_goal_sha256=initial['sha256'],arms={})
    for mode in ('old','calibrated'):
        arm=out/mode;arm.mkdir()
        trial=RouteTrial.start(MotionGoal.restore(initial),mode,EnergyCalibration.restore(frozen),dict(counts={},pending=[],episodes=0,last=None))
        halted=advance(trial,ticks,arm);assert trial.model.checkpoint()==frozen
        atomic_json(arm/'screen_trial.json',trial.checkpoint());s=trial_summary(trial);atomic_json(arm/'screen_summary.json',s)
        result['arms'][mode]=dict(summary=s,halted_no_safe_choice=halted,requested=[r['decision']['request']['requested'] for r in trial.session['records']])
    a=result['arms']['old'];b=result['arms']['calibrated']
    result['requests_differ']=a['requested']!=b['requested']
    result['first_requested_difference']=next((i+1 for i,(x,y) in enumerate(itertools.zip_longest(a['requested'],b['requested'])) if x!=y),None)
    result['screen_is_efficiency_claim']=False
    atomic_json(out/'screen.json',result)
    return result


def pause(goal,ticks):
    rows=[]
    for _ in range(ticks):
        if goal.task['status']!='running':break
        request=goal.request();request['requested']='slow_breath';before=goal.checkpoint()['sha256']
        receipt=base.advance_motion(goal,request)
        rows.append(dict(before_goal_sha256=before,request=request,receipt=receipt,after_goal_sha256=goal.checkpoint()['sha256']))
    return rows


def comparable(a,b,target):
    return all(s['final']['landings']==target and s['final']['minimum']['posture']=='double_support' and
        s['all_receipts_valid'] and s['grounded'] and not s['swing_active'] for s in (a,b)) and a['feet_m']==b['feet_m']


def followup_case(args):
    case_id,output,protocol=args;out=Path(output)/case_id;result=dict(case_id=case_id,arms={})
    for mode in ('old','calibrated'):
        arm=out/mode;trial=RouteTrial.restore(json.loads((arm/'screen_trial.json').read_text()))
        while (trial.session['status']=='running' and len(trial.task['landings'])<protocol['followup_landings'] and
               len(trial.session['records'])<min(protocol['followup_policy_tick_limit'],trial.session['max_ticks'])):
            if advance(trial,1,arm):break
        atomic_json(arm/'final_trial.json',trial.checkpoint());policy_summary=trial_summary(trial)
        paused=MotionGoal.restore(trial.goal.checkpoint());rows=[] if (arm/'halt.json').exists() else pause(paused,protocol['pause_ticks'])
        atomic_json(arm/'pause_receipts.json',rows);atomic_json(arm/'paused_goal.json',paused.checkpoint())
        p=paused.body.owner.physical;final=base.state(paused)
        result['arms'][mode]=dict(policy_summary=policy_summary,final=final,
            total_owner_ticks=final['elapsed']-trial.session['initial']['elapsed'],
            fuel_used_J=trial.session['initial']['fuel_J']-final['fuel_J'],feet_m=deepcopy(p.state.feet_m),
            grounded=all(x[2]==0. for x in p.state.feet_m.values()),swing_active=p.state.swing is not None,
            all_receipts_valid=policy_summary['all_receipts_valid'] and all(r['receipt']['owner']['physical_model_valid'] for r in rows),
            original_remaining_ticks=230-paused.task['elapsed'],pause_ticks=len(rows),final_goal_sha256=paused.checkpoint()['sha256'])
        atomic_json(arm/'final_summary.json',result['arms'][mode])
    a=result['arms']['old'];b=result['arms']['calibrated']
    match=comparable(a,b,protocol['followup_landings'])
    result.update(comparable_paused_endpoints=match,saved_fuel_J=a['fuel_used_J']-b['fuel_used_J'],saved_simulated_seconds=a['total_owner_ticks']-b['total_owner_ticks'])
    result['calibrated_dominates']=match and result['saved_fuel_J']>=0 and result['saved_simulated_seconds']>=0 and (result['saved_fuel_J']>0 or result['saved_simulated_seconds']>0)
    atomic_json(out/'followup.json',result);return result


def choose_followups(screen,limit):
    if type(limit) is not int or limit<0:raise ValueError('followup limit')
    return [x['case']['id'] for x in screen if x['requests_differ']][:limit]


def run(output,model_path,workers):
    out=Path(output).resolve();out.mkdir(exist_ok=False,parents=True)
    path=Path(__file__).with_name('decision_survey_protocol.json');protocol=json.loads(path.read_text());cohort=cases(protocol)
    model_path=Path(model_path).resolve();model_file_sha=hashlib.sha256(model_path.read_bytes()).hexdigest()
    model=EnergyCalibration.restore(json.loads(model_path.read_text()))
    frozen_sources=sources();driver_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();protocol_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    atomic_json(out/'frozen_protocol.json',dict(protocol=protocol,cases=cohort,execution_epoch=out.name,sources=frozen_sources,
        driver_sha256=driver_sha,
        protocol_sha256=protocol_sha,model_sha256=model.checkpoint()['sha256'],model_file_sha256=model_file_sha))
    prepare_defaults();screen=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(screen_case,[(c,str(out),str(model_path),protocol['screen_ticks_per_arm']) for c in cohort]):
            screen.append(row);print(json.dumps(dict(case=row['case']['id'],diverged=row['requests_differ'],first=row['first_requested_difference'],
                fixture_unavailable=row.get('fixture_unavailable',False),
                landings={k:v['summary']['final']['landings'] for k,v in row['arms'].items()})),flush=True)
        selected=choose_followups(screen,protocol['followup_max_cases']);atomic_json(out/'selected_followups.json',selected)
        followups=[]
        for row in pool.map(followup_case,[(c,str(out),protocol) for c in selected]):
            followups.append(row);print(json.dumps(dict(followup=row['case_id'],comparable=row['comparable_paused_endpoints'],saved_fuel_J=row['saved_fuel_J'],saved_s=row['saved_simulated_seconds'])),flush=True)
    assert hashlib.sha256(model_path.read_bytes()).hexdigest()==model_file_sha
    assert sources()==frozen_sources and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==driver_sha
    assert hashlib.sha256(path.read_bytes()).hexdigest()==protocol_sha
    result=dict(schema=protocol['schema'],cases=len(cohort),screen=screen,followups=followups,selected_followups=selected,
        divergent_cases=sum(r['requests_differ'] for r in screen),followup_wins=sum(r['calibrated_dominates'] for r in followups),
        model_unchanged=True,policy_parameters_unchanged=True,official_state_advanced=False,model_api_calls=0,
        scope=protocol['scope'])
    atomic_json(out/'survey.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('screen','followups')},indent=2),flush=True)


def audit(output,model_path):
    """Validate every saved pre-action assessment in a fresh read-only process."""
    out=Path(output);contract=json.loads((out/'frozen_protocol.json').read_text())
    assert contract['sources']==sources()
    assert contract['driver_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert contract['protocol_sha256']==hashlib.sha256(Path(__file__).with_name('decision_survey_protocol.json').read_bytes()).hexdigest()
    model=EnergyCalibration.restore(json.loads(Path(model_path).read_text()))
    assert model.checkpoint()['sha256']==contract['model_sha256']
    survey=json.loads((out/'survey.json').read_text())
    assert survey['selected_followups']==choose_followups(survey['screen'],contract['protocol']['followup_max_cases'])
    n=0;changed=0;guarded=0;unseen=0;actual_ticks=0;safe_halts=0;traces=set()
    with patch.object(UnifiedBody,'cycle',side_effect=AssertionError('native execution during audit')), \
         patch.object(base,'rollout',side_effect=AssertionError('forecast during audit')):
        for case in contract['cases']:
            directory=out/case['id'];initial=MotionGoal.restore(json.loads((directory/'initial_goal.json').read_text()))
            screen=json.loads((directory/'screen.json').read_text())
            assert initial.checkpoint()['sha256']==screen['initial_goal_sha256']
            if screen.get('fixture_unavailable'):continue
            for mode in ('old','calibrated'):
                arm=directory/mode;followed=case['id'] in survey['selected_followups']
                trial=RouteTrial.restore(json.loads((arm/('final_trial.json' if followed else 'screen_trial.json')).read_text()))
                assert trial.session['initial_goal_sha']==initial.checkpoint()['sha256'] and trial.model.checkpoint()==model.checkpoint()
                rows=trial.session['records'];plans=[(i,r['decision']['plan']) for i,r in enumerate(rows) if r['decision']['offset']==0]
                if (arm/'halt.json').exists():
                    halted=json.loads((arm/'halt.json').read_text())
                    assert halted['goal_sha256']==trial.goal.checkpoint()['sha256'] and not halted['native_action_executed']
                    safe_halts+=1
                evidence=[json.loads(line) for line in (arm/'assessments.jsonl').read_text().splitlines()] if (arm/'assessments.jsonl').exists() else []
                assert len(evidence)==len(plans)
                for item,(i,plan) in zip(evidence,plans):
                    verify(item,plan,base.counts(rows[:i]),model,mode);p=item['payload']
                    n+=1;changed+=p['choice_changed'];guarded+=p['selection_constraint']=='current_body_need'
                    unseen+=sum(v['unseen_steps'] for v in p['coverage'].values())
                if rows:traces.add(base.digest([(r['decision']['request']['requested'],r['receipt']['owner']['selected_action'],
                    r['after']['fuel_J'],r['after']['minimum']['fatigue'],r['after']['landings']) for r in rows]))
                actual_ticks+=len(rows)
                if followed:
                    paused=MotionGoal.restore(json.loads((arm/'paused_goal.json').read_text()))
                    receipts=json.loads((arm/'pause_receipts.json').read_text());head=trial.goal.checkpoint()['sha256']
                    for row in receipts:
                        assert row['before_goal_sha256']==head and row['request']['requested']=='slow_breath'
                        assert paused.body.results[row['request']['event_id']]==row['receipt']
                        assert row['receipt']['owner']['physical_model_valid'];head=row['after_goal_sha256']
                    assert head==paused.checkpoint()['sha256']
                    assert paused.task['plan']==trial.task['plan'] and paused.task['elapsed']==trial.task['elapsed']+len(receipts)
                    actual_ticks+=len(receipts)
    result=dict(assessments_verified=n,choice_relevant_assessments=changed,body_need_determined_assessments=guarded,
        unseen_context_forecast_steps=unseen,distinct_executed_traces=len(traces),measured_owner_ticks=actual_ticks,
        safe_halted_arms=safe_halts,cold_audit_valid=True,native_actions_executed=0,new_forecasts_executed=0)
    atomic_json(out/'audit.json',result);print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--model',required=True)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--audit',action='store_true');args=p.parse_args()
    if args.audit:audit(args.output,args.model)
    else:run(args.output,args.model,args.workers)
