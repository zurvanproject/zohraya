"""Isolated 78 kg / 1.70 m morphology and measured contact-control trial.

This does not migrate Tadash, an owner's saved state, or an anatomical mesh.
The proxy has no clothes, skin, genital geometry, or facial likeness.
"""
import argparse
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import mujoco
import yaml
from .build import ROOT, fmt
from .resize import SMALL
from .evaluate import load
from .support_geometry import support_bounds

CANDIDATE=ROOT/'assets/nasuraya_articulated_v03'
EVIDENCE=ROOT/'evidence/body-canon-trial-v01'
TARGETS={'mass_kg':78.,'crown_height_m':1.70,'horn_upper_bound_m':1.92,
         'tail_centerline_length_m':.85,'fingers_per_hand':5,'toes_per_foot':3}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_candidate(output=CANDIDATE):
    output=Path(output)
    length=1.70/1.85; mass=78./85.
    torque=mass*length; damping=mass*length**1.5; inertia=mass*length**2
    tree=ET.parse(SMALL/'nasuraya.xml');xml=tree.getroot()
    xml.set('model','nasuraya_articulated_v03_experiment')
    robot=xml.find("./worldbody/body[@name='pelvis']")
    for item in robot.iter():
        for key in ('pos','fromto','size'):
            if key in item.attrib:
                item.set(key,fmt(float(v)*length for v in item.get(key).split()))
        if 'mass' in item.attrib:
            item.set('mass',str(float(item.get('mass'))*mass))
        if item.tag=='joint':
            for key,factor in [('damping',damping),('armature',inertia)]:
                if key in item.attrib:
                    item.set(key,str(float(item.get(key))*factor))
    # Four rigid links remain a reduced tail, not the proposed 18 vertebrae.
    tail_scale=.85/(.888*length)
    for item in robot.iter():
        name=item.get('name','')
        if item.tag=='body' and name in ('tail_2','tail_3','tail_4'):
            item.set('pos',fmt(float(v)*tail_scale for v in item.get('pos').split()))
        elif item.tag=='geom' and name.startswith('tail_geom_'):
            item.set('fromto',fmt(float(v)*tail_scale for v in item.get('fromto').split()))
        elif item.tag=='site' and name=='tail_tip':
            item.set('pos',fmt(float(v)*tail_scale for v in item.get('pos').split()))
    # Extend existing backwards/upwards horn paths about their roots.
    head=xml.find(".//body[@name='head']")
    crown_local=float(head.find("site[@name='crown']").get('pos').split()[2])
    head_world=1.70-crown_local
    for side in ('L','R'):
        geoms=[head.find("geom[@name='horn_%s_%s']"%(side,i)) for i in range(3)]
        root_z=float(geoms[0].get('fromto').split()[2])
        old_tip=float(geoms[-1].get('fromto').split()[5])
        radius=float(geoms[-1].get('size'))
        new_tip=1.92-head_world-radius
        factor=(new_tip-root_z)/(old_tip-root_z)
        for geom in geoms:
            coords=list(map(float,geom.get('fromto').split()))
            for index in (2,5):coords[index]=root_z+(coords[index]-root_z)*factor
            geom.set('fromto',fmt(coords))
        site=head.find("site[@name='horn_tip_%s']"%side)
        coords=list(map(float,site.get('pos').split()));coords[2]=new_tip
        site.set('pos',fmt(coords))
    for motor in xml.findall('./actuator/motor'):
        for key in ('ctrlrange','forcerange'):
            motor.set(key,fmt(float(v)*torque for v in motor.get(key).split()))
    spec=yaml.safe_load((SMALL/'robot.yaml').read_text())
    spec['id']='nasuraya-canon-trial'
    spec['description']='Experimental unclothed geometry proxy: 78 kg, 1.70 m crown, 0.85 m tail.'
    spec['init_height']*=length
    for joint in spec['joints'].values():
        for key,factor in [('effort',torque),('stiffness',torque),('damping',damping),('armature',inertia)]:
            joint[key]*=factor
    output.mkdir(parents=True,exist_ok=True)
    ET.indent(xml,space='  ')
    tree.write(output/'nasuraya.xml',encoding='unicode',xml_declaration=True)
    (output/'robot.yaml').write_text(yaml.safe_dump(spec,sort_keys=False))
    provenance={'status':'authored_physics_proxy_not_anatomical_mesh',
        'targets':TARGETS,'source':str(SMALL.relative_to(ROOT)),
        'source_model_sha256':sha(SMALL/'nasuraya.xml'),
        'scale_factors':{'length':length,'mass':mass,'torque_and_kp':torque,
                         'damping_and_kd':damping,'armature':inertia},
        'tail_links':4,'tail_link_length_m':.85/4,
        'unimplemented':['reference facial mesh and skin','18 anatomical tail vertebrae',
                         'canonical 18 cm hock and 14.5 by 11 cm support geometry',
                         'muscle/tendon mechanics and pressure distribution',
                         'Tadash physiological runtime or live checkpoint migration'],
        'assumptions':['Remaining body proportions are uniformly scaled from v02.',
                       'Mass allocation and motor scaling remain authored engineering choices.',
                       'Horn height includes capsule radius in the neutral pose.']}
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return output


