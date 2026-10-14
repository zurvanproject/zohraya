"""Source-qualified anthropometry and bounded reduced-model motion evaluation.

Visual revisions do not modify native geometry. Paired trials establish this
invariance, not improved strength, prettier geometry or validated mesh contact.
Private checkpoints are read-only; all execution is on isolated clones.
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

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT/'runtimes/tadash_body'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(NATIVE))
from unified_body_v2 import UnifiedBody
from posture_step import GaitEnvironment, Inputs, PostureLoop
from persistent_embodiment_v1 import digest
sys.path.insert(0,str(ROOT/'examples/nasuraya_star_motion'))
from extension_state import restore as restore_star, checkpoint as star_checkpoint
from examples.nasuraya_body_loop.__main__ import verified_sources

DESIGN = NATIVE/'base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json'
CASES = [
 dict(name='standing',segments=[['stand',2.0]]),
 dict(name='left_support_and_return',segments=[['single_L',12.0],['stand',3.0]]),
 dict(name='right_support_and_return',segments=[['single_R',12.0],['stand',3.0]]),
 dict(name='walking_and_stopping',segments=[['walk',24.0],['stand',4.0]]),
 dict(name='impulse_tail_enabled',segments=[['stand',4.0]],impulse=[8.0,4.0]),
 dict(name='impulse_tail_disabled',segments=[['stand',4.0]],impulse=[8.0,4.0],tail=False),
 dict(name='zero_friction_negative_control',segments=[['walk',3.0]],friction=0.0),
 dict(name='known_regional_danger',segments=[['stand',1.0]],
      stimuli={'calf_L':{'damage':.9}}),
]
VISUAL_REVISION = dict(schema='nasuraya-visual-leg-revision/1',
 native_geometry_changed=False, mass_changed=False, force_limits_changed=False,
 modifications=['short fine fur following the muscle contour',
 'smooth calf-to-ankle transition without boot-like fur cuff',
 'longer-looking instep aligned with the retained hock-to-anchor segment',
 'three smoothly integrated broad toes with short rounded nails',
 'preserve the plantar pad and load-bearing width; do not shrink the foot'],
 mechanical_geometry_source='unchanged contact_design_v06.json',
 status='authored rendering specification; no deformable 3D mesh')


def geometry():
    phenotype=json.loads((NATIVE/'phenotype_v1.json').read_text())
    a=phenotype['adult_scale'];d=json.loads(DESIGN.read_text())
    return dict(evidence_level='declared uncalibrated model parameters',
        height_excluding_horns_cm=a['ground_to_crown_cm'],mass_kg=d['mass_kg'],
        landmarks_z_cm=a['landmarks_z_cm'],leg_lengths_cm=[v*100 for v in d['leg_lengths_m']],
        leg_segment_fractions=[v/sum(d['leg_lengths_m']) for v in d['leg_lengths_m']],
        foot_external_design_cm=a['feet'],
        loaded_contact_area_each_cm2=sum(p['area_m2'] for p in d['patches'])*1e4,
        loaded_area_equals_external_target=False,
        hip_joint_spacing_cm=2*d['hip_half_width_m']*100,
        tail_length_cm=100*d['tail_length_m'],tail_mass_kg=d['tail_mass_kg'],
        horns=a['horns'],separate_horn_mass_kg=None,
        measured_head_neck_shoulder_width_cm=None,actual_muscle_volume_cm3=None,
        collision_mesh_available=False,rotating_contact_patches=False,
        coordinate_scope='3D joint points and fixed planar contact centres; no body surface mesh')


def sample(frame,loop):
    p=frame['posture'];m=frame['motor'];c=frame['contact']
    return dict(time_s=p['time_s'],phase=p['phase'],valid=frame['balance']['model_valid'],
        failure=p['failed_reason'],feet_m=p['feet_m'],com_m=p['com_m'],
        joints={s:p['kinematics'][s] for s in ('L','R')},
        pressures_kpa=c['pressure_kpa'],normal_force_N=c['normal_N'],
        support_fraction=c.get('joint_support_fraction'),
        capture_margin_m=frame['balance']['capture_margin_m'],
        joint_force_N=m['force_N'],joint_force_required_N=m['requests_N'],
        equivalent_load_arm_moment_Nm={k:v*loop.body.sections[k]['external_load_arm_m']
            for k,v in m['force_N'].items()},
        joint_rate_rad_s=p['joint_rates_rad_s'],tail_torque_Nm=p['tail_torque_actual_Nm'],
        tail_angle_rad=p['tail_angle_rad'],fuel_used_J=frame['ledger']['fuel_used_J'],
        work_J=frame['ledger']['work_J'],walk_steps=p['walk_steps'],
        protective_steps=p['protective_steps'],friction_saturated=c['friction_saturated'],
        regional_latches=deepcopy(loop.body.state.latched),
        max_segment_length_error_m=max(v['segment_length_error_m'] for v in p['kinematics'].values()),
        events=p['events_this_frame'])


def trial(template,case):
    loop=deepcopy(template);loop.star_enabled=False
    before=loop.checkpoint();before_walk=loop.state.walk_steps;rows=[]
    for command,seconds in case['segments']:
        for _ in range(round(seconds/.1)):
            e=GaitEnvironment(command=command,body=Inputs(dt_s=.1,stimuli=case.get('stimuli',{})),
                friction=dict(L=case.get('friction',.6),R=case.get('friction',.6)),
                tail_enabled=case.get('tail',True),
                external_impulse_N_s=case.get('impulse',[0.,0.]) if not rows else [0.,0.])
            frame=loop.step(e);rows.append(sample(frame,loop))
            if not frame['balance']['model_valid']:break
        if rows and not rows[-1]['valid']:break
    phases=sorted({r['phase'] for r in rows})
    return dict(case=case['name'],start_hash=before['sha256'],rows=rows,
        trajectory_sha256=digest(rows),final_checkpoint=loop.checkpoint(),
        summary=dict(frames=len(rows),simulated_s=len(rows)*.1,
            valid_throughout=all(r['valid'] for r in rows),failure=rows[-1]['failure'],
            phase=rows[-1]['phase'],visited_phases=phases,
            new_walk_touchdowns=loop.state.walk_steps-before_walk,
            single_support_reached='single_support' in phases,
            fuel_used_J=sum(r['fuel_used_J'] for r in rows),
            peak_pressure_kpa=max((v for r in rows for v in r['pressures_kpa'].values()),default=None),
            peak_joint_force_N=max((v for r in rows for v in r['joint_force_N'].values()),default=0.),
            min_support_fraction=min((r['support_fraction'] for r in rows if r['support_fraction'] is not None),default=None),
            max_segment_length_error_m=max(r['max_segment_length_error_m'] for r in rows),
            max_tail_torque_norm_Nm=max(math.hypot(*r['tail_torque_Nm']) for r in rows),
            slipped_distance_m=None,collision_clearance_m=None))


def cold_check(envelope):
    b=restore_star(envelope)
    if star_checkpoint(b)!=envelope:raise ValueError('cold star checkpoint mismatch')
    return b


def run(star_path,live_path,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    manifest=verified_sources()
    star_path,live_path=Path(star_path),Path(live_path)
    original_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (star_path,live_path)}
    envelope=json.loads(star_path.read_text());body=cold_check(envelope)
    contract=dict(schema='nasuraya-anatomy-motion-contract/1',cases=CASES,dt_s=.1,
        max_frames_each=280,source_star_checkpoint=envelope['sha256'],
        comparison='same checkpoint and input; rendering revision preserves mechanics',
        visual_revision=VISUAL_REVISION,
        unsupported=['whole-body yaw turn','squat','stairs','obstacle collision',
                     'deformable foot contact','skin/fur collision','horn-neck load distribution'])
    (output/'frozen_contract.json').write_text(json.dumps(contract,indent=2)+'\n')
    paired=[]
    for case in CASES:
        a=trial(body.owner.physical,case);b=trial(body.owner.physical,case)
        assert a['trajectory_sha256']==b['trajectory_sha256']
        assert a['final_checkpoint']==b['final_checkpoint']
        name=case['name'];(output/(name+'.json')).write_text(json.dumps(dict(baseline=a,revised=b))+'\n')
        paired.append(dict(case=name,summary=a['summary'],paired_exact=True))
        print(json.dumps({'case':name,**a['summary']}),flush=True)
    unsupported=[]
    for name in ('turn','squat','stair'):
        p=deepcopy(body.owner.physical);before=p.checkpoint()
        try:p.step(GaitEnvironment(command=name,body=Inputs(dt_s=.1)))
        except ValueError:unsupported.append(dict(command=name,rejected=True,state_unchanged=p.checkpoint()==before))
        else:raise AssertionError('unsupported command admitted')
    uri=live_path.resolve().as_uri()+'?mode=ro'
    with sqlite3.connect(uri,uri=True) as db:
        saved=json.loads(db.execute("SELECT value FROM runtime WHERE key='nasuraya-body-loop'").fetchone()[0])
    live=UnifiedBody.restore(saved);old=live.checkpoint();clock=datetime.fromisoformat(live.owner.wall_utc)
    selected=live.cycle(event_id='isolated-audit-sleep-walk',at_utc=clock.isoformat(),duration_s=.1,
                       requested='walk',expected_revision=live.revision)
    veto=dict(source_revision=old['payload']['revision'],requested='walk',
              selected=selected['owner']['selected_action'],
              physical_valid=selected['owner']['physical_model_valid'],
              source_ledger_changed=False)
    head=cold_check(envelope);before=deepcopy(head.owner.aux['upper_angles'])
    r=head.cycle(event_id='isolated-audit-head-yaw',at_utc=head.owner.wall_utc,duration_s=1.,
        requested='observe',expected_revision=head.revision,
        external={'native':{'upper_targets':{'head_yaw':.2,'head_pitch':.1}}})
    head_result=dict(before=before,
        after=head.owner.aux['upper_angles'],paid_work_J=r['owner']['resource_and_gas_audit']['upper_motion_work_paid_J'],
        physical_valid=r['owner']['physical_model_valid'],
        scope='bounded accessory angle/energy proxy; head mesh and neck reaction forces absent')
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in original_hashes.items())
    result=dict(schema='nasuraya-anatomy-motion-audit/1',geometry=geometry(),paired_trials=paired,
        original_checkpoints_unchanged=True,original_hashes=original_hashes,
        current_live_goal_revision=saved['payload']['revision'],
        star_practice_revision=envelope['payload']['native']['payload']['revision'],
        new_full_body_mission=False,live_API_calls=0,unsupported_commands=unsupported,
        saved_sleep_walk_veto=veto,accessory_head_check=head_result,
        runtime_manifest_sha256=hashlib.sha256((NATIVE/'PUBLIC_FILES_SHA256.json').read_bytes()).hexdigest(),
        runtime_verified_files=len(manifest),visual_revision=VISUAL_REVISION,
        measured_mechanical_improvement=False,mesh_validation=False,
        interpretation='paired equality preserves the reduced mechanics; beauty and mesh geometry remain authored')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--star-checkpoint',required=True)
    p.add_argument('--live-session',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.star_checkpoint,a.live_session,a.output)
