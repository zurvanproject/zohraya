"""Opt-in landing/settling experiment; never a native-body controller.

The two numerical routines below are a deliberately isolated fork of PR #87
stepping.py at d07c8199d90004951c747e3b3197e60ca1de8bf9. Keeping the frozen
controller untouched preserves its source-bound checkpoints and replay tools.
Shared geometry/contact helpers are imported, not reimplemented. Timing, QP
constraints, torque limits, swing, lift and landing guards remain identical.
"""
from pathlib import Path
import math
import numpy as np
import mujoco
import osqp
from scipy import sparse
from .balance import BalanceController
from .evaluate import load
from .canon_trial import CANDIDATE
from .stepping import (ContactController as LegacyController, smooth,
                       contact_state, sole_clearance, can_lift)

MODES = ('unchanged', 'landing', 'tail', 'combined')


def terminal_blend(phase, step, requested_steps, elapsed, timing):
    """Use only the final scheduled landing; never extend a phase."""
    if phase == 'landing' and step == requested_steps - 1:
        return smooth(elapsed / timing)
    return 1. if phase in ('recenter', 'settle') else 0.


class ContactController(LegacyController):
    def __init__(self, m, d, geometry_support=False):
        super().__init__(m, d, geometry_support=geometry_support)
        self.tail_blend = 0.
        self.tail_dofs = np.array([int(m.jnt_dofadr[j]) for j in range(m.njnt)
            if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or '').startswith('tail_')])

    def command(self, d, com, targets, support):
        m = self.m
        n = self.n
        N = n + 12
        J, jc, jr = self.jacobians(d)
        allj = np.vstack([*J, jc, jr])
        jd = np.zeros(allj.shape[0]) if self.prev is None else (allj - self.prev) / self.control_dt @ d.qvel
        self.prev = allj
        M = np.zeros((n, n))
        mujoco.mj_fullM(m, d, M)
        h = d.qfrc_bias - d.qfrc_passive
        JT = np.hstack([j.T for j in J]) * 100
        torque = np.hstack([M[self.va], -JT[self.va]])
        eq = np.hstack([M[:6], -JT[:6]]) / 100
        AA = [eq, torque]
        lo = [-h[:6] / 100, m.actuator_ctrlrange[:, 0] - h[self.va]]
        hi = [-h[:6] / 100, m.actuator_ctrlrange[:, 1] - h[self.va]]
        P = np.eye(N) * 1e-05
        q = np.zeros(N)

        def task(A, b, w):
            nonlocal P, q
            z = np.zeros((len(b), N))
            z[:, :n] = A
            P += w * z.T @ z
            q -= w * z.T @ b
        e = np.zeros(n)
        mujoco.mj_differentiatePos(m, e, 1, d.qpos, self.q0)
        task(np.eye(n)[6:], (50 * e - 12 * d.qvel)[6:], 0.1)
        # Extra soft tail task, inside the same torque-constrained QP.
        # Same neutral posture stiffness, increased damping and priority.
        # Fade in over the existing final landing; no state/velocity reset.
        if self.tail_blend:
            td = self.tail_dofs
            task(np.eye(n)[td], 50 * e[td] - 20 * d.qvel[td], self.tail_blend)

        task(jc, 60 * (com - d.subtree_com[1]) - 15 * jc @ d.qvel - jd[12:15], 10)
        rot = d.xmat[1].reshape(3, 3)
        re = 0.5 * sum((np.cross(rot[:, i], self.rot0[:, i]) for i in range(3)))
        task(jr, 150 * re - 25 * jr @ d.qvel - jd[15:18], 10)
        for s in range(2):
            site = self.sites[s]
            rot = d.site_xmat[site].reshape(3, 3)
            re = 0.5 * sum((np.cross(rot[:, i], np.eye(3)[:, i]) for i in range(3)))
            des = np.r_[300 * (targets[s] - d.site_xpos[site]), 200 * re] - 35 * J[s] @ d.qvel - jd[s * 6:s * 6 + 6]
            task(J[s], des, 100 if support[s] else 10)
            C = []
            cl = []
            ch = []

            def bound(coeff, l, u):
                row = np.zeros(N)
                row[n + 6 * s:n + 6 * s + 6] = coeff
                C.append(row)
                cl.append(l)
                ch.append(u)
            if not support[s]:
                for k in range(6):
                    v = np.zeros(6)
                    v[k] = 1
                    bound(v, 0, 0)
            else:
                cap = 20 if self.load_fractions is None else (2 * self.load_fractions[s] * m.body_mass.sum() * 9.81 + 30) / 100
                bound([0, 0, 1, 0, 0, 0], 0, cap)
                if self.load_fractions is not None:
                    k = n + 6 * s + 2
                    P[k, k] += 0.1
                    q[k] -= 0.1 * self.load_fractions[s] * m.body_mass.sum() * 9.81 / 100
                for axis in [0, 1]:
                    for sign in [-1, 1]:
                        v = np.zeros(6)
                        v[axis] = sign
                        v[2] = -min(0.5, float(m.geom_friction[0, 0]) * 0.85)
                        bound(v, -np.inf, 0)
                xmin,xmax,ymin,ymax = ([-.12,-.015,-.075,.075]
                    if self.support_bounds is None else self.support_bounds[s])
                bound([0, 0, -ymax, 1, 0, 0], -np.inf, 0)
                bound([0, 0, ymin, -1, 0, 0], -np.inf, 0)
                bound([0, 0, xmin, 0, 1, 0], -np.inf, 0)
                bound([0, 0, -xmax, 0, -1, 0], -np.inf, 0)
                bound([0, 0, -0.02, 0, 0, 1], -np.inf, 0)
                bound([0, 0, -0.02, 0, 0, -1], -np.inf, 0)
            AA.append(np.array(C))
            lo.append(cl)
            hi.append(ch)
        problem = osqp.OSQP()
        problem.setup(P=sparse.csc_matrix(P), q=q, A=sparse.csc_matrix(np.vstack(AA)), l=np.concatenate(lo), u=np.concatenate(hi), verbose=False, eps_abs=1e-05, eps_rel=1e-05, max_iter=5000, polishing=True)
        if self.previous_solution is not None:
            problem.warm_start(x=self.previous_solution)
        r = problem.solve(raise_error=False)
        if r.info.status_val not in [1, 2]:
            raise RuntimeError(r.info.status)
        violation = max(float(np.max(np.concatenate(lo) - np.vstack(AA) @ r.x)), float(np.max(np.vstack(AA) @ r.x - np.concatenate(hi))))
        if violation > 0.01:
            raise RuntimeError(f'QP constraint residual {violation}')
        self.max_residual = max(self.max_residual, violation)
        self.solves += 1
        self.inaccurate += r.info.status_val == 2
        self.previous_solution = r.x
        self.last_wrenches = r.x[n:].reshape(2, 6) * 100
        return np.clip(torque @ r.x + h[self.va], m.actuator_ctrlrange[:, 0], m.actuator_ctrlrange[:, 1])

