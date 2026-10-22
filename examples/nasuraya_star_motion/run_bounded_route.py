"""Bounded forward/reverse evaluation from a read-only recorded practice copy.

Budget: 6 s prelude, up to 220 s movement, 4 s closure. No state refill,
forced owner selection or native-limit changes. Incomplete routes stay incomplete.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys


def route_targets(feet, direction):
    if direction not in ('forward', 'reverse'):
        raise ValueError('unsupported direction')
    order = [0,2,4,1,3,0] if direction == 'forward' else [0,3,1,4,2,0]
    return {s:[[feet[s][0]+.05*math.cos(math.pi/2+2*math.pi*k/5),
                feet[s][1]+.05*math.sin(math.pi/2+2*math.pi*k/5),0.] for k in order]
              + [list(feet[s])] for s in ('L','R')}


def run(native_root, source_db, output, direction):
    sys.path.insert(0,str(Path(native_root).resolve()))
    from unified_body_v2 import UnifiedBody
    from persistent_embodiment_v1 import PersistentEmbodiment
    from coordinated_support import CoordinatedSupport
    from extension_state import attach, checkpoint, restore, sources, FIELDS

    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    source=Path(source_db).resolve();source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    loaded_sources=sources()
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as connection:
        native=json.loads(connection.execute('SELECT value FROM runtime WHERE key=?',('nasuraya-body-loop',)).fetchone()[0])
    body=UnifiedBody.restore(native);initial_time=body.owner.physical.state.time_s
    initial_feet=deepcopy(body.owner.physical.state.feet_m)
    plan=route_targets(initial_feet,direction)
    controller=dict(star_enabled=False,star_started=dict(L=0,R=0),star_targets=plan,cursor_semantics='confirmed')
    attach(body,controller);assert body.checkpoint()==native
    clock=datetime.fromisoformat(body.owner.wall_utc)
    targets=dict(shoulder_L=.35,shoulder_R=.35,elbow_L=1.2,elbow_R=1.2,head_pitch=-.1,head_yaw=0.)
    rows=[];touchdowns=[];adjustments=[];bad_frames=[];substeps=0;min_support=1.;stop=None;actual=False
    original_simulate=PersistentEmbodiment._simulate;original_step=CoordinatedSupport.step

    def simulate(owner,*args,**kwargs):
        nonlocal actual
        previous=actual;actual=kwargs.get('actual',False)
        try:return original_simulate(owner,*args,**kwargs)
        finally:actual=previous

    def step(physical,environment):
        nonlocal substeps,min_support
        phase=physical.state.phase
        frame=original_step(physical,environment)
        if actual:
            substeps+=1;min_support=min(min_support,frame['contact']['joint_support_fraction'])
            for event in frame['posture']['events_this_frame']:
                if event['name']=='touchdown':touchdowns.append(deepcopy(event))
            if frame['posture']['coordination_governor']['adjusted']:
                adjustments.append(dict(time_s=physical.state.time_s,phase_before=phase,
                    phase_after=physical.state.phase,command=environment.command,
                    diagnostic=deepcopy(physical.last_support_adjustment),support=frame['contact']['joint_support_fraction']))
            if not frame['balance']['model_valid']:bad_frames.append(deepcopy(frame))
        return frame

    def advance(phase,action,upper):
        nonlocal clock
        before=dict(body=body.checkpoint(),controller={k:deepcopy(getattr(body.owner.physical,k)) for k in FIELDS if hasattr(body.owner.physical,k)})
        time=body.owner.physical.state.time_s
        r=body.cycle(event_id=f'bounded-{direction}-{len(rows):03d}',at_utc=clock.isoformat(),
            duration_s=1.,requested=action,expected_revision=body.revision,
            external=dict(native=dict(upper_targets=upper,imagery=[
                'C/authored ritual: four concentric boundaries; center Wuji; small pentagram foot route; palms facing as visual design only.']),
                sensors=dict(vision=dict(value=.25,source_id='authored-star-floor-'+str(len(rows)),sampled_at_s=time,kind='declared_simulated_input'))))
        p=body.owner.physical
        row=dict(index=len(rows),phase=phase,requested=action,selected=r['owner']['selected_action'],
            elapsed_s=p.state.time_s-initial_time,valid=r['owner']['physical_model_valid'],
            candidates=r['owner']['candidates'],cursor=deepcopy(p.star_started),
            physical_phase=p.state.phase,swing=deepcopy(p.state.swing),feet_m=deepcopy(p.state.feet_m),
            com_m=list(p.state.com_m),velocity_m_s=list(p.state.velocity_m_s),
            balance=body.owner.body()['minimum_state']['balance'],whole_body_audit=r['whole_body_audit'],
            fuel_used_J=sum(f['fuel_used_J'] for f in r['trace']),owner_ticks=r['owner_ticks'])
        if action=='walk' and row['selected']!='walk':
            (output/f'veto_before_{len(rows):03d}.json').write_text(json.dumps(before,indent=2))
        rows.append(row);clock+=timedelta(seconds=1)
        print(json.dumps({k:row[k] for k in ('index','phase','selected','cursor','valid')}),flush=True)
        return row

    PersistentEmbodiment._simulate=simulate;CoordinatedSupport.step=step
    try:
        for _ in range(6):
            if not advance('prelude','slow_breath',targets)['valid']:stop='prelude invalid';break
        if stop is None:
            body.owner.physical.star_enabled=True;veto=0
            for _ in range(220):
                if all(body.owner.physical.star_started[s]==len(plan[s]) for s in ('L','R')):break
                row=advance('route','walk',targets)
                if not row['valid']:stop='route invalid';break
                veto=veto+1 if row['selected']!='walk' else 0
                if veto>=3:stop='three consecutive native walk vetoes';break
            body.owner.physical.star_enabled=False
        complete=all(body.owner.physical.star_started[s]==len(plan[s]) for s in ('L','R'))
        if stop is None:
            for _ in range(4):
                if not advance('closure','slow_breath',{j:0. for j in targets})['valid']:stop='closure invalid';break
        final=checkpoint(body)
        assert checkpoint(restore(json.loads(json.dumps(final))))==final
        assert sources()==loaded_sources,'controller source changed during execution'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
        confirmed=[e for e in touchdowns if e.get('kind')=='walk']
        for side in ('L','R'):
            got=[e['position_m'] for e in confirmed if e['side']==side]
            assert got==plan[side][:len(got)],'touchdown order differs from route'
        home=max(math.dist(body.owner.physical.state.feet_m[s],initial_feet[s]) for s in ('L','R'))
        result=dict(schema='nasuraya-bounded-route/1',direction=direction,source_checkpoint_sha256=native['sha256'],
            source_database_sha256=source_hash,controller_sources=loaded_sources,
            contract=dict(prelude_seconds=6,movement_max_seconds=220,closure_seconds=4,radius_m=.05,requested_landings=14),
            rows=rows,touchdowns=touchdowns,adjustments=adjustments,invalid_frames=bad_frames,
            complete=complete,stop_reason=stop,valid=all(r['valid'] for r in rows),actual_seconds=len(rows),
            confirmed_landings=len(confirmed),final_home_error_m=home,final_phase=body.owner.physical.state.phase,
            final_balance=rows[-1]['balance'],minimum_support_fraction=min_support,physical_substeps=substeps,
            total_fuel_used_J=sum(r['fuel_used_J'] for r in rows),cold_restore_exact=True,source_unchanged=True,
            no_stock_reset=True,native_limits_changed=False,official_state_advanced=False,model_api_calls=0)
        (output/'result.json').write_text(json.dumps(result,indent=2))
        (output/'checkpoint.json').write_text(json.dumps(final,indent=2))
        print('FINAL',json.dumps({k:result[k] for k in ('direction','complete','stop_reason','valid','actual_seconds','confirmed_landings','final_home_error_m','final_phase','final_balance')}),flush=True)
        return result
    finally:
        PersistentEmbodiment._simulate=original_simulate;CoordinatedSupport.step=original_step


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--native-root',required=True)
    parser.add_argument('--source-db',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--direction',required=True,choices=('forward','reverse'));args=parser.parse_args()
    run(args.native_root,args.source_db,args.output,args.direction)
