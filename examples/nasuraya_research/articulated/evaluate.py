"""CPU physical checks and real upstream WBC importer/registry integration.

No trained controller, external root support, or running certification is implied.
"""
from pathlib import Path
import argparse,json,math,os,shutil,tempfile,importlib.metadata
import numpy as np
import mujoco,yaml
from .build import OUT,ROOT


def name(m,kind,i):return mujoco.mj_id2name(m,kind,int(i))
def load(model_dir=OUT):
    m=mujoco.MjModel.from_xml_path(str(model_dir/'nasuraya.xml'));d=mujoco.MjData(m)
    mujoco.mj_forward(m,d);return m,d

def controller_arrays(m,spec):
    qa=[];va=[];kp=[];kd=[];eff=[]
    for a in range(m.nu):
        j=int(m.actuator_trnid[a,0]);g=spec['joints'][name(m,mujoco.mjtObj.mjOBJ_JOINT,j)]
        qa.append(m.jnt_qposadr[j]);va.append(m.jnt_dofadr[j]);kp.append(g['stiffness']);kd.append(g['damping']);eff.append(g['effort'])
    return tuple(np.array(v) for v in [qa,va,kp,kd,eff])

def rollout(seconds=2.,drop=0.,tail_motion=False,zero_g=False,passive=False,dt=.001,frames=False,model_dir=OUT):
    m,d=load(model_dir);spec=yaml.safe_load((model_dir/'robot.yaml').read_text());m.opt.timestep=dt
    if zero_g:m.opt.gravity[:]=0;d.qpos[2]+=2.
    else:d.qpos[2]+=drop
    mujoco.mj_forward(m,d)
    qa,va,kp,kd,eff=controller_arrays(m,spec);target=d.qpos[qa].copy()
    tail=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_JOINT,'tail_yaw_1')
    tail_a=list(m.actuator_trnid[:,0]).index(tail)
    floor=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'floor')
    rows=[];saved=[];peak_grf=0.;saturation=0.;nonfeet=set();unstable=False;maxmomentum=0.;maxlimit=0.
    for i in range(round(seconds/dt)):
        if tail_motion:target[tail_a]=.35*.5*(1-math.cos(math.pi*min(d.time/.4,1)))
        torque=kp*(target-d.qpos[qa])-kd*d.qvel[va]
        if not passive:saturation+=float(np.mean(abs(torque)>eff))
        d.ctrl[:]=0 if passive else np.clip(torque,-eff,eff)
        mujoco.mj_step(m,d);mujoco.mj_forward(m,d)
        if not np.isfinite(d.qpos).all() or d.warning[mujoco.mjtWarning.mjWARN_BADQACC].number:
            unstable=True;break
        mujoco.mj_subtreeVel(m,d);maxmomentum=max(maxmomentum,float(np.linalg.norm(d.subtree_angmom[1])))
        grf=0.;touch=[]
        for j,c in enumerate(d.contact[:d.ncon]):
            if floor in [c.geom1,c.geom2]:
                other=c.geom2 if c.geom1==floor else c.geom1;n=name(m,mujoco.mjtObj.mjOBJ_GEOM,other)
                touch.append(n);force=np.zeros(6);mujoco.mj_contactForce(m,d,j,force);grf+=max(float(force[0]),0.)
                if not n.startswith(('ball_','toe_pad_')):nonfeet.add(n)
        peak_grf=max(peak_grf,grf)
        for j in range(1,m.njnt):
            q=d.qpos[m.jnt_qposadr[j]];lo,hi=m.jnt_range[j];maxlimit=max(maxlimit,max(lo-q,q-hi,0.))
        if i%max(1,round(.02/dt))==0:
            yaw=math.atan2(d.xmat[1].reshape(3,3)[1,0],d.xmat[1].reshape(3,3)[0,0])
            tilt=math.acos(np.clip(d.xmat[1].reshape(3,3)[2,2],-1,1))
            rows.append({'t':float(d.time),'root_height':float(d.qpos[2]),'root_yaw_rad':yaw,'root_tilt_rad':tilt,
                         'tail_yaw_rad':float(d.qpos[m.jnt_qposadr[tail]]),'contacts':sorted(set(touch))})
            if frames:saved.append(d.qpos.copy())
    final_rot=d.xmat[1].reshape(3,3)
    result={'seconds':float(d.time),'numerically_finite':not unstable,'root_height_final_m':float(d.qpos[2]),
       'root_yaw_final_rad':math.atan2(final_rot[1,0],final_rot[0,0]),
       'tail_yaw_final_rad':float(d.qpos[m.jnt_qposadr[tail]]),
       'peak_ground_normal_n':peak_grf,'actuator_saturation_fraction':saturation/max(i+1,1),
       'nonfoot_ground_geoms':sorted(nonfeet),'max_joint_limit_soft_violation_rad':maxlimit,
       'max_physical_subtree_angular_momentum_norm':maxmomentum,'trace':rows}
    if frames:return result,saved
    return result


