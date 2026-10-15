"""A bounded session continued in a fresh Python process after two decisions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .monitor import ROOT,SelfModel
from .regulation import RegulatedGoal,RegulationJournal,NoSafeChoice
from motion_goal import MotionGoal
from persistent_embodiment_v1 import atomic_json,digest


def run_worker(journal_path,output,stop_after):
    journal=RegulationJournal(journal_path);out=Path(output).resolve()
    while True:
        goal=journal.load()
        if goal.session['status']!='running':break
        event=goal.goal.request()['event_id'];head=goal.checkpoint()['sha256']
        try:receipt=journal.step(event_id=event,expected_head=head)
        except NoSafeChoice as exc:
            atomic_json(out/'blocked.json',dict(reason=str(exc),head=head,pid=os.getpid()))
            break
        current=journal.load();row=current.session['records'][-1];d=row['decision']
        print(json.dumps(dict(pid=os.getpid(),index=d['index'],chosen=d['request']['requested'],actual=receipt['owner']['selected_action'],
            reason=d['reason'],landings=len(current.task['landings']),native_time_s=current.body.owner.physical.state.time_s,
            goal_elapsed=current.task['elapsed'],status=current.session['status'])),flush=True)
        if stop_after and len(current.session['records'])==stop_after:
            atomic_json(out/'handoff.json',dict(pid=os.getpid(),head=current.checkpoint()['sha256'],
                ticks=len(current.session['records']),goal_id=current.task['goal_id'],elapsed=current.task['elapsed']))
            os._exit(75)
    final=journal.load();knowledge,counts,assessed=final.derived()
    rows=final.session['records'];source_state=json.loads((out/'initial.json').read_text())
    summary=dict(schema='nasuraya-goal-directed-session/1',goal_id=final.task['goal_id'],session_id=final.session['session_id'],
        session_status=final.session['status'],goal_status=final.task['status'],owner_ticks=len(rows),choice_counts=counts,
        initial=source_state,final=dict(time_s=final.body.owner.physical.state.time_s,elapsed=final.task['elapsed'],
            landings=len(final.task['landings']),fuel_J=final.body.owner.owner.body.state.fuel_J,
            phase=final.body.owner.physical.state.phase,remaining_route_s=220-final.task['counts']['route']),
        goal_target_preserved=final.task['goal_id']==source_state['goal_id'],
        confirmed_new_landings=len(final.task['landings'])-source_state['landings'],
        selected=[r['decision']['request']['requested'] for r in rows],actual=[r['receipt']['owner']['selected_action'] for r in rows],
        valid_receipts=all(r['receipt']['owner']['physical_model_valid'] for r in rows),
        forecast_owner_receipts_equal=all(digest(r['receipt'])==r['decision']['candidates'][r['decision']['request']['requested']]['receipt_sha256'] for r in rows),
        charged_seconds=final.task['elapsed']-source_state['elapsed'],
        knowledge=knowledge,decision_records=rows,final_sha256=final.checkpoint()['sha256'],
        worker_pid=os.getpid(),official_state_advanced=False,model_api_calls=0)
    atomic_json(out/'final_session.json',final.checkpoint());atomic_json(out/'summary.json',summary)
    assert summary['charged_seconds']==summary['owner_ticks'] and summary['goal_target_preserved']
    print('FINAL',json.dumps({k:summary[k] for k in ['session_status','owner_ticks','selected','actual','confirmed_new_landings']}),flush=True)


def start(args):
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    source=Path(args.source).resolve();model_path=Path(args.model).resolve()
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,model_path)}
    original=MotionGoal.restore(json.loads(source.read_text()));knowledge=SelfModel(model_path).verify()
    regulated=RegulatedGoal.start(original,knowledge,session_id='regulation-2026-10-15',max_ticks=args.max_ticks,
        target_new_landings=min(1,14-len(original.task['landings'])))
    journal=RegulationJournal.create(out/'session.sqlite',regulated)
    atomic_json(out/'initial.json',dict(goal_id=original.task['goal_id'],time_s=original.body.owner.physical.state.time_s,
        elapsed=original.task['elapsed'],landings=len(original.task['landings']),fuel_J=original.body.owner.owner.body.state.fuel_J,
        source_hashes=hashes,session_max_ticks=args.max_ticks))
    command=[sys.executable,'-m','examples.nasuraya_self_model.run_regulation','worker','--output',str(out),'--journal',str(journal.path)]
    with (out/'first_worker.log').open('w') as log:
        first=subprocess.run(command+['--stop-after','2'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if first.returncode not in (0,75):raise RuntimeError('first owner failed; inspect first_worker.log')
    if first.returncode==75:
        with (out/'resumed_worker.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    result=json.loads((out/'summary.json').read_text())
    result['source_unchanged']=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    if first.returncode==75:
        handoff=json.loads((out/'handoff.json').read_text())
        result['fresh_process_handoff']=handoff['pid']!=result['worker_pid']
        result['handoff_ticks']=handoff['ticks']
    atomic_json(out/'summary.json',result)
    assert result['source_unchanged'] and result['valid_receipts'] and result['forecast_owner_receipts_equal']
    print(json.dumps({k:result[k] for k in ['session_status','owner_ticks','selected','actual','confirmed_new_landings','final','source_unchanged']},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('start','worker'))
    p.add_argument('--output',required=True);p.add_argument('--source');p.add_argument('--model');p.add_argument('--journal')
    p.add_argument('--max-ticks',type=int,default=12);p.add_argument('--stop-after',type=int,default=0)
    a=p.parse_args()
    if a.mode=='start':start(a)
    else:run_worker(a.journal,a.output,a.stop_after)
