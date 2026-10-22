"""Free-base feedback balance and a bounded kinematic stepping experiment.

Uses only existing, torque-limited joint motors. No welds, root actuator, state
resets during rollout, or helper forces. The controller reads simulator state;
state estimation and learned locomotion remain separate work.
"""
from pathlib import Path
import argparse, gzip, hashlib, json, math
import numpy as np
import mujoco
import yaml
from scipy.linalg import solve_discrete_are
from scipy.optimize import least_squares
from .resize import SMALL
from .build import ROOT
from .evaluate import load, controller_arrays


class BalanceController:
    def __init__(self, model):
        self.m = model
        spec = yaml.safe_load((SMALL/'robot.yaml').read_text())
        self.qa, self.va, self.kp, self.kd, self.eff = controller_arrays(model, spec)
        d = mujoco.MjData(model)
        def residual(x):
            d.qpos[:] = model.qpos0
            d.qpos[2] += x[0]
            mujoco.mju_axisAngle2Quat(d.qpos[3:7], np.array([0., 1., 0.]), x[1])
            d.qvel[:] = 0
            d.qacc[:] = 0
            mujoco.mj_inverse(model, d)
            return d.qfrc_inverse[[2, 4]].copy()
        fit = least_squares(residual, [-.00008, 0.], diff_step=1e-3,
                            xtol=1e-12, gtol=1e-10, ftol=1e-12,
                            max_nfev=100, x_scale=[.0001, .0001])
        residual(fit.x)
        self.q0 = d.qpos.copy()
        # Actuator insertion order differs from the XML joint/DOF order.
        self.u0 = d.qfrc_inverse[self.va].copy()
        root_residual = float(np.max(np.abs(d.qfrc_inverse[:6])))
        if not fit.success or root_residual > 1e-5 or np.any(abs(self.u0) > self.eff):
            raise RuntimeError('No feasible unsupported static equilibrium found')
        d.ctrl[:] = self.u0
        mujoco.mj_forward(model, d)
        equilibrium_acceleration = float(np.max(np.abs(d.qacc)))
        if equilibrium_acceleration > 1e-4:
            raise RuntimeError('Inverse torque mapping does not balance forward dynamics')
        n = 2*model.nv
        A, B = np.zeros((n,n)), np.zeros((n,model.nu))
        mujoco.mjd_transitionFD(model, d, 1e-6, True, A, B, None, None)
        cost = np.r_[np.ones(6)*1000, np.ones(model.nv-6)*10,
                     np.ones(6)*10, np.ones(model.nv-6)]
        # Protect the compliant toe/ball joints instead of increasing motor power.
        for j in range(1, model.njnt):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j)
            if name.startswith(('toe_flex', 'mtp_')):
                cost[model.jnt_dofadr[j]] = 10000
                cost[model.nv+model.jnt_dofadr[j]] = 10
        Q = np.diag(cost)
        R = np.eye(model.nu)*.01
        P = solve_discrete_are(A, B, Q, R)
        self.K = np.linalg.solve(R+B.T@P@B, B.T@P@A)
        radius = float(np.max(abs(np.linalg.eigvals(A-B@self.K))))
        if radius >= 1:
            raise RuntimeError('Linearized closed loop is unstable')
        self.design = {'static_free_root_residual_max': root_residual,
                       'static_forward_acceleration_max': equilibrium_acceleration,
                       'linearized_closed_loop_spectral_radius': radius,
                       'equilibrium_root_height_m': float(self.q0[2]),
                       'equilibrium_root_pitch_rad': float(fit.x[1]),
                       'max_feedforward_torque_nm': float(max(abs(self.u0))),
                       'state_cost_diagonal': cost.tolist(), 'control_cost_diagonal': .01,
                       'state_feedback': 'full simulator qpos/qvel, not an observer',
                       'torque_limits_unchanged': True,
                       'root_actuator_or_weld': False}
        self.error = np.zeros(model.nv)

    def command(self, data, mode='feedback', reference=None, velocity=None):
        qref = self.q0 if reference is None else reference
        vref = np.zeros(self.m.nv) if velocity is None else velocity
        if mode == 'legacy_pd':
            raw = -self.kp*data.qpos[self.qa] - self.kd*data.qvel[self.va]
        elif mode == 'feedforward_only':
            raw = self.u0.copy()
        else:
            mujoco.mj_differentiatePos(self.m, self.error, 1., qref, data.qpos)
            raw = self.u0-self.K@np.r_[self.error, data.qvel-vref]
        lower, upper = self.m.actuator_ctrlrange.T
        return np.clip(raw, lower, upper), float(np.mean((raw < lower) | (raw > upper)))


