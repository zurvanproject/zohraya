"""Continue a completed route on its accumulated body and verify cold handoff."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def run(native_root,source,output,direction):
    sys.path.insert(0,str(Path(native_root).resolve()))
    from unified_body_v2 import UnifiedBody
    from extension_state import restore,checkpoint,sources
    from persistent_embodiment_v1 import PersistentEmbodiment,digest
    from coordinated_support import CoordinatedSupport
    from motion_goal import MotionGoal,source_hash

    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    source=Path(source).resolve();source_hash_before=hashlib.sha256(source.read_bytes()).hexdigest()
    envelope=json.loads(source.read_text());body=restore(envelope)
    initial_native=body.checkpoint();initial=dict(time_s=body.owner.physical.state.time_s,
        walk_steps=body.owner.physical.state.walk_steps,fuel_J=body.owner.owner.body.state.fuel_J,
        free_water_L=body.owner.owner.body.state.free_water_L,minimum=deepcopy(body.owner.body()['minimum_state']))
    goal=MotionGoal.start(body,direction,'chain-'+direction);assert body.checkpoint()==initial_native
    loaded=dict(controller=sources(),goal=source_hash());rows=[];ticks=[];actual=False;handoff=None
    old_sim=PersistentEmbodiment._simulate;old_step=CoordinatedSupport.step

    def simulate(owner,*args,**kwargs):
        nonlocal actual
        previous=actual;actual=kwargs.get('actual',False)
        try:return old_sim(owner,*args,**kwargs)
        finally:actual=previous

    def step(physical,environment):
        f=old_step(physical,environment)
        if actual:ticks.append(dict(time_s=physical.state.time_s,valid=f['balance']['model_valid'],
            support=f['contact']['joint_support_fraction'],phase=physical.state.phase,reason=physical.state.failed_reason))
        return f

    PersistentEmbodiment._simulate=simulate;CoordinatedSupport.step=step
    try:
        while goal.task['status']=='running':
            verify=handoff is None and len(goal.task['landings'])>=7 and goal.task['phase']=='route'
            if verify:
                saved=goal.checkpoint();(out/'mid_goal.json').write_text(json.dumps(saved,indent=2))
                expected=goal.request();before_time=body.owner.physical.state.time_s;fuel=body.owner.owner.body.state.fuel_J
            phase=goal.task['phase'];r=goal.step();p=body.owner.physical
            rows.append(dict(index=len(rows),phase=phase,selected=r['owner']['selected_action'],
                cursor=deepcopy(p.star_started),valid=r['owner']['physical_model_valid'],time_s=p.state.time_s,
                fuel_used_J=sum(f['fuel_used_J'] for f in r['trace']),audit=r['whole_body_audit'],
                fatigue=max(p.body.state.fatigue.values()),sleep_pressure=body.owner.aux['sleep_pressure']))
            if verify:
                (out/'mid_request.json').write_text(json.dumps(expected,indent=2))
                subprocess.run([sys.executable,str(Path(__file__).resolve()),'replay',
                    '--native-root',str(Path(native_root).resolve()),'--source',str(out/'mid_goal.json'),
                    '--output',str(out/'cold_tick.json')],check=True)
                cold=json.loads((out/'cold_tick.json').read_text())
                current=goal.checkpoint()
                handoff=dict(goal_receipt_sha256=digest(r),goal_checkpoint_sha256=current['sha256'],
                    receipt_equal=digest(r)==cold['receipt_sha256'],checkpoint_equal=current['sha256']==cold['goal_sha256'],
                    request_equal=digest(expected)==cold['request_sha256'],owner_delta_s=p.state.time_s-before_time,
                    fuel_debit_J=fuel-p.body.state.fuel_J,receipt_fuel_J=rows[-1]['fuel_used_J'],
                    remaining_budget_equal=goal.task['counts']==cold['counts'],cold_owner_delta_s=cold['owner_delta_s'])
                assert handoff['receipt_equal'] and handoff['checkpoint_equal'] and handoff['request_equal'] and handoff['remaining_budget_equal']
                assert abs(handoff['owner_delta_s']-1.)<1e-7 and abs(handoff['fuel_debit_J']-handoff['receipt_fuel_J'])<5e-5
                (out/'handoff.json').write_text(json.dumps(handoff,indent=2))
            print(json.dumps({k:rows[-1][k] for k in ('index','phase','selected','cursor','valid','fatigue')}),flush=True)
        final=goal.checkpoint();assert MotionGoal.restore(json.loads(json.dumps(final))).checkpoint()==final
        p=body.owner.physical
        result=dict(schema='nasuraya-route-chain/1',direction=direction,source_sha256=envelope['sha256'],
            initial=initial,final=dict(time_s=p.state.time_s,walk_steps=p.state.walk_steps,fuel_J=p.body.state.fuel_J,
                free_water_L=p.body.state.free_water_L,minimum=deepcopy(body.owner.body()['minimum_state'])),
            task=goal.task,rows=rows,physical_substeps=len(ticks),minimum_support_fraction=min(t['support'] for t in ticks),
            invalid_ticks=[t for t in ticks if not t['valid']],handoff=handoff,goal_source=loaded,
            source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==source_hash_before,
            native_stocks_reset=False,official_state_advanced=False,model_api_calls=0,
            verification_clone_scope='one extra cold validation tick on a private clone; not charged to the continuing owner')
        assert result['source_unchanged'] and loaded==dict(controller=sources(),goal=source_hash())
        (out/'result.json').write_text(json.dumps(result,indent=2));(out/'final_goal.json').write_text(json.dumps(final,indent=2))
        print('FINAL',json.dumps(dict(status=goal.task['status'],seconds=goal.task['elapsed'],new_landings=len(goal.task['landings']),total_steps=p.state.walk_steps,reason=goal.task['stop_reason'])),flush=True)
        return result
    finally:
        PersistentEmbodiment._simulate=old_sim;CoordinatedSupport.step=old_step


def replay(native_root,source,output):
    sys.path.insert(0,str(Path(native_root).resolve()))
    from unified_body_v2 import UnifiedBody
    from persistent_embodiment_v1 import digest
    from motion_goal import MotionGoal
    goal=MotionGoal.restore(json.loads(Path(source).read_text()))
    request=goal.request();time=goal.body.owner.physical.state.time_s;r=goal.step()
    Path(output).write_text(json.dumps(dict(receipt_sha256=digest(r),goal_sha256=goal.checkpoint()['sha256'],
        request_sha256=digest(request),counts=goal.task['counts'],owner_delta_s=goal.body.owner.physical.state.time_s-time),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('run','replay'))
    parser.add_argument('--native-root',required=True);parser.add_argument('--source',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--direction',choices=('forward','reverse'))
    args=parser.parse_args()
    if args.mode=='run':run(args.native_root,args.source,args.output,args.direction)
    else:replay(args.native_root,args.source,args.output)