def upstream_check(config_root=None):
    from wbc_mjlab.robots import custom
    import torch
    t=tempfile.TemporaryDirectory() if config_root is None else None
    folder=Path(t.name if t else config_root)
    previous=os.environ.get('WBC_MJLAB_CONFIG_DIR');os.environ['WBC_MJLAB_CONFIG_DIR']=str(folder)
    try:
        dest=folder/'robots/nasuraya';dest.mkdir(parents=True,exist_ok=True)
        for f in ['nasuraya.xml','robot.yaml']:shutil.copy(OUT/f,dest/f)
        spec=custom.load_spec('nasuraya');inspection=custom.inspect_model(spec.source)
        if inspection['dof']!=55:raise RuntimeError(f"Upstream import found {inspection['dof']} of 55 joints; incompatible dependency versions")
        settle=custom.settle_test(spec)
        custom.save_spec(spec)
        from mjlab.tasks import registry
        from wbc_mjlab import tasks
        task_ids=[c.task_id for c in custom.tasks_for(spec)]
        registered={n:n in registry._REGISTRY for n in task_ids}
        cfg=custom.env_cfg(spec,play=True)
        entity=cfg.scene.entities['robot'];prepared=entity.spec_fn().compile()
        return {'upstream_imported_joints':inspection['dof'],'mass_kg':inspection['mass'],'settle_check':settle,
           'registered_tasks':registered,'environment_config_built':True,'prepared_nq':prepared.nq,
           'tracked_bodies':list(cfg.commands['motion'].body_names),'actuator_groups':len(entity.articulation.actuators),
           'cuda_available':torch.cuda.is_available(),'training_executed':False,
           'note':'Real upstream inspect/prepare/settle/save/registry and environment config executed. No learned policy or GPU training.'}
    finally:
        if previous is None:os.environ.pop('WBC_MJLAB_CONFIG_DIR',None)
        else:os.environ['WBC_MJLAB_CONFIG_DIR']=previous
        if t:t.cleanup()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'evidence/articulated-body-v01/results.json')
    args=ap.parse_args();m,d=load();spec=yaml.safe_load((OUT/'robot.yaml').read_text())
    names=[name(m,mujoco.mjtObj.mjOBJ_BODY,i) for i in range(1,m.nbody)]
    collisions=[]
    for c in d.contact[:d.ncon]:
        a=name(m,mujoco.mjtObj.mjOBJ_GEOM,c.geom1);b=name(m,mujoco.mjtObj.mjOBJ_GEOM,c.geom2)
        if a!='floor' and b!='floor':collisions.append([a,b,float(c.dist)])
    result={'schema':'nasuraya-articulated/0.1','upstream_wbc_commit':'eb6c024b9586bc1de41b3dd22b9f18ad51cb1da9',
       'versions':{n:importlib.metadata.version(n) for n in ['mujoco','numpy','scipy','torch','mjlab','wbc-mjlab','warp-lang']},
       'structure':{'mass_kg':float(m.body_mass.sum()),'rigid_bodies':m.nbody-1,'actuated_joints':m.nu,
        'free_base_dof':6,'total_velocity_dof':m.nv,'initial_com_m':d.subtree_com[1].tolist(),
        'native_com_fixture_m':1.314,'initial_self_collisions':collisions,
        'fingers_per_hand':{s:sum(n.startswith('finger_'+s+'_') for n in names) for s in ['L','R']},
        'toes_per_foot':{s:sum(n.startswith('toe_'+s+'_') for n in names) for s in ['L','R']},
        'tail_segments':sum(n.startswith('tail_') for n in names),
        'inertia_positive':bool(np.all(m.body_inertia[1:]>0)),
        'crown_z':float(d.site_xpos[mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_SITE,'crown'),2])}}
    result['physical_trials']={
       'pose_hold_0_5s':rollout(seconds=.5,drop=.005),
       'pose_hold_5s':rollout(seconds=5,drop=.005),
       'passive_1s':rollout(seconds=1,drop=.005,passive=True),
       'landing_5cm':rollout(seconds=.5,drop=.05),
       'airborne_tail_neutral':rollout(seconds=.8,zero_g=True),
       'airborne_tail_yaw':rollout(seconds=.8,zero_g=True,tail_motion=True),
       'airborne_tail_yaw_half_dt':rollout(seconds=.8,zero_g=True,tail_motion=True,dt=.0005)}
    try:result['wbc']=upstream_check()
    except Exception as e:result['wbc']={'integration_error':type(e).__name__+': '+str(e),'training_executed':False}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({**result,'physical_trials':{k:{a:b for a,b in v.items() if a!='trace'} for k,v in result['physical_trials'].items()}},indent=2))

if __name__=='__main__':main()
