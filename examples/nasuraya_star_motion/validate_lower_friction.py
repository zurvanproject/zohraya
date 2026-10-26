"""One bounded authored ritual performance on a declared waking practice branch.

Native fuel/gas/postural guards and arbitration remain active. The additive
controller changes the target of a native walking swing to a small star point;
it never relocates feet, resets state or grants energy. Finger/wrist rotation
and metaphysical effects are not solved by this model.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys


def run(native_root, source_db, output):
    native_root=Path(native_root).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(native_root))
    from unified_body_v2 import UnifiedBody
    from posture_step import PostureLoop
    from coordinated_support import CoordinatedSupport

    class StarPosture(CoordinatedSupport):
        def _start_swing(self,side,kind,target,duration):
            if kind=='walk' and self.star_enabled:
                i=self.star_started[side]
                if i < len(self.star_targets[side]):
                    proposed=self.star_targets[side][i]
                    if math.dist(proposed,self.state.feet_m[side])>self.design['max_step_length_m']:
                        raise ValueError('authored star target exceeds native reach contract')
                    target=proposed;self.star_started[side]+=1
            return super()._start_swing(side,kind,target,duration)

    raw=Path(source_db).resolve();source_hash=hashlib.sha256(raw.read_bytes()).hexdigest()
    with sqlite3.connect(raw.as_uri()+'?mode=ro',uri=True) as c:
        checkpoint=json.loads(c.execute('SELECT value FROM runtime WHERE key=?',('nasuraya-body-loop',)).fetchone()[0])
    body=UnifiedBody.restore(checkpoint);before=deepcopy(body.owner.body());start_revision=body.revision
    p=body.owner.physical;p.__class__=StarPosture;p.star_enabled=False
    p.star_started={s:0 for s in ('L','R')};p.star_targets={}
    order=[0,2,4,1,3,0]
    for side in ('L','R'):
        home=p.state.feet_m[side][:2]
        p.star_targets[side]=[[home[0]+.05*math.cos(math.pi/2+2*math.pi*k/5),home[1]+.05*math.sin(math.pi/2+2*math.pi*k/5),0.] for k in order]+[[*home,0.]]
    plan=deepcopy(p.star_targets);rows=[];clock=datetime.fromisoformat(body.owner.wall_utc);wall_start=clock
    feet_initial=deepcopy(p.state.feet_m);walk_initial=p.state.walk_steps
    bounds=dict(prelude_seconds=6,max_step_seconds=48,closure_seconds=4,star_radius_m=.05,
        foot_landings_requested=14,no_recovery_or_parameter_tuning=True)
    hand_targets=dict(shoulder_L=.35,shoulder_R=.35,elbow_L=1.2,elbow_R=1.2,head_pitch=-.1,head_yaw=0.)

    def cycle(phase,action,targets):
        nonlocal body,clock
        start=body.owner.owner.body.state.time_s
        external=dict(native=dict(upper_targets=targets,friction={'L':.45,'R':.45},imagery=[
            'C/authored ritual: four concentric boundaries; center Wuji; small pentagram foot route; palms facing as visual design only.']),
            sensors=dict(vision=dict(value=.25,source_id='authored-star-floor-'+str(len(rows)),
                sampled_at_s=start,kind='declared_simulated_input')))
        receipt=body.cycle(event_id=f'star-ritual-v1-{len(rows):03d}',at_utc=clock.isoformat(),
            duration_s=1.,requested=action,external=external,expected_revision=body.revision)
        p=body.owner.physical
        row=dict(index=len(rows),phase=phase,requested=action,selected=receipt['owner']['selected_action'],
            body_time_s=body.owner.owner.body.state.time_s,minimum=body.owner.body()['minimum_state'],
            upper_angles=deepcopy(body.owner.aux['upper_angles']),feet_m=deepcopy(p.state.feet_m),
            com_m=deepcopy(p.state.com_m),tail_angle_rad=deepcopy(p.state.tail_angle_rad),
            walk_touchdowns=p.state.walk_steps-walk_initial,
            star_targets_started=deepcopy(p.star_started),physical_model_valid=receipt['owner']['physical_model_valid'],
            failure_reason=p.state.failed_reason,
            actual_upper_work_paid_J=receipt['owner']['resource_and_gas_audit']['upper_motion_work_paid_J'],
            achieved_slow_breath_ticks=receipt['owner']['resource_and_gas_audit']['achieved_slow_breath_ticks'],
            whole_body_audit=receipt['whole_body_audit'],
            fuel_used_J=sum(x['fuel_used_J'] for x in receipt['trace']),
            neural=deepcopy(body.modules['outputs']['neural']),
            support_adjustments=getattr(p,'support_adjustments',0),support_searches=getattr(p,'support_searches',0),last_support_adjustment=deepcopy(getattr(p,'last_support_adjustment',None)),
            minimum_support_fraction=p.last['contact']['joint_support_fraction'],max_pressure_kpa=max(p.last['contact']['pressure_kpa'].values()),
            imagery_scope='authored C input, not a physical signal or energy source')
        rows.append(row);clock+=timedelta(seconds=1)
        print(json.dumps({k:row[k] for k in ['index','phase','requested','selected','walk_touchdowns','physical_model_valid']}) ,flush=True)
        return row

    stopped=None
    for _ in range(6):
        row=cycle('center-and-open-palms','slow_breath',hand_targets)
        if not row['physical_model_valid']:stopped='physical support invalid during prelude';break
    if stopped is None:
        body.owner.physical.star_enabled=True;veto_count=0
        for _ in range(48):
            row=cycle('star-in-place','walk',hand_targets)
            if not row['physical_model_valid']:stopped='physical support invalid during star';break
            veto_count=veto_count+1 if row['selected']!='walk' else 0
            if veto_count>=3:stopped='three consecutive native walk vetoes';break
            if row['walk_touchdowns']>=14:break
        body.owner.physical.star_enabled=False
    if stopped is None:
        for _ in range(4):
            row=cycle('close-and-return','slow_breath',{j:0. for j in hand_targets})
            if not row['physical_model_valid']:stopped='physical support invalid during closure';break
    after=deepcopy(body.owner.body());final=body.checkpoint()
    native_restore=UnifiedBody.restore(final)
    assert native_restore.checkpoint()==final
    assert hashlib.sha256(raw.read_bytes()).hexdigest()==source_hash
    result=dict(schema='nasuraya-authored-star-performance/1',source_checkpoint_sha256=checkpoint['sha256'],
        source_database_sha256=source_hash,source_database_unchanged=True,source_revision=start_revision,
        branch='explicit waking practice branch; not the high-sleep continuation session',
        bounds=bounds,source_pages=[dict(library_file_id='libfile_9896382870a88191a644cc259a55df48',file_page=165,printed_page=166,figure='1.161'),
            dict(library_file_id='libfile_9896382870a88191a644cc259a55df48',file_page=404,printed_page=405,figure='1.412')],
        observed_source='facing palms near chest; concentric circle diameters 9/8/7/6 ft, Wuji center',
        authored='name, verse, star targets/order, joint targets, scheduling and simulated visual input',
        before=before,after=after,rows=rows,star_targets=plan,feet_initial=feet_initial,
        total_simulated_seconds=len(rows),start_simulated_wall_utc=wall_start.isoformat(),stop_reason=stopped,
        actual_walk_touchdowns=body.owner.physical.state.walk_steps-walk_initial,
        support_extension_sha256=hashlib.sha256(Path(__file__).with_name('coordinated_support.py').read_bytes()).hexdigest(),
        star_complete=body.owner.physical.state.walk_steps-walk_initial>=14,
        actual_upper_motion_work_J=sum(r['actual_upper_work_paid_J'] for r in rows),
        actual_fuel_used_J=sum(r['fuel_used_J'] for r in rows),
        achieved_slow_breath_ticks=sum(r['achieved_slow_breath_ticks'] for r in rows),
        final_checkpoint_sha256=final['sha256'],final_revision=body.revision,
        checkpoint_cold_restore_exact=True,controller_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='software performance with an additive foot-target controller; not a physical or metaphysical measurement',
        limitations=['wrists/fingers/palm orientations are visual design only','no second-face deformation or crystal force solver',
                    'before/after does not isolate ritual symbols from movement/breath/time','native model remains uncalibrated'])
    (output/'performance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (output/'body_checkpoint.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native-root',required=True);p.add_argument('--source-db',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=run(a.native_root,a.source_db,a.output)
    print('FINAL',json.dumps({k:r[k] for k in ['total_simulated_seconds','actual_walk_touchdowns','star_complete','stop_reason','actual_upper_motion_work_J','final_revision']}))