def stepping_reference(model, controller, seconds=6., interval=.01):
    """Authored slow stepping probe, NOT a learned/validated running gait.

    IK solves six foot pose constraints per leg; lateral weight transfer precedes
    each alternating 4 cm step. Reference is supplied to the standing regulator.
    Failure is recorded rather than relabelled as running.
    """
    d = mujoco.MjData(model)
    d.qpos[:] = controller.q0
    mujoco.mj_forward(model,d)
    sites = [mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_SITE,'foot_contact_'+s) for s in ['L','R']]
    positions = [d.site_xpos[s].copy() for s in sites]
    initial_rot = [d.site_xmat[s].reshape(3,3).copy() for s in sites]
    legs = []
    for side in ['L','R']:
        names = ['hip_yaw_', 'hip_roll_', 'hip_pitch_', 'knee_', 'hock_pitch_', 'hock_roll_', 'mtp_']
        joints = [mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,n+side) for n in names]
        legs.append((model.jnt_qposadr[joints], model.jnt_range[joints]))
    frames = []
    max_error = 0.
    for t in np.arange(0,seconds+interval/2,interval):
        d.qpos[:] = controller.q0
        targets = [p.copy() for p in positions]
        elapsed = max(t-2.,0.)
        step = int(elapsed/1.2)
        phase = (elapsed/1.2)%1
        swing = step%2
        # Completed steps advance alternate feet. Initial feet share x=0.
        for side in range(2):
            count = (step+1-side)//2
            targets[side][0] += .04*max(count,0)
        progress = np.clip((phase-.25)/.6,0,1)
        smooth = progress*progress*(3-2*progress)
        if t > 2:
            targets[swing][0] += .04*smooth
            targets[swing][2] += .025*math.sin(math.pi*progress)**2
            d.qpos[0] += .02*(step+smooth)
            # Shift over the opposite, supporting foot before lifting.
            d.qpos[1] = (-1 if swing==0 else 1)*.09*math.sin(math.pi*phase)**2
        for s,(qids, limits) in enumerate(legs):
            def error(q):
                d.qpos[qids] = q
                mujoco.mj_forward(model,d)
                rot = d.site_xmat[sites[s]].reshape(3,3)
                orientation = .5*sum(np.cross(initial_rot[s][:,i],rot[:,i]) for i in range(3))
                return np.r_[d.site_xpos[sites[s]]-targets[s], orientation*.2, q*.001]
            fit = least_squares(error, np.zeros(len(qids)), bounds=(limits[:,0]+.001,limits[:,1]-.001), max_nfev=30)
            residual = error(fit.x)
            max_error = max(max_error,float(np.linalg.norm(residual[:3])))
        frames.append(d.qpos.copy())
    return np.asarray(frames), interval, max_error


