"""Run a frozen paired-route protocol; no model API or official body writes."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .route_trial import RouteTrial,TrialJournal,sources,selection
from .energy import EnergyCalibration,example
from . import planning as base
from .monitor import ROOT,digest
from motion_goal import MotionGoal
from persistent_embodiment_v1 import atomic_json


def summary(goal):
    initial=goal.session['initial'];final=base.state(goal.goal);rows=goal.session['records']
    active=[]
    for r in rows:
        if goal.session['mode']=='old':active.append(abs(r['feedback']['corrected_fuel_error_J']))
        else:
            e=example(r);active.append(abs(e['actual_J']-goal.model.predict(e['features'],e['raw_J'])))
    return dict(mode=goal.session['mode'],initial=initial,final=final,goal_status=goal.task['status'],
        owner_ticks=len(rows),fuel_used_J=initial['fuel_J']-final['fuel_J'],
        new_landings=final['landings']-initial['landings'],confirmed_landings=goal.task['landings'],
        counts=goal.task['counts'],remaining_ticks=230-final['elapsed'],
        requested=dict(Counter(r['decision']['request']['requested'] for r in rows)),
        actual=dict(Counter(r['receipt']['owner']['selected_action'] for r in rows)),
        all_receipts_valid=all(r['receipt']['owner']['physical_model_valid'] for r in rows),
        final_goal_sha256=goal.goal.checkpoint()['sha256'],final_trial_sha256=goal.checkpoint()['sha256'],
        raw_fuel_mae_J=sum(abs(r['feedback']['fuel_error_J']) for r in rows)/len(rows),
        active_fuel_mae_J=sum(active)/len(active),
        model_sha256=goal.model.checkpoint()['sha256'],retained_knowledge_sha256=digest(goal.session['retained_knowledge']),
        official_state_advanced=False,model_api_calls=0,pid=os.getpid())


def worker(args):
    out=Path(args.output).resolve()
    if args.mode=='memory':
        seed=json.loads(Path(args.seed).read_text());model=EnergyCalibration.restore(json.loads(Path(args.model).read_text()))
        goal=RouteTrial.start(MotionGoal.restore(seed['goal']),args.policy,model,seed['knowledge']);journal=None
    else:journal=TrialJournal(out/'session.sqlite');goal=journal.load()
    while goal.session['status']=='running':
        event=goal.goal.request()['event_id']
        if journal:
            receipt=journal.step(event_id=event,expected_head=goal.checkpoint()['sha256'],current_goal=goal)
        else:receipt=goal.step()
        row=goal.session['records'][-1];d=row['decision'];p=d['plan']
        other='calibrated' if goal.session['mode']=='old' else 'old'
        alternative,_=selection(other,p['initial']['goal_phase'],p['initial'],p['candidates'],p['calibration'],
                                base.counts(goal.session['records'][:len(goal.session['records'])-d['offset']-1]),goal.model)
        print(json.dumps(dict(pid=os.getpid(),mode=goal.session['mode'],tick=len(goal.session['records']),
            elapsed=goal.task['elapsed'],landings=len(goal.task['landings']),requested=d['request']['requested'],
            actual=receipt['owner']['selected_action'],posture=row['after']['minimum']['posture'],
            fuel_J=row['after']['fuel_J'],fatigue=row['after']['minimum']['fatigue'],new_plan=d['offset']==0,
            other_policy_same_candidates=alternative,plan_chosen=p['chosen'])),flush=True)
        if journal and args.stop_landings and len(goal.task['landings'])>=args.stop_landings and goal.task['status']=='running':
            atomic_json(out/'handoff.json',dict(pid=os.getpid(),head=goal.checkpoint()['sha256'],state=base.state(goal.goal)))
            os._exit(75)
    atomic_json(out/'final_trial.json',goal.checkpoint());atomic_json(out/'summary.json',summary(goal))
    print('FINAL',json.dumps(summary(goal)),flush=True)


def start(args):
    out=Path(args.output).resolve();out.mkdir(exist_ok=False,parents=True)
    source=Path(args.seed).resolve();seed=json.loads(source.read_text())
    model=EnergyCalibration.restore(json.loads(Path(args.model).read_text()))
    goal=RouteTrial.start(MotionGoal.restore(seed['goal']),args.policy,model,seed['knowledge'])
    TrialJournal.create(out/'session.sqlite',goal)
    atomic_json(out/'protocol.json',dict(sources=sources(),seed_file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        initial_goal_sha256=seed['goal']['sha256'],model_sha256=model.checkpoint()['sha256'],mode=args.policy,
        initial=base.state(goal.goal),max_ticks=goal.session['max_ticks'],stop_landings=args.stop_landings))
    command=[sys.executable,'-m','examples.nasuraya_self_model.run_route_trial','worker','--output',str(out)]
    with (out/'first_worker.log').open('w') as log:
        first=subprocess.run(command+['--stop-landings',str(args.stop_landings)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if first.returncode not in (0,75):raise RuntimeError('first route trial worker failed')
    if first.returncode==75:
        with (out/'resumed_worker.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    final=json.loads((out/'summary.json').read_text())
    checks=dict(seed_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==json.loads((out/'protocol.json').read_text())['seed_file_sha256'],
        first_returncode=first.returncode,fresh_process_handoff=first.returncode==75 and json.loads((out/'handoff.json').read_text())['pid']!=final['pid'])
    assert checks['seed_unchanged']
    atomic_json(out/'continuation_check.json',checks);print(json.dumps(checks),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('memory','start','worker'))
    p.add_argument('--output',required=True);p.add_argument('--seed');p.add_argument('--model')
    p.add_argument('--policy',choices=('old','calibrated'));p.add_argument('--stop-landings',type=int,default=0)
    args=p.parse_args()
    if args.mode=='start':start(args)
    else:
        if args.mode=='memory':Path(args.output).mkdir(exist_ok=False,parents=True)
        worker(args)