def audit(folder):
    m,d=load(folder)
    body_names=[mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,i) for i in range(1,m.nbody)]
    crown=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_SITE,'crown')
    horn_top=[]
    for side in ('L','R'):
        s=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_SITE,'horn_tip_'+side)
        g=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'horn_'+side+'_2')
        horn_top.append(float(d.site_xpos[s,2]+m.geom_size[g,0]))
    tree=ET.parse(folder/'nasuraya.xml')
    tail=sum(np.linalg.norm(np.diff(np.array(list(map(float,g.get('fromto').split()))).reshape(2,3),axis=0))
             for g in tree.findall('.//geom') if g.get('name','').startswith('tail_geom_'))
    collisions=[]
    for c in d.contact[:d.ncon]:
        names=[mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,int(x)) for x in (c.geom1,c.geom2)]
        if 'floor' not in names:collisions.append({'geoms':names,'distance_m':float(c.dist)})
    bounds=support_bounds(m)
    physical=support_bounds(m,inset=.999999999)
    old=np.array([-.12,-.015,-.075,.075])
    overshoot=np.maximum(np.array([physical[:,0]-old[0],old[1]-physical[:,1],
                                  physical[:,2]-old[2],old[3]-physical[:,3]]),0).max()
    return {'mass_kg':float(m.body_mass.sum()),'crown_height_m':float(d.site_xpos[crown,2]),
        'horn_upper_bound_m':max(horn_top),'tail_centerline_length_m':float(tail),
        'fingers_per_hand':{s:sum(n.startswith('finger_'+s+'_') for n in body_names) for s in ('L','R')},
        'toes_per_foot':{s:sum(n.startswith('toe_'+s+'_') for n in body_names) for s in ('L','R')},
        'actuated_joints':m.nu,'positive_inertias':bool(np.all(m.body_inertia[1:]>0)),
        'initial_self_collisions':collisions,'support_bounds_m':bounds.tolist(),
        'legacy_bound_max_overshoot_m':float(overshoot),'model_sha256':sha(folder/'nasuraya.xml')}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-only',action='store_true')
    ap.add_argument('--output',type=Path,default=EVIDENCE)
    args=ap.parse_args();build_candidate();out=args.output;out.mkdir(parents=True,exist_ok=True)
    measurements={'v02':audit(SMALL),'v03':audit(CANDIDATE)}
    (out/'morphology.json').write_text(json.dumps(measurements,indent=2)+'\n')
    print(json.dumps(measurements),flush=True)
    if args.build_only:return
    from .stepping import walk_trial
    from .balance import BalanceController,run_trial
    # Frozen before the first candidate rollout; no retuning on holdouts.
    cases=[('v02_legacy',SMALL,False,{}),('v03_legacy',CANDIDATE,False,{}),
           ('v03_geometry',CANDIDATE,True,{}),
           ('v03_low_friction_holdout',CANDIDATE,True,{'friction':.4}),
           ('v03_lateral_push_holdout',CANDIDATE,True,{'push':8.}),
           ('v03_half_timestep_holdout',CANDIDATE,True,{'dt':.0005})]
    protocol={'targets':TARGETS,'steps_per_case':2,'stride_m':.06,'timing':1.,
              'cases':[{'label':label,'model':str(folder.relative_to(ROOT)),
                        'geometry_support':geometry,**opts} for label,folder,geometry,opts in cases],
              'criteria':'Existing walk_trial contact/height/tilt/joint/landing guards unchanged; additionally final speed <0.05.',
              'limits':'Flat-ground rigid-body tests only; full-state feedback; no biological or photoreal claim.'}
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    results={'morphology':measurements,'protocol_sha256':sha(out/'protocol.json'),
        'versions':{p:importlib.metadata.version(p) for p in ('mujoco','numpy','scipy','osqp','PyYAML','Pillow')},
        'trials':[]}
    traces=[]
    for label,folder,geometry,opts in cases:
        try:
            result,poses=walk_trial(label=label,steps=2,model_dir=folder,
                                   geometry_support=geometry,capture=True,**opts)
            result['settled_walk_pass']=bool(result['walk_pass'] and result['final_max_generalized_speed']<.05)
            traces.append({'label':label,'trace':result.pop('trace')})
            np.savez_compressed(out/(label+'-poses.npz'),qpos=np.array(poses),
                                time=np.array([r['t'] for r in traces[-1]['trace']]))
        except Exception as error:
            result={'label':label,'walk_pass':False,'settled_walk_pass':False,
                    'exception':type(error).__name__+': '+str(error)}
        results['trials'].append(result)
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    m,_=load(CANDIDATE);controller=BalanceController(m,CANDIDATE)
    results['standing_trial']=run_trial(m,controller,label='v03_stand_push_10s',seconds=10.,force=(0.,30.))
    traces.append({'label':'v03_stand_push_10s','trace':results['standing_trial'].pop('trace')})
    (out/'traces.json.gz').write_bytes(gzip.compress(json.dumps(traces,separators=(',',':')).encode(),mtime=0))
    results['traces_sha256']=sha(out/'traces.json.gz')
    results['sources_sha256']={name:sha(Path(__file__).with_name(name)) for name in
        ('canon_trial.py','support_geometry.py','stepping.py','balance.py','evaluate.py')}
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results['standing_trial']),flush=True)


if __name__=='__main__':main()