def run_trial(model, controller, *, label, seconds=20., mode='feedback', force=(0.,0.),
              friction=None, dt=None, gait=None, capture=False):
    original_dt = model.opt.timestep
    original_friction = model.geom_friction.copy()
    if dt is not None: model.opt.timestep = dt
    if friction is not None: model.geom_friction[:,0] = friction
    d = mujoco.MjData(model)
    # Identical initial state as v02's failed legacy experiment, not equilibrium.
    d.qpos[:] = model.qpos0
    d.qpos[2] += .005
    mujoco.mj_forward(model,d)
    floor = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'floor')
    torso = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'torso')
    nonfeet = set()
    first_nonfoot = None
    tilt_max = 0.
    height_min = float(d.qpos[2])
    torque_peak = 0.
    saturation = 0.
    warning = False
    both_airborne_steps = 0
    unilateral_steps = 0
    max_soft_limit = 0.
    trace, poses = [], []
    initial_xy = d.qpos[:2].copy()
    applied_impulse = np.zeros(2)
    tail_speed = []
    steps = round(seconds/model.opt.timestep)
    for i in range(steps):
        reference = velocity = None
        if gait is not None:
            frames, spacing, _ = gait
            j = min(int(d.time/spacing),len(frames)-2)
            reference = frames[j]
            velocity = np.zeros(model.nv)
            mujoco.mj_differentiatePos(model,velocity,spacing,frames[j],frames[j+1])
        command,sat = controller.command(d,mode,reference,velocity)
        d.ctrl[:] = command
        saturation += sat
        torque_peak = max(torque_peak,float(max(abs(command))))
        d.xfrc_applied[:] = 0
        if 3 <= d.time < 3.2:
            # External force is solely a declared test disturbance on torso.
            d.xfrc_applied[torso,:2] = force
            applied_impulse += np.array(force)*model.opt.timestep
        mujoco.mj_step(model,d)
        mujoco.mj_forward(model,d)
        warning = (not np.isfinite(d.qpos).all() or any(w.number for w in d.warning))
        if warning: break
        contacts = set()
        for c in d.contact[:d.ncon]:
            if floor in [c.geom1,c.geom2]:
                other = c.geom2 if c.geom1==floor else c.geom1
                name = mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,other)
                if name.startswith(('ball_', 'toe_pad_')):
                    contacts.add('L' if '_L' in name else 'R')
                else:
                    nonfeet.add(name)
                    if first_nonfoot is None: first_nonfoot = float(d.time)
        both_airborne_steps += len(contacts)==0
        unilateral_steps += len(contacts)==1
        tilt = math.acos(np.clip(d.xmat[1].reshape(3,3)[2,2],-1,1))
        tilt_max = max(tilt_max,tilt)
        height_min = min(height_min,float(d.qpos[2]))
        qj = d.qpos[model.jnt_qposadr[1:]]
        max_soft_limit = max(max_soft_limit,float(np.maximum(model.jnt_range[1:,0]-qj,qj-model.jnt_range[1:,1]).max()))
        if d.time > seconds-2: tail_speed.append(float(np.max(abs(d.qvel))))
        if i%max(1,round(.05/model.opt.timestep))==0:
            trace.append({'t':float(d.time),'pelvis_xyz':d.qpos[:3].tolist(),
                          'tilt_deg':math.degrees(tilt),'feet_contact':sorted(contacts)})
            if capture: poses.append(d.qpos.copy())
        if first_nonfoot is not None or d.qpos[2] < .7*controller.q0[2] or tilt > math.radians(50):
            break
    completed = float(d.time) >= seconds-model.opt.timestep/2
    stood = bool(completed and not warning and not nonfeet and height_min>.8*controller.q0[2] and tilt_max<math.radians(20) and max_soft_limit<=.02)
    tail_speed_max = max(tail_speed) if tail_speed else None
    result = {'label':label,'mode':mode,'requested_seconds':seconds,'executed_seconds':float(d.time),
              'initial_state':'v02 neutral with 5 mm initial gap, zero velocity',
              'force_on_torso_n':list(force),'force_interval_s':[3.,3.2],
              'applied_impulse_xy_ns':applied_impulse.tolist(),'friction':float(model.geom_friction[floor,0]),
              'timestep_s':float(model.opt.timestep),'standing_pass':stood,
              'settled_pass':bool(stood and tail_speed_max is not None and tail_speed_max<.1),
              'final_pelvis_xyz_m':d.qpos[:3].tolist(),'min_pelvis_height_m':height_min,
              'max_tilt_deg':math.degrees(tilt_max),'peak_motor_torque_nm':torque_peak,
              'actuator_saturation_fraction':saturation/(i+1),'warnings':warning,
              'nonfoot_ground_geoms':sorted(nonfeet),'first_nonfoot_time_s':first_nonfoot,
              'last_2s_max_generalized_speed':tail_speed_max,
              'final_displacement_xy_m':(d.qpos[:2]-initial_xy).tolist(),
              'both_feet_airborne_seconds':both_airborne_steps*model.opt.timestep,
              'single_foot_contact_seconds':unilateral_steps*model.opt.timestep,
              'max_joint_limit_soft_violation_rad':max_soft_limit,
              'trace':trace}
    model.opt.timestep = original_dt
    model.geom_friction[:] = original_friction
    return (result,poses) if capture else result


