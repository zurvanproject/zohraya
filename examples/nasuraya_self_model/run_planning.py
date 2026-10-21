"""Bounded continuation of the existing route with a real process handoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .planning import PlanningGoal,PlanningJournal,state,score
from .monitor import ROOT,digest
from motion_goal import MotionGoal
from persistent_embodiment_v1 import atomic_json


def create(seed):
    return PlanningGoal.start(MotionGoal.restore(seed['goal']),seed['knowledge'],session_id='progress-planning-2026-10-15')


def summarize(goal):
    rows=goal.session['records'];learning,knowledge=goal.derived();eta=[x for r in rows for x in r['feedback']['settled_eta_errors']]
    def mae(key):return sum(abs(r['feedback'][key]) for r in rows)/len(rows) if rows else None
    return dict(schema='nasuraya-progress-planning-report/1',goal_id=goal.task['goal_id'],
        goal_status=goal.task['status'],session_status=goal.session['status'],
        initial=goal.session['initial'],final=state(goal.goal),owner_ticks=len(rows),
        actions=[r['decision']['request']['requested'] for r in rows],
        actual=[r['receipt']['owner']['selected_action'] for r in rows],
        valid_receipts=all(r['receipt']['owner']['physical_model_valid'] for r in rows),
        distinct_plans=sum(r['decision']['offset']==0 for r in rows),learning=learning,knowledge=knowledge,
        raw_fuel_mae_J=mae('fuel_error_J'),corrected_fuel_mae_J=mae('corrected_fuel_error_J'),
        raw_fatigue_mae=mae('fatigue_error'),corrected_fatigue_mae=mae('corrected_fatigue_error'),
        settled_eta_forecasts=len(eta),raw_eta_mae_s=sum(abs(x['error_s']) for x in eta)/len(eta) if eta else None,
        corrected_eta_mae_s=sum(abs(x['corrected_error_s']) for x in eta)/len(eta) if eta else None,
        eta_errors=eta,final_sha256=goal.checkpoint()['sha256'],pid=os.getpid(),
        official_state_advanced=False,live_model_api_calls=0,
        evaluation_scope='prequential errors on this one trajectory; overlapping ETA forecasts; not a held-out benchmark')


def worker(args):
    out=Path(args.output).resolve()
    if args.mode=='control':
        goal=create(json.loads(Path(args.seed).read_text()));journal=None
    else:
        journal=PlanningJournal(out/'session.sqlite');goal=journal.load()
    while goal.session['status']=='running':
        event=goal.goal.request()['event_id']
        if journal:
            head=goal.checkpoint()['sha256'];receipt=journal.step(event_id=event,expected_head=head,current_goal=goal)
        else:receipt=goal.step()
        row=goal.session['records'][-1];d=row['decision'];p=d['plan']
        print(json.dumps(dict(pid=os.getpid(),tick=len(goal.session['records']),requested=d['request']['requested'],
            actual=receipt['owner']['selected_action'],landings=len(goal.task['landings']),
            elapsed=goal.task['elapsed'],phase=goal.task['phase'],status=goal.task['status'],
            new_plan=d['offset']==0,plan_eta_s=p['candidates'][p['chosen']]['eta_s'],
            corrected_plan_score=score(p['candidates'][p['chosen']],p['calibration']),
            fuel_error_J=row['feedback']['fuel_error_J'],corrected_fuel_error_J=row['feedback']['corrected_fuel_error_J'])),flush=True)
        if journal and args.stop_landings and len(goal.task['landings'])>=args.stop_landings and goal.task['status']=='running':
            learning,knowledge=goal.derived()
            atomic_json(out/'handoff.json',dict(pid=os.getpid(),head=goal.checkpoint()['sha256'],
                ticks=len(goal.session['records']),state=state(goal.goal),learning=learning,knowledge_sha256=digest(knowledge)))
            os._exit(75)
    atomic_json(out/'final_session.json',goal.checkpoint());atomic_json(out/'summary.json',summarize(goal))
    print('FINAL',goal.task['status'],len(goal.task['landings']),goal.checkpoint()['sha256'],flush=True)


def start(args):
    out=Path(args.output).resolve();out.mkdir(exist_ok=False)
    path=Path(args.seed).resolve();source_sha=hashlib.sha256(path.read_bytes()).hexdigest();seed=json.loads(path.read_text())
    goal=create(seed);journal=PlanningJournal.create(out/'session.sqlite',goal)
    atomic_json(out/'protocol.json',dict(seed_sha256=source_sha,initial=state(goal.goal),
        max_ticks=goal.session['max_ticks'],stop_landings=12,original_goal_budget_refilled=False,
        forecast_scope='reduced owner kernel; same source, approximate outer coupling',
        parent_session_sha256=seed['prior_session_sha256']))
    command=[sys.executable,'-m','examples.nasuraya_self_model.run_planning','worker','--output',str(out)]
    with (out/'first_worker.log').open('w') as log:
        first=subprocess.run(command+['--stop-landings','12'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if first.returncode not in (0,75):raise RuntimeError('first worker failed; inspect its log')
    if first.returncode==75:
        with (out/'resumed_worker.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    result=json.loads((out/'summary.json').read_text());handoff=json.loads((out/'handoff.json').read_text()) if first.returncode==75 else None
    checks=dict(source_unchanged=hashlib.sha256(path.read_bytes()).hexdigest()==source_sha,
                fresh_process_handoff=bool(handoff and handoff['pid']!=result['pid']),
                first_worker_returncode=first.returncode,final_sha256=result['final_sha256'])
    atomic_json(out/'continuation_check.json',checks)
    assert checks['source_unchanged'] and result['valid_receipts']
    print(json.dumps({**checks,**{k:result[k] for k in ('goal_status','owner_ticks','final','distinct_plans','raw_fuel_mae_J','corrected_fuel_mae_J','raw_eta_mae_s','corrected_eta_mae_s')}},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('start','worker','control'))
    p.add_argument('--seed');p.add_argument('--output',required=True);p.add_argument('--stop-landings',type=int,default=0)
    a=p.parse_args()
    if a.mode=='start':start(a)
    else:
        if a.mode=='control':Path(a.output).mkdir(exist_ok=False)
        worker(a)
