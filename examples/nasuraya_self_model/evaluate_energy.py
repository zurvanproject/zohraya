"""Frozen three-way synthetic native energy evaluation, separate from body practice."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .energy import EnergyCalibration, example
from .evaluate import fixture, prepare_defaults
from .planning import state, rollout, bounded_mean, POLICY
from .monitor import ROOT, digest
from extension_state import attach
from motion_goal import MotionGoal
from persistent_embodiment_v1 import atomic_json


def episode(pressure, name, out, protocol):
    body=fixture(pressure)
    attach(body,dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=dict(L=[],R=[]),cursor_semantics='confirmed'))
    goal=MotionGoal.start(body,'reverse',name)
    for _ in range(6):goal.step()
    initial=goal.checkpoint();atomic_json(out/(name+'-initial.json'),initial)
    rows=[];plan=None;offset=0
    for tick in range(protocol['ticks_per_fixture']):
        if goal.task['status']!='running':break
        before=state(goal);request=goal.request()
        if plan is None:
            owner_before=goal.checkpoint()['sha256']
            candidate=rollout(goal,request['requested'],min(protocol['forecast_horizon'],
                dict(prelude=6,route=220,closure=4)[goal.task['phase']]-goal.task['counts'][goal.task['phase']]))
            assert goal.checkpoint()['sha256']==owner_before
            plan=dict(initial=before,candidates={request['requested']:candidate},chosen=request['requested'])
            offset=0
        d=dict(before=before,request=request,plan=deepcopy(plan),offset=offset)
        receipt=goal.step();after=state(goal)
        row=dict(decision=d,after=after,receipt=receipt)
        row['energy']=example(row);rows.append(row)
        offset+=1
        if (offset>=len(candidate['series']) or after['landings']>before['landings'] or
                after['goal_phase']!=before['goal_phase'] or receipt['owner']['selected_action']!=request['requested']):
            plan=None
    final=goal.checkpoint();atomic_json(out/(name+'-final.json'),final)
    assert all(r['receipt']['owner']['physical_model_valid'] for r in rows)
    assert len(rows)==goal.task['elapsed']-initial['payload']['task']['elapsed']
    return rows,dict(initial_sha=initial['sha256'],final_sha=final['sha256'],owner_ticks=len(rows),
                    landings=len(goal.task['landings']),time_s=state(goal)['time_s'],counts=goal.task['counts'],
                    native_valid=True,sleep_pressure=pressure)


def evaluate(output):
    out=Path(output).resolve();out.mkdir(exist_ok=False,parents=True)
    path=Path(__file__).with_name('energy_protocol.json');protocol=json.loads(path.read_text())
    # Persist this before generating any new native outcome.
    atomic_json(out/'frozen_protocol.json',dict(protocol=protocol,protocol_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    prepare_defaults();model=EnergyCalibration();ema={};results=[];summary=[];hashes={}
    for split in ('training','validation','held_out'):
        if split=='validation':model.begin_validation()
        if split=='held_out':
            model.freeze();atomic_json(out/'model.json',model.checkpoint());frozen=model.checkpoint()
        hashes[split]=set()
        for i,pressure in enumerate(protocol[split+'_sleep_pressure']):
            name=f'energy-{split}-{i}'
            rows,meta=episode(pressure,name,out,protocol);hashes[split].add(meta['initial_sha'])
            atomic_json(out/(name+'-receipts.json'),rows)
            for tick,row in enumerate(rows):
                item=row['energy'];action=row['decision']['request']['requested']
                record=dict(split=split,fixture=name,tick=tick,event_id=row['decision']['request']['event_id'],
                            **item,predicted_J=model.predict(item['features'],item['raw_J']),
                            old_ema_predicted_J=item['raw_J']+ema.get(action,0.),
                            receipt_sha256=digest(row['receipt']))
                results.append(record)
                if split!='held_out':model.add(record['event_id'],item)
                if split=='training':
                    ema[action]=bounded_mean(ema.get(action,0.),item['actual_J']-item['raw_J'],POLICY['fuel_bias_limit_J'])
            summary.append(dict(split=split,fixture=name,**meta))
            print(json.dumps(dict(split=split,fixture=name,ticks=len(rows),landings=meta['landings'])),flush=True)
    assert model.checkpoint()==frozen
    assert all(not(hashes[a]&hashes[b]) for a,b in [('training','validation'),('training','held_out'),('validation','held_out')])
    atomic_json(out/'predictions.json',results)
    reanalyze(out)


def reanalyze(output):
    """Reproduce fitting and scores from retained receipts, without native ticks.

    This also permits hardening the checkpoint source contract without rerunning
    physical actions. Model parameters and the frozen protocol must be unchanged.
    """
    out=Path(output).resolve();path=Path(__file__).with_name('energy_protocol.json')
    protocol=json.loads(path.read_text());saved=json.loads((out/'frozen_protocol.json').read_text())
    if saved != dict(protocol=protocol,protocol_sha256=hashlib.sha256(path.read_bytes()).hexdigest()):
        raise ValueError('saved evaluation protocol changed')
    pressures=[set(protocol[s+'_sleep_pressure']) for s in ('training','validation','held_out')]
    if any(pressures[a]&pressures[b] for a,b in [(0,1),(0,2),(1,2)]):
        raise ValueError('declared fixture inputs overlap')
    model=EnergyCalibration();ema={};results=[];summary=[];hashes={}
    for split in ('training','validation','held_out'):
        if split=='validation':model.begin_validation()
        if split=='held_out':model.freeze();frozen=model.checkpoint()
        hashes[split]=set()
        for i,pressure in enumerate(protocol[split+'_sleep_pressure']):
            name=f'energy-{split}-{i}'
            initial=MotionGoal.restore(json.loads((out/(name+'-initial.json')).read_text()))
            final=MotionGoal.restore(json.loads((out/(name+'-final.json')).read_text()))
            hashes[split].add(initial.checkpoint()['sha256'])
            rows=json.loads((out/(name+'-receipts.json')).read_text());previous=state(initial)
            if len(rows)>protocol['ticks_per_fixture']:raise ValueError('fixture tick budget')
            for tick,row in enumerate(rows):
                d=row['decision'];receipt=row['receipt'];item=example(row)
                if (d['before']!=previous or row['after']['elapsed']!=previous['elapsed']+1 or
                    abs(row['after']['time_s']-previous['time_s']-1.)>1e-8 or
                    receipt['event_id']!=d['request']['event_id'] or not receipt['owner']['physical_model_valid'] or
                    item!=row['energy']):raise ValueError('saved native evidence lineage')
                if receipt['event_id'] in final.body.results and final.body.results[receipt['event_id']]!=receipt:
                    raise ValueError('saved receipt differs from native result')
                previous=row['after'];action=d['request']['requested']
                record=dict(split=split,fixture=name,tick=tick,event_id=receipt['event_id'],**item,
                    predicted_J=model.predict(item['features'],item['raw_J']),
                    old_ema_predicted_J=item['raw_J']+ema.get(action,0.),receipt_sha256=digest(receipt))
                results.append(record)
                if split!='held_out':model.add(record['event_id'],item)
                if split=='training':ema[action]=bounded_mean(ema.get(action,0.),item['actual_J']-item['raw_J'],POLICY['fuel_bias_limit_J'])
            if state(final)!=previous:raise ValueError('saved fixture final state')
            summary.append(dict(split=split,fixture=name,initial_sha=initial.checkpoint()['sha256'],
                final_sha=final.checkpoint()['sha256'],owner_ticks=len(rows),landings=len(final.task['landings']),
                time_s=state(final)['time_s'],counts=final.task['counts'],native_valid=True,sleep_pressure=pressure))
    assert model.checkpoint()==frozen
    assert all(not(hashes[a]&hashes[b]) for a,b in [('training','validation'),('training','held_out'),('validation','held_out')])
    old_path=out/'model.json'
    if old_path.exists():
        old=json.loads(old_path.read_text())
        if digest(old['payload'])!=old['sha256']:raise ValueError('prior model checksum')
        if (old['payload']['schema']!=frozen['payload']['schema'] or
            any(frozen['payload']['sources'].get(k)!=v for k,v in old['payload']['sources'].items())):
            raise ValueError('reanalysis cannot migrate changed source code')
        for k in ('stage','training','validation','seen','policy'):
            if old['payload'][k]!=frozen['payload'][k]:raise ValueError('model changed during reanalysis')
        if old!=frozen:atomic_json(out/'prior_model_contract.json',old)
    predictions_path=out/'predictions.json'
    if predictions_path.exists() and json.loads(predictions_path.read_text())!=results:
        raise ValueError('prediction values changed during contract hardening')
    atomic_json(old_path,frozen);atomic_json(predictions_path,results)
    cold=out/'cold.json'
    subprocess.run([sys.executable,'-m','examples.nasuraya_self_model.evaluate_energy','cold','--output',str(cold),
                    '--model',str(old_path),'--predictions',str(predictions_path)],cwd=ROOT,check=True)
    held=[r for r in results if r['split']=='held_out']
    assert json.loads(cold.read_text())==[r['predicted_J'] for r in held]
    def metrics(rows):
        def mae(key):return sum(abs(r['actual_J']-r[key]) for r in rows)/len(rows)
        return dict(n=len(rows),raw_mae_J=mae('raw_J'),old_ema_mae_J=mae('old_ema_predicted_J'),
                    calibrated_mae_J=mae('predicted_J'),corrected_predictions=sum(r['predicted_J']!=r['raw_J'] for r in rows))
    result=dict(schema=protocol['schema'],held_out=metrics(held),fixtures=summary,
        by_fixture={s['fixture']:metrics([r for r in held if r['fixture']==s['fixture']]) for s in summary if s['split']=='held_out'},
        protocol_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),model_sha256=frozen['sha256'],
        enabled_contexts=sum(model.correction(r['features'])!=0 for r in {digest(r['features']):r for r in held}.values()),
        cold_predictions_equal=True,held_out_model_unchanged=True,split_checkpoint_hashes_disjoint=True,
        original_planner_policy_modified=False,official_state_advanced=False,live_model_api_calls=0,
        reanalysis_native_ticks=0,scope=protocol['scope'])
    result['distinct_held_out_energy_traces']=len({digest([(r['raw_J'],r['actual_J']) for r in held if r['fixture']==s['fixture']])
        for s in summary if s['split']=='held_out'})
    result['acceptance_passed']=result['held_out']['calibrated_mae_J']<min(result['held_out']['raw_mae_J'],result['held_out']['old_ema_mae_J'])
    atomic_json(out/'evaluation.json',result);print(json.dumps(result,indent=2),flush=True)


def transfer(model_path,source,output):
    """Retrospective transfer check on a previously inspected private route."""
    from .planning import PlanningGoal
    path=Path(source);file_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    goal=PlanningGoal.restore(json.loads(path.read_text()))
    model=EnergyCalibration.restore(json.loads(Path(model_path).read_text()));frozen=model.checkpoint()
    rows=[]
    for row in goal.session['records']:
        e=example(row);pred=model.predict(e['features'],e['raw_J'])
        rows.append(dict(**e,predicted_J=pred,old_corrected_error_J=row['feedback']['corrected_fuel_error_J']))
    n=len(rows)
    result=dict(schema='nasuraya-energy-retrospective-transfer/1',n=n,
        raw_mae_J=sum(abs(r['actual_J']-r['raw_J']) for r in rows)/n,
        old_prequential_mae_J=sum(abs(r['old_corrected_error_J']) for r in rows)/n,
        calibrated_mae_J=sum(abs(r['actual_J']-r['predicted_J']) for r in rows)/n,
        corrected_predictions=sum(r['raw_J']!=r['predicted_J'] for r in rows),
        source_session_sha=goal.checkpoint()['sha256'],model_sha256=frozen['sha256'],
        source_file_sha256=file_sha,source_unchanged=hashlib.sha256(path.read_bytes()).hexdigest()==file_sha,
        model_unchanged=model.checkpoint()==frozen,native_actions_executed=0,
        scope='retrospective transfer on previously inspected receipts; not blind holdout; original policy trajectory, no new route execution')
    assert result['source_unchanged'] and result['model_unchanged']
    atomic_json(Path(output),result);print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('evaluate','reanalyze','transfer','cold'))
    p.add_argument('--output',required=True);p.add_argument('--model');p.add_argument('--predictions');p.add_argument('--source');args=p.parse_args()
    if args.mode=='evaluate':evaluate(args.output)
    elif args.mode=='reanalyze':reanalyze(args.output)
    elif args.mode=='transfer':transfer(args.model,args.source,args.output)
    else:
        m=EnergyCalibration.restore(json.loads(Path(args.model).read_text()))
        rows=json.loads(Path(args.predictions).read_text())
        atomic_json(Path(args.output),[m.predict(r['features'],r['raw_J']) for r in rows if r['split']=='held_out'])
