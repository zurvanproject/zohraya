"""Frozen native-receipt evaluation and optional existing-goal practice."""
import argparse
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .monitor import SelfModel,snapshot,ROOT
from synthetic_fixture import prepare_defaults,synthetic_body
from persistent_embodiment_v1 import atomic_json,digest


def fixture(pressure):
    body=synthetic_body();before=body.owner.body()
    body.owner.aux['sleep_pressure']=pressure
    body.owner._record(before,body.owner.body(),'external_input',
        'declared self-efficacy evaluation fixture; no user state reset',0.)
    return body


def request(body,event,duration=.1):
    return dict(event_id=event,at_utc=(datetime.fromisoformat(body.owner.wall_utc)+timedelta(seconds=duration)).isoformat(),
        duration_s=duration,requested='walk',expected_revision=body.revision,
        external=dict(sensors=dict(vision=dict(value=.25,source_id=event+':vision',
            sampled_at_s=body.owner.physical.state.time_s,kind='declared_simulated_input'))))


def evaluate(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    protocol_path=Path(__file__).with_name('protocol.json');protocol=json.loads(protocol_path.read_text())
    atomic_json(out/'frozen_protocol.json',protocol)
    prepare_defaults();model=SelfModel.create(out/'self_model.sqlite');rows=[];train_hashes=set();test_hashes=set()
    for split,pressures in [('train',protocol['training_sleep_pressure']),('held_out',protocol['held_out_sleep_pressure'])]:
        frozen_counts=model.verify()['counts']
        for index,pressure in enumerate(pressures):
            body=fixture(pressure);before=snapshot(body);req=request(body,f'{split}:{index}')
            pred=model.begin(body,req);receipt=body.cycle(**req)
            result=model.finish(req['event_id'],body,receipt,learn=split=='train')
            (train_hashes if split=='train' else test_hashes).add(before['native_sha'])
            rows.append(dict(split=split,input_native_sha=before['native_sha'],sleep_pressure=pressure,
                prediction=pred,admitted=result['admitted'],actual=receipt['owner']['selected_action'],
                brier=result['brier'],fixed_prior_brier=(.5-int(result['admitted']))**2,
                receipt_sha256=digest(receipt)))
        if split=='held_out':assert model.verify()['counts']==frozen_counts
    held=[r for r in rows if r['split']=='held_out'];state=model.verify()
    cold=out/'cold.json'
    subprocess.run([sys.executable,'-m','examples.nasuraya_self_model.evaluate','cold',
        '--model',str(model.path),'--output',str(cold)],cwd=ROOT,check=True)
    assert json.loads(cold.read_text())==json.loads(json.dumps(state))
    result=dict(schema=protocol['schema'],protocol_sha256=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        rows=rows,training_episodes=8,held_out_episodes=4,
        fixed_prior_brier=sum(r['fixed_prior_brier'] for r in held)/len(held),
        self_model_brier=sum(r['brier'] for r in held)/len(held),
        train_test_native_hashes_disjoint=not(train_hashes & test_hashes),cold_model_equal=True,
        held_out_learning=False,model_updates=sum(sum(v) for v in state['counts'].values()),
        subjective_experience_measured=False,external_model_api_used=False,
        scope='prospective software requested-action admission; comparator is a fixed 0.5 prior, not native forecasting')
    assert result['train_test_native_hashes_disjoint'] and result['self_model_brier']<result['fixed_prior_brier']
    atomic_json(out/'evaluation.json',result);print(json.dumps(result,indent=2),flush=True)


def practice(source,output):
    sys.path.insert(0,str(ROOT/'examples/nasuraya_star_motion'))
    from motion_journal import MotionJournal
    from motion_goal import MotionGoal
    from .goal_bridge import step_goal
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    source=Path(source).resolve();before_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    goal=MotionGoal.restore(json.loads(source.read_text()))
    body_store=MotionJournal.create(out/'practice.sqlite',goal)
    model=SelfModel.create(out/'self_model.sqlite');rows=[]
    initial=dict(time_s=goal.body.owner.physical.state.time_s,goal_elapsed=goal.task['elapsed'],
        native_sha=goal.body.checkpoint()['sha256'])
    gate_before=step_goal(model,body_store)
    assert not gate_before['executed'] and body_store.load().checkpoint()==goal.checkpoint()
    for _ in range(4):
        goal=body_store.load();req=goal.request();obs=snapshot(goal.body)
        introspection=model.inspect(obs,req);prediction=model.begin(goal.body,req)
        receipt=body_store.step(event_id=req['event_id'],expected_head=goal.checkpoint()['sha256'])
        after=body_store.load();result=model.finish(req['event_id'],after.body,receipt)
        rows.append(dict(before=introspection,prediction=prediction,admitted=result['admitted'],
            actual=receipt['owner']['selected_action'],brier=result['brier'],receipt_sha256=digest(receipt)))
    before_gate=body_store.load().checkpoint()
    gate_after=step_goal(model,body_store)
    final=body_store.load();report=model.inspect(snapshot(final.body),final.request())
    if not gate_after['executed']:assert final.checkpoint()==before_gate
    atomic_json(out/'advanced_goal.json',final.checkpoint())
    result=dict(initial=initial,final=dict(time_s=final.body.owner.physical.state.time_s,goal_elapsed=final.task['elapsed'],
        native_sha=final.body.checkpoint()['sha256']),rows=rows,self_report=report,model_state=model.verify(),
        gate_before=gate_before,gate_after=gate_after,
        source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==before_hash,
        execution_kind='four explicitly authorized practice probes; monitor did not bypass native guards',
        subjective_experience_measured=False,model_api_calls=0,official_state_advanced=False)
    assert result['source_unchanged'];atomic_json(out/'practice.json',result)
    print(json.dumps(dict(initial=initial,final=result['final'],inferred=report['inferred'],recommendation=report['recommendation']),indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('evaluate','practice','cold'))
    p.add_argument('--output',required=True);p.add_argument('--model');p.add_argument('--source')
    a=p.parse_args()
    if a.mode=='evaluate':evaluate(a.output)
    elif a.mode=='practice':practice(a.source,a.output)
    else:atomic_json(a.output,SelfModel(a.model).verify())