def save_results(result, output):
    """Keep full precision traces losslessly, without a megabyte of JSON indent."""
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = dict(result)
    summary['trials'] = [dict(t) for t in result['trials']]
    traces = [{'label':t['label'], 'trace':t.pop('trace')} for t in summary['trials']]
    trace_path = output.with_name(output.stem+'-traces.json.gz')
    trace_path.write_bytes(gzip.compress(json.dumps(traces,separators=(',',':')).encode(),mtime=0))
    summary['traces_file'] = trace_path.name
    output.write_text(json.dumps(summary,indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/articulated-balance-v01/results.json')
    args = parser.parse_args()
    model,_ = load(SMALL)
    controller = BalanceController(model)
    cases = [dict(label='legacy_pd',mode='legacy_pd',seconds=5),
             dict(label='feedforward_only',mode='feedforward_only',seconds=20),
             dict(label='standing_30s',seconds=30),
             dict(label='forward_push',force=(30,0)),dict(label='backward_push',force=(-30,0)),
             dict(label='left_push',force=(0,30)),dict(label='right_push',force=(0,-30)),
             dict(label='strong_forward_push',force=(100,0)),
             dict(label='diagonal_push_holdout',force=(-40,40)),
             dict(label='lower_friction_holdout',force=(0,30),friction=.4),
             dict(label='half_timestep_holdout',force=(30,0),dt=.0005)]
    result = {'scope':'Torque-limited articulated balance, not learned running',
              'model_sha256':hashlib.sha256((SMALL/'nasuraya.xml').read_bytes()).hexdigest(),
              'design':controller.design,'acceptance':{'standing':'Full duration; only foot ground contact; pelvis height >80% reference; tilt <20 degrees; no warnings; soft joint-limit excess <=0.02 rad.',
                  'settled':'Standing criteria plus last 2 seconds maximum absolute generalized speed <0.1 (m/s for translation, rad/s for joints).',
                  'no_running_claim':'A slow stepping reference is a separate transfer probe, never counted as a standing pass or running.'},
              'trials':[]}
    for case in cases:
        trial = run_trial(model,controller,**case)
        result['trials'].append(trial)
        print(json.dumps({k:v for k,v in trial.items() if k!='trace'}),flush=True)
    gait = stepping_reference(model,controller)
    trial = run_trial(model,controller,label='slow_stepping_transfer_probe',seconds=6,gait=gait)
    trial['reference_max_foot_position_residual_m'] = gait[2]
    trial['validated_running'] = False
    trial['note'] = 'Standing LQR applied to alternating 4 cm steps / 2.5 cm foot lift; no gait-policy training.'
    result['trials'].append(trial)
    print(json.dumps({k:v for k,v in trial.items() if k!='trace'}),flush=True)
    save_results(result,args.output)

if __name__=='__main__':main()