def walk_trial(*,label='nominal',steps=6,stride=.06,timing=1.,friction=.6,dt=.001,
               push=0.,capture=False,checkpoint=None,retain_checkpoint=False,
               model_dir=CANDIDATE,geometry_support=True,com_bias_x_m=.006,
               mode="combined"):
    if mode not in MODES:
        raise ValueError("unknown landing experiment mode")
    if checkpoint is not None or retain_checkpoint:
        raise ValueError("landing experiment does not accept or create checkpoints")
    if Path(model_dir).resolve() != CANDIDATE.resolve() or not geometry_support:
        raise ValueError("landing experiment requires the isolated v03 model and geometry support")
    if (type(com_bias_x_m) not in (int,float) or not math.isfinite(com_bias_x_m)
            or abs(com_bias_x_m)>.01):
        raise ValueError('COM bias must be a finite number within 10 mm')
    if com_bias_x_m and not geometry_support:
        raise ValueError('COM bias requires geometry-derived support')
    model_dir=Path(model_dir)
    model,data=load(model_dir)
    model.opt.timestep=dt
    model.geom_friction[:,0]=friction
    from .checkpoint import integration_state, digest
    parameters=dict(stride=stride,timing=timing,friction=friction,dt=dt,push=push)
    if checkpoint is None:
        standing=BalanceController(model,model_dir)
        standing_height=float(standing.q0[2])
        data.qpos[:]=model.qpos0;data.qpos[2]+=.005
        for _ in range(round(2/dt)):
            data.ctrl[:]=standing.command(data)[0]
            mujoco.mj_step(model,data)
        mujoco.mj_forward(model,data)
        controller=ContactController(model,data,geometry_support=geometry_support)
        if controller.support_bounds is not None:
            for bounds in controller.support_bounds:
                target=bounds[:2].mean()+com_bias_x_m
                if not bounds[0]<target<bounds[1]:
                    raise ValueError('COM bias leaves the conservative support pad')
        feet=controller.anchors.copy();previous_com=controller.com0.copy()
        step_offset=0;index=0;initialization_seconds=2.
    initial_feet=feet.copy();initial_root=data.qpos[:3].copy()
    start_time=float(data.time)
    initial_qpos=data.qpos.copy();initial_qvel=data.qvel.copy()
    initial_integration_sha=digest(integration_state(model,data).tolist())
    initial_solves=controller.solves;initial_inaccurate=controller.inaccurate
    trace=[];poses=[];landings=[]
    max_tilt=0.;max_limit=0.;max_torque_fraction=0.;height_min=float(data.qpos[2])
    tilt_squared_time=0.;measured_seconds=0.
    nonfeet=set();failure=None
    current_step=-1;phase='initial';step_stats=None
    impulse=0.
    phase_metrics={}
    final_window_max_speed=0.
    def advance(duration,reference):
        nonlocal max_tilt,max_limit,max_torque_fraction,height_min,failure,index,impulse
        nonlocal tilt_squared_time,measured_seconds,final_window_max_speed
        for local in range(round(duration/dt)):
            com,targets,support=reference(local*dt)
            blend = terminal_blend(phase, current_step, steps, local*dt, timing)
            if mode in ('landing', 'combined') and blend:
                com = com.copy()
                com[0] -= com_bias_x_m * blend
            controller.tail_blend = blend if mode in ('tail', 'combined') else 0.

            try:
                if index%round(controller.control_dt/dt)==0:
                    data.ctrl[:]=controller.command(data,com,targets,support)
            except RuntimeError as error:
                failure='solver: '+str(error);return False
            data.xfrc_applied[:]=0
            # Holdout disturbance during the first swing. Never a support force.
            if current_step==0 and phase=='swing' and .9<local*dt<=1.1:
                torso=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'torso')
                data.xfrc_applied[torso,1]=push;impulse+=push*dt
            mujoco.mj_step(model,data);mujoco.mj_forward(model,data)
            forces,other=contact_state(model,data);nonfeet.update(other)
            tilt=math.acos(float(np.clip(data.xmat[1].reshape(3,3)[2,2],-1,1)))
            tilt_squared_time+=math.degrees(tilt)**2*dt;measured_seconds+=dt
            key=f'{current_step}:{phase}'
            metric=phase_metrics.setdefault(key,dict(seconds=0.,tilt_integral_deg2_s=0.,max_generalized_speed=0.))
            metric['seconds'] += dt
            metric['tilt_integral_deg2_s'] += math.degrees(tilt)**2*dt
            metric['max_generalized_speed'] = max(metric['max_generalized_speed'],float(max(abs(data.qvel))))
            if phase == 'settle' and local*dt >= 1.5:
                final_window_max_speed=max(final_window_max_speed,float(max(abs(data.qvel))))
            max_tilt=max(max_tilt,math.degrees(tilt));height_min=min(height_min,float(data.qpos[2]))
            joints=data.qpos[model.jnt_qposadr[1:]]
            excess=float(np.maximum(model.jnt_range[1:,0]-joints,joints-model.jnt_range[1:,1]).max())
            max_limit=max(max_limit,excess)
            max_torque_fraction=max(max_torque_fraction,float(np.max(abs(data.ctrl)/model.actuator_ctrlrange[:,1])))
            if step_stats is not None and phase=='swing':
                side=step_stats['swing_side'];stance=1-side
                step_stats['min_load_on_stance_n']=min(step_stats['min_load_on_stance_n'],float(forces[stance]))
                if forces[side]<1:
                    step_stats['air_time_s']+=dt
                    step_stats['peak_whole_sole_clearance_m']=max(step_stats['peak_whole_sole_clearance_m'],sole_clearance(model,data,side))
                drift=float(np.linalg.norm(data.site_xpos[controller.sites[stance],:2]-step_stats['stance_start_xy']))
                step_stats['max_stance_slide_m']=max(step_stats['max_stance_slide_m'],drift)
            if index%round(.05/dt)==0:
                trace.append({'t':float(data.time-start_time),'step':current_step,'phase':phase,
                              'tilt_deg':math.degrees(tilt),
                              'pelvis_xyz':data.qpos[:3].tolist(),'com_xyz':data.subtree_com[1].tolist(),
                              'foot_xyz':data.site_xpos[controller.sites].tolist(),'normal_force_n':forces.tolist(),
                              'com_target_xyz':com.tolist(),'terminal_blend':blend,
                              'qvel':data.qvel.tolist()})
                if capture:poses.append(data.qpos.copy())
            index+=1
            if (not np.isfinite(data.qpos).all() or any(w.number for w in data.warning)
                    or other or data.qpos[2]<.8*standing_height or tilt>math.radians(20) or excess>.02):
                failure='balance/contact/joint-limit guard';return False
        return True
    for step in range(steps):
        current_step=step;swing=(step_offset+step)%2;stance=1-swing
        goal=feet.copy();goal[swing,0]=feet[stance,0]+stride
        offset = (np.array([-.06882,0.]) if controller.support_bounds is None else
                  np.array([controller.support_bounds[stance,:2].mean(),controller.support_bounds[stance,2:].mean()]))
        offset[0]+=com_bias_x_m
        support_com=np.r_[feet[stance,:2]+offset,controller.com0[2]]
        phase='transfer';step_stats=None
        loads=contact_state(model,data)[0];load_start=loads/max(loads.sum(),1);load_goal=np.zeros(2);load_goal[stance]=1
        def transfer(t):
            s=smooth(t/(2*timing))
            controller.load_fractions=load_start*(1-s)+load_goal*s
            return previous_com*(1-s)+support_com*s,feet.copy(),[True,True]
        if not advance(2*timing,transfer):break
        wait=0.
        while not can_lift(data,controller,stance,contact_state(model,data)[0]) and wait<1.5:
            if not advance(.05,lambda t:(support_com,feet.copy(),[True,True])):break
            wait+=.05
        if failure:break
        if not can_lift(data,controller,stance,contact_state(model,data)[0]):
            failure='measured support loading gate timed out';break
        step_stats={'step':step,'swing_side':swing,'load_gate_wait_s':wait,'air_time_s':0.,
                    'peak_whole_sole_clearance_m':0.,'max_stance_slide_m':0.,'min_load_on_stance_n':float('inf'),
                    'stance_start_xy':data.site_xpos[controller.sites[stance],:2].copy()}
        phase='swing'
        def swing_reference(t):
            r=float(np.clip(t/(3*timing),0,1));s=smooth(r)
            targets=feet.copy();targets[swing,0]=(1-s)*feet[swing,0]+s*goal[swing,0]
            targets[swing,2]+=.03*math.sin(math.pi*r)**2
            support=[True,True];support[swing]=False
            return support_com,targets,support
        if not advance(3*timing,swing_reference):break
        phase='landing';controller.load_fractions=None
        if not advance(1*timing,lambda t:(support_com,goal.copy(),[True,True])):break
        landing_error=float(np.linalg.norm(data.site_xpos[controller.sites[swing],:2]-goal[swing,:2]))
        force=contact_state(model,data)[0][swing]
        step_stats.pop('stance_start_xy')
        step_stats['landing_xy_error_m']=landing_error
        step_stats['landing_normal_force_n']=float(force)
        step_stats['accepted']=bool(step_stats['air_time_s']>.2 and step_stats['peak_whole_sole_clearance_m']>.015
                                   and step_stats['max_stance_slide_m']<.02 and landing_error<.02 and force>1)
        landings.append(step_stats)
        if not step_stats['accepted']:
            failure='landing/clearance/support acceptance failed';break
        feet=goal;previous_com=support_com
    if not failure:
        current_step=steps;step_stats=None;phase='recenter'
        offset = (np.array([-.06882,0.]) if controller.support_bounds is None else
                  np.array([controller.support_bounds[:,:2].mean(),controller.support_bounds[:,2:].mean()]))
        offset[0]+=com_bias_x_m
        final_com=np.r_[feet[:,:2].mean(axis=0)+offset,controller.com0[2]]
        if advance(3*timing,lambda t:(previous_com*(1-smooth(t/(3*timing)))+final_com*smooth(t/(3*timing)),feet.copy(),[True,True])):
            phase='settle';advance(2.,lambda t:(final_com,feet.copy(),[True,True]))
            previous_com=final_com
    result={'label':label,'requested_steps':steps,'accepted_steps':sum(s['accepted'] for s in landings),
            'stride_m':stride,'timing_multiplier':timing,'friction':friction,'timestep_s':dt,
            'simulated_seconds':float(data.time-start_time),'failure':failure,
            'walk_pass':bool(failure is None and len(landings)==steps),
            'pelvis_displacement_xyz_m':(data.qpos[:3]-initial_root).tolist(),
            'mean_foot_forward_displacement_m':float((data.site_xpos[controller.sites,0]-initial_feet[:,0]).mean()),
            'max_tilt_deg':max_tilt,'min_pelvis_height_m':height_min,'max_joint_limit_excess_rad':max_limit,
            'tilt_rms_deg':math.sqrt(tilt_squared_time/measured_seconds) if measured_seconds else None,
            'tilt_integral_deg2_s':tilt_squared_time,'measured_seconds':measured_seconds,
            'com_bias_x_m':com_bias_x_m,
            'max_motor_torque_fraction':max_torque_fraction,'nonfoot_ground_contacts':sorted(nonfeet),
            'qp_solves':controller.solves-initial_solves,'qp_inaccurate_status_count':controller.inaccurate-initial_inaccurate,
            'qp_max_constraint_violation':controller.max_residual,
            'holdout_lateral_push_n':push,'push_impulse_ns':impulse,
            'final_max_generalized_speed':float(max(abs(data.qvel))),
            'steps':landings,'trace':trace,'running_validated':False,
            'experimental_mode':mode,'native_apply_allowed':False,
            'phase_metrics':phase_metrics,'final_qvel':data.qvel.tolist(),
            'last_half_second_max_generalized_speed':final_window_max_speed}

    return (result,poses) if capture else result
