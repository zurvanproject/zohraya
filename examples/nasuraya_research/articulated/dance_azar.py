"""Azar dance study: authored beat score executed on the unchanged v03 body.

Only joint torques enter mj_step. References are never imposed on the live body.
This is an isolated, full-state-feedback experiment, not a trained dance policy,
photographic avatar, or native Tadash migration.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import mujoco
import numpy as np

from .balance import BalanceController
from .canon_trial import CANDIDATE
from .evaluate import load
from .stepping import ContactController

BPM = 96.0
INTRO = 2.0
BARS = 8
BEATS = 32
SETTLE = 4.0
PHRASES = [
    'listen', 'open', 'left_arc', 'right_arc', 'open_sky',
    'gather', 'left_wave', 'right_wave', 'return',
]
# (left roll, right roll, left pitch, right pitch, left elbow, right elbow, waist yaw)
KEYS = np.array([
    [0, 0, 0, 0, 0, 0, 0],
    [.75, -.75, -.12, -.12, -.45, -.45, 0],
    [1.15, -.45, -.15, -.35, -.65, -1.0, .12],
    [.45, -1.15, -.35, -.15, -1.0, -.65, -.12],
    [1.35, -1.35, -.15, -.15, -.40, -.40, 0],
    [.35, -.35, -.65, -.65, -1.10, -1.10, 0],
    [.95, -.55, -.55, -.20, -.55, -.90, .10],
    [.55, -.95, -.20, -.55, -.90, -.55, -.10],
    [0, 0, 0, 0, 0, 0, 0],
], dtype=float)
KEY_JOINTS = ['shoulder_roll_L', 'shoulder_roll_R', 'shoulder_pitch_L',
              'shoulder_pitch_R', 'elbow_L', 'elbow_R', 'waist_yaw']
CRITERIA = {'complete_duration': True, 'no_nonfoot_ground_contact': True,
            'no_self_collision': True, 'max_pelvis_tilt_deg': 8.0,
            'max_foot_anchor_drift_m': .015, 'min_pelvis_height_ratio': .90,
            'max_joint_soft_limit_excess_rad': .02,
            'both_feet_loaded_fraction_min': .99,
            'last_second_max_generalized_speed': .05,
            'min_shoulder_range_rad': .40, 'numerically_finite': True}


def smooth(x):
    x = float(np.clip(x, 0, 1))
    return x*x*x*(10 + x*(-15 + 6*x))


def duration(bpm=BPM):
    if not math.isfinite(bpm) or not 48 <= bpm <= 144:
        raise ValueError('Tempo must be finite and between 48 and 144 BPM')
    return INTRO + BEATS*60/bpm + SETTLE


def score(t, bpm=BPM, amplitude=1.0):
    """C2 pose targets; complete eight-bar score, then explicit quiet settling."""
    beat = np.clip((t-INTRO)*bpm/60, 0, BEATS)
    bar = min(int(beat//4), 7)
    p = smooth((beat-4*bar)/4)
    v = amplitude*((1-p)*KEYS[bar] + p*KEYS[bar+1])
    joints = dict(zip(KEY_JOINTS, map(float, v)))
    env = math.sin(math.pi*beat/BEATS)**2
    phase = 2*math.pi*beat/8
    joints.update({'neck_yaw': amplitude*.16*env*math.sin(phase),
                   'neck_pitch': amplitude*.045*env*math.sin(phase/2),
                   'waist_roll': amplitude*.025*env*math.sin(phase),
                   'waist_pitch': amplitude*.025*env*math.sin(phase/2)})
    for s, sign in [('L', 1), ('R', -1)]:
        joints['wrist_roll_'+s] = sign*amplitude*.18*env*math.sin(phase)
        joints['wrist_pitch_'+s] = amplitude*.14*env*math.cos(phase)
        for finger in range(1, 6):
            joints[f'finger_flex_{s}_{finger}'] = amplitude*.12*env
    for link in range(1, 5):
        joints[f'tail_yaw_{link}'] = amplitude*.11*env*math.sin(phase-.45*link)
        joints[f'tail_pitch_{link}'] = amplitude*.035*env*math.sin(phase/2-.3*link)
    com_offset = np.array([0., amplitude*.010*env*math.sin(phase),
                           -amplitude*.004*env*(1-math.cos(phase))/2])
    return joints, com_offset, float(beat), PHRASES[min(int(beat//4), 8)]


def run(output, bpm=BPM, amplitude=1.0, friction=.6, dt=.001, seconds=None):
    total = duration(bpm)
    if not 0 < amplitude <= 1.1 or not .2 <= friction <= 1.2:
        raise ValueError('Amplitude or friction outside this study scope')
    if dt not in (.001, .0005):
        raise ValueError('Use a 1 ms or 0.5 ms physics step')
    if seconds is not None and not 0 < seconds <= total:
        raise ValueError('A diagnostic duration must be positive and no longer than the score')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    protocol = {'name':'Nasuraya / Azar dance v0.1', 'bpm':bpm,
        'meter':'4/4', 'bars':BARS, 'beats':BEATS, 'amplitude':amplitude,
        'intro_s':INTRO, 'settle_s':SETTLE, 'duration_s':duration(bpm),
        'friction':friction, 'timestep_s':dt, 'control_period_s':.005,
        'criteria':CRITERIA, 'keys':KEYS.tolist(), 'key_joints':KEY_JOINTS,
        'scope':'Authored score + existing torque-constrained contact controller.',
        'root_actuator':False, 'root_weld':False, 'live_pose_overwrites':False,
        'external_help_forces':False, 'native_body_migration':False,
        'model_sha256':hashlib.sha256((CANDIDATE/'nasuraya.xml').read_bytes()).hexdigest()}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    m, d = load(CANDIDATE)
    assert m.neq == 0 and np.all(m.actuator_trnid[:,0] > 0)
    m.opt.timestep = dt
    m.geom_friction[:,0] = friction
    balance = BalanceController(m, CANDIDATE)
    d.qpos[:] = balance.q0
    mujoco.mj_forward(m,d)
    controller = ContactController(m,d,geometry_support=True)
    initial_q = d.qpos.copy()
    target_q = d.qpos.copy()
    com0 = d.subtree_com[1].copy()
    anchors = controller.anchors.copy()
    jmap = {mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_JOINT,i):i for i in range(1,m.njnt)}
    floor = mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'floor')
    pelvis = mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,'pelvis')
    body_names = [mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,i) for i in range(m.nbody)]
    shoulder_q = [m.jnt_qposadr[jmap['shoulder_roll_'+s]] for s in ['L','R']]
    seconds = duration(bpm) if seconds is None else seconds
    control_stride = round(.005/dt)
    capture_stride = round(.025/dt)
    rows, poses, velocities, times, control_rows = [], [], [], [], []
    nonfeet, self_contacts = set(), set()
    max_tilt = max_slip = max_limit = peak_torque = 0.
    min_height = float(d.qpos[2])
    both_loaded = 0
    last_speeds = []
    warnings = False
    failure = None
    observed_error = []
    hand_positions = []
    for i in range(round(seconds/dt)):
        if i % control_stride == 0:
            targets, offset, beat, phrase = score(d.time,bpm,amplitude)
            target_q[:] = initial_q
            for name, value in targets.items():
                target_q[m.jnt_qposadr[jmap[name]]] += value
            controller.q0[:] = target_q
            try:
                d.ctrl[:] = controller.command(d,com0+offset,anchors,[True,True])
            except RuntimeError as ex:
                failure = 'QP: '+str(ex)
                break
            observed_error.append(float(np.mean((d.qpos[shoulder_q]-target_q[shoulder_q])**2)))
        mujoco.mj_step(m,d)
        mujoco.mj_forward(m,d)
        if not np.isfinite(d.qpos).all() or any(w.number for w in d.warning):
            warnings = True
            failure = 'numerical_warning'
            break
        rot = d.xmat[pelvis].reshape(3,3)
        tilt = math.degrees(math.acos(np.clip(rot[2,2],-1,1)))
        max_tilt = max(max_tilt,tilt)
        min_height = min(min_height,float(d.qpos[2]))
        slip = float(np.max(np.linalg.norm(d.site_xpos[controller.sites]-anchors,axis=1)))
        max_slip = max(max_slip,slip)
        qj = d.qpos[m.jnt_qposadr[1:]]
        max_limit = max(max_limit,float(np.maximum(m.jnt_range[1:,0]-qj,qj-m.jnt_range[1:,1]).max()))
        peak_torque = max(peak_torque,float(np.max(abs(d.ctrl))))
        loads = np.zeros(2)
        for ci,c in enumerate(d.contact[:d.ncon]):
            gn = [mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,int(g)) for g in [c.geom1,c.geom2]]
            if floor in [c.geom1,c.geom2]:
                name = gn[1] if c.geom1 == floor else gn[0]
                if not name.startswith(('ball_','toe_pad_')):
                    nonfeet.add(name)
                else:
                    f = np.zeros(6)
                    mujoco.mj_contactForce(m,d,ci,f)
                    side = 0 if '_L' in name else 1
                    loads[side] += max(0.,float(f[0]))
            elif c.dist < -.001:
                self_contacts.add(tuple(sorted(gn)))
        both_loaded += bool(np.all(loads>1))
        if d.time > seconds-1:
            last_speeds.append(float(np.max(abs(d.qvel))))
        if i % capture_stride == 0:
            poses.append(d.qpos.copy()); velocities.append(d.qvel.copy()); times.append(float(d.time))
            control_rows.append(d.ctrl.copy())
            rows.append({'t':round(float(d.time),6),'beat':round(beat,5),'phrase':phrase,
                         'pelvis_tilt_deg':tilt,'foot_drift_m':slip,'foot_normal_n':loads.tolist(),
                         'com_m':d.subtree_com[1].tolist()})
            hand_positions.append([d.xpos[body_names.index('hand_'+s)].copy() for s in ['L','R']])
        if nonfeet or min_height < .8*initial_q[2] or tilt>20:
            failure = 'physical_guard'
            break
    completed = bool(d.time >= seconds-dt/2)
    ranges = np.ptp(np.array(poses)[:,shoulder_q],axis=0) if poses else np.zeros(2)
    final_speed = max(last_speeds,default=float('inf'))
    result = {'executed_seconds':float(d.time),'requested_seconds':seconds,'complete':completed,
        'model_mass_kg':float(m.body_mass.sum()),'actuated_joints':m.nu,
        'max_pelvis_tilt_deg':max_tilt,'max_foot_anchor_drift_m':max_slip,
        'min_pelvis_height_ratio':min_height/initial_q[2],
        'max_joint_soft_limit_excess_rad':max_limit,'peak_motor_torque_nm':peak_torque,
        'both_feet_loaded_fraction':both_loaded/(i+1),'nonfoot_ground_geoms':sorted(nonfeet),
        'self_contact_pairs':sorted(self_contacts),'numerical_warnings':warnings,
        'last_second_max_generalized_speed':final_speed,
        'shoulder_range_rad':ranges.tolist(),'shoulder_target_rmse_rad':float(np.sqrt(np.mean(observed_error))),
        'qp_solves':controller.solves,'qp_inaccurate':controller.inaccurate,
        'qp_max_constraint_residual':controller.max_residual,'failure':failure,
        'torque_limits_unchanged':True,'root_actuator_or_weld':False,
        'live_pose_overwrites':False,'external_help_forces':False,
        'performance_scope':'Only this recorded two-foot, flat-ground dance trial.',
        'diagnostic_partial_score': seconds < duration(bpm)}
    result['accepted'] = bool(completed and failure is None and not nonfeet and not self_contacts and
        not warnings and max_tilt<CRITERIA['max_pelvis_tilt_deg'] and max_slip<CRITERIA['max_foot_anchor_drift_m'] and
        result['min_pelvis_height_ratio']>CRITERIA['min_pelvis_height_ratio'] and
        max_limit<=CRITERIA['max_joint_soft_limit_excess_rad'] and
        result['both_feet_loaded_fraction']>=CRITERIA['both_feet_loaded_fraction_min'] and
        final_speed<CRITERIA['last_second_max_generalized_speed'] and min(ranges)>.40)
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'trace.json').write_text(json.dumps(rows,separators=(',',':'))+'\n')
    np.savez_compressed(output/'poses.npz',qpos=np.array(poses),qvel=np.array(velocities),
                        time=np.array(times),ctrl=np.array(control_rows),hands=np.array(hand_positions))
    print(json.dumps(result),flush=True)
    return result


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--bpm',type=float,default=BPM)
    ap.add_argument('--amplitude',type=float,default=1.)
    ap.add_argument('--friction',type=float,default=.6)
    ap.add_argument('--dt',type=float,default=.001)
    ap.add_argument('--seconds',type=float)
    a=ap.parse_args()
    run(a.output,a.bpm,a.amplitude,a.friction,a.dt,a.seconds)
