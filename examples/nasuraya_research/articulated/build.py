"""Deterministic MJCF construction from native dimensions and authored mechanics.

No biological feasibility is inferred. Segment inertia is computed from primitive
geometries with explicit mass. Local q=0 is the authored flexed reference pose.
"""
from pathlib import Path
import json,math,xml.etree.ElementTree as ET
import numpy as np
import yaml

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'assets/nasuraya_articulated_v01'
DESIGN=ROOT/'runtimes/tadash_body/base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json'
PHENOTYPE=ROOT/'runtimes/tadash_body/phenotype_v1.json'
PROFILE=Path(__file__).parents[1]/'running_profile_v01.json'

def fmt(x):return ' '.join(f'{float(v):.12g}' for v in x)
def node(parent,tag,**kw):return ET.SubElement(parent,tag,{k:fmt(v) if isinstance(v,(list,tuple,np.ndarray)) else str(v) for k,v in kw.items()})

def build(output=OUT):
    d=json.loads(DESIGN.read_text());p=json.loads(PHENOTYPE.read_text())
    target=json.loads(PROFILE.read_text())['profile'];mass=target['mass_kg']
    compartments={k:v*mass/d['mass_kg'] for k,v in p['adult_scale']['mass_compartments_kg'].items()}
    xml=ET.Element('mujoco',model='nasuraya_articulated_v01')
    node(xml,'compiler',angle='radian',autolimits='true',inertiafromgeom='true')
    node(xml,'option',timestep='.001',integrator='implicitfast',gravity=[0,0,-9.81],iterations=60,cone='elliptic')
    visual=node(xml,'visual');node(visual,'global',offwidth=1200,offheight=1000)
    default=node(xml,'default')
    node(default,'joint',damping=1,armature=.01,limited='true')
    node(default,'geom',friction=[.6,.005,.0001],solref=[.01,1],solimp=[.95,.99,.001],condim=3,rgba=[.65,.32,.17,1])
    world=node(xml,'worldbody')
    node(world,'light',pos=[2,-2,5],dir=[-1,1,-2],diffuse=[.8,.8,.8])
    node(world,'geom',name='floor',type='plane',size=[6,6,.1],rgba=[.18,.22,.26,1])
    root=node(world,'body',name='pelvis',pos=[0,0,d['hip_height_m']])
    node(root,'freejoint',name='root')
    gains={};geoms=[]
    def joint(body,name,axis,limits,effort,kp,kd,arm=.05):
        node(body,'joint',name=name,type='hinge',axis=axis,range=limits,armature=arm,damping=.2)
        gains[name]={'effort':effort,'stiffness':kp,'damping':kd,'armature':arm}
    def capsule(body,name,a,b,r,m,**kw):
        return node(body,'geom',name=name,type='capsule',fromto=[*a,*b],size=[r],mass=m,**kw)
    def geom(body,name,kind,pos,size,m,**kw):return node(body,'geom',name=name,type=kind,pos=pos,size=size,mass=m,**kw)
    geom(root,'pelvis_mass','ellipsoid',[0,0,.06],[.19,.20,.18],compartments['trunk']*.25)
    torso=node(root,'body',name='torso',pos=[0,0,.20])
    for suffix,axis,lim in [('yaw',[0,0,1],[-.6,.6]),('pitch',[0,1,0],[-.45,.45]),('roll',[1,0,0],[-.3,.3])]:
        joint(torso,'waist_'+suffix,axis,lim,180,800,45,.2)
    geom(torso,'torso_mass','ellipsoid',[0,0,.20],[.19,.25,.24],compartments['trunk']*.75)
    node(torso,'site',name='imu',pos=[0,0,.2],size=.012)
    head=node(torso,'body',name='head',pos=[0,0,.56])
    joint(head,'neck_yaw',[0,0,1],[-.9,.9],35,120,10)
    joint(head,'neck_pitch',[0,1,0],[-.45,.45],35,120,10)
    hm=compartments['head_and_horns']
    capsule(head,'neck_mass',[0,0,0],[0,0,.08],.06,hm*.06)
    geom(head,'head_mass','ellipsoid',[0,0,.16],[.13,.105,.16],hm*.90)
    node(head,'site',name='crown',pos=[0,0,.32],size=.008)
    for side,sign in [('L',1),('R',-1)]:
        points=[[0,sign*.08,.22],[-.09,sign*.11,.33],[-.10,sign*.11,.43],[-.04,sign*.10,.50]]
        for i in range(3):capsule(head,f'horn_{side}_{i}',points[i],points[i+1],.018,hm*.04/6,rgba=[.22,.14,.11,1])
        node(head,'site',name=f'horn_tip_{side}',pos=points[-1],size=.005)
        arm=node(torso,'body',name=f'upper_arm_{side}',pos=[0,sign*.31,.44])
        for suffix,axis,lim in [('pitch',[0,1,0],[-2,2]),('roll',[1,0,0],[-1.6,1.6]),('yaw',[0,0,1],[-1.5,1.5])]:
            joint(arm,f'shoulder_{suffix}_{side}',axis,lim,90,300,22)
        am=compartments['both_arms']/2;upper=np.array([0,sign*.07,-.40]);lower=np.array([.025,0,-.36])
        capsule(arm,f'upper_arm_geom_{side}',[0,0,0],upper,.065,am*.5)
        fore=node(arm,'body',name=f'forearm_{side}',pos=upper)
        joint(fore,f'elbow_{side}',[0,1,0],[-1.9,.25],75,260,18)
        capsule(fore,f'forearm_geom_{side}',[0,0,0],lower,.05,am*.3)
        hand=node(fore,'body',name=f'hand_{side}',pos=lower)
        joint(hand,f'wrist_pitch_{side}',[0,1,0],[-.8,.8],20,80,6,.01)
        joint(hand,f'wrist_roll_{side}',[1,0,0],[-.6,.6],20,80,6,.01)
        geom(hand,f'palm_{side}','box',[0,0,-.065],[.03,.06,.065],am*.12)
        for i in range(5):
            finger=node(hand,'body',name=f'finger_{side}_{i+1}',pos=[0,(i-2)*.026,-.125])
            joint(finger,f'finger_flex_{side}_{i+1}',[0,1,0],[-.2,1.3],4,20,1,.002)
            capsule(finger,f'finger_geom_{side}_{i+1}',[0,0,0],[.015 if i==0 else 0,0,-(.08 if i in [0,4] else .11)],.009,am*.08/5)
        # Native 3-link geometry, rotated from (+left,+forward,+up) to (+forward,+left,+up).
        hip=np.array([0,sign*d['hip_half_width_m'],d['hip_height_m']])
        foot=np.array([0,sign*d['foot_half_spacing_m'],0.])
        l1,l2,l3=d['leg_lengths_m'];hz=d['hock_height_m'];back=math.sqrt(l3*l3-hz*hz)
        hock=foot+[-back,0,hz];delta=hock-hip;length=np.linalg.norm(delta);u=delta/length
        a=(l1*l1-l2*l2+length*length)/(2*length);bend=math.sqrt(l1*l1-a*a)
        forward=np.array([1,0,0])-u*u[0];forward/=np.linalg.norm(forward);knee=hip+a*u+bend*forward
        lm=compartments['both_legs_and_feet']/2
        thigh=node(root,'body',name=f'thigh_{side}',pos=hip-[0,0,d['hip_height_m']])
        for suffix,axis,lim in [('yaw',[0,0,1],[-.6,.6]),('roll',[1,0,0],[-.5,.5]),('pitch',[0,1,0],[-1.1,1.1])]:
            joint(thigh,f'hip_{suffix}_{side}',axis,lim,350,1200,65,.3)
        capsule(thigh,f'thigh_geom_{side}',[0,0,0],knee-hip,.085,lm*.48)
        shin=node(thigh,'body',name=f'shin_{side}',pos=knee-hip)
        joint(shin,f'knee_{side}',[0,1,0],[-.5,1.8],350,1200,65,.3)
        capsule(shin,f'shin_geom_{side}',[0,0,0],hock-knee,.06,lm*.32)
        meta=node(shin,'body',name=f'metatarsal_{side}',pos=hock-knee)
        joint(meta,f'hock_pitch_{side}',[0,1,0],[-.8,.8],220,800,40,.15)
        joint(meta,f'hock_roll_{side}',[1,0,0],[-.4,.4],150,500,30,.1)
        capsule(meta,f'metatarsal_geom_{side}',[0,0,0],foot-hock+[0,0,.07],.045,lm*.12)
        pad=node(meta,'body',name=f'foot_{side}',pos=foot-hock)
        joint(pad,f'mtp_{side}',[0,1,0],[-.5,.7],160,700,35,.08)
        ball=d['patches'][0];halfwidth=.11;halflength=ball['area_m2']/(4*halfwidth)
        geom(pad,f'ball_{side}','box',[ball['xy'][1],ball['xy'][0],.025],[halflength,halfwidth,.025],lm*.06)
        geoms.append(f'ball_{side}')
        node(pad,'site',name=f'foot_contact_{side}',pos=[0,0,0],size=.01)
        for i,patch in enumerate(d['patches'][1:]):
            toe=node(pad,'body',name=f'toe_{side}_{i+1}',pos=[.015,patch['xy'][0],0])
            joint(toe,f'toe_flex_{side}_{i+1}',[0,1,0],[-.3,.6],25,140,8,.015)
            hw=.02 if i!=1 else .025;hl=patch['area_m2']/(4*hw)
            name=f'toe_pad_{side}_{i+1}';geoms.append(name)
            geom(toe,name,'box',[patch['xy'][1]-.015,0,.02],[hl,hw,.02],lm*.02/3)
    parent=root;tm=compartments['tail'];segment=np.array([-.3*math.cos(.17),0,-.3*math.sin(.17)])
    for i,fraction in enumerate([.4,.3,.2,.1]):
        body=node(parent,'body',name=f'tail_{i+1}',pos=[-.18,0,-.08] if i==0 else segment)
        for suffix,axis in [('yaw',[0,0,1]),('pitch',[0,1,0])]:joint(body,f'tail_{suffix}_{i+1}',axis,[-.65,.65],60 if i==0 else 35,100 if i==0 else 70,8,.04)
        capsule(body,f'tail_geom_{i+1}',[0,0,0],segment,[.05,.04,.03,.02][i],tm*fraction)
        parent=body
    node(parent,'site',name='tail_tip',pos=segment,size=.008)
    acts=node(xml,'actuator')
    for name,g in gains.items():node(acts,'motor',name=name+'_motor',joint=name,gear=1,ctrllimited='true',ctrlrange=[-g['effort'],g['effort']],forcelimited='true',forcerange=[-g['effort'],g['effort']])
    sensors=node(xml,'sensor')
    node(sensors,'gyro',name='imu_ang_vel',site='imu');node(sensors,'velocimeter',name='imu_lin_vel',site='imu')
    node(sensors,'subtreeangmom',name='root_angmom',body='pelvis')
    keys=['pelvis','torso','head']+[f'{part}_{side}' for side in ['L','R'] for part in ['upper_arm','forearm','hand','thigh','shin','metatarsal','foot']]+['tail_1','tail_4']
    spec={'id':'nasuraya','model':'nasuraya.xml','anchor_body':'torso','keybodies':keys,
          'ee_bodies':['foot_L','foot_R','hand_L','hand_R'],'feet_bodies':['foot_L','foot_R'],
          'foot_sites':['foot_contact_L','foot_contact_R'],'foot_geoms':geoms,
          'foot_sole_z':0.,'init_height':d['hip_height_m']+.005,'init_joint_pos':{k:0. for k in gains},
          'joints':gains,'action_scale':.25,'description':'Nasuraya 165 kg experimental articulated body; untrained.',
          'nconmax':256,'njmax':1500}
    provenance={'status':'authored_articulated_design_not_biological_measurement','axes':'+X forward,+Y left,+Z up',
        'mass_kg':mass,'mass_compartments_kg':compartments,'native_reference_mass_kg':d['mass_kg'],
        'crown_height_m':2.5,'horn_tip_site_height_m':2.68,'tail_length_m':1.2,
        'source_paths':[str(x.relative_to(ROOT)) for x in [DESIGN,PHENOTYPE,PROFILE]],
        'derived_from_native':['hip height/spacing','foot spacing','three leg lengths and nominal IK geometry','contact patch areas/centres','crown/shoulder heights','tail length','compartment mass proportions'],
        'authored':['within-compartment mass split','primitive inertial/collision shapes','reference pose joint ranges','motor torque limits and PD gains','four two-axis tail segments','finger/toe articulation'],
        'limitations':['no muscles/tendons or tissue compliance','primitive feet reproduce area but not measured pressure distribution','neutral-pose joint offsets, not anatomical angle conventions','tail/head/limb inertia are authored from primitive geometry','no trained motion policy or verified running']}
    output.mkdir(parents=True,exist_ok=True);ET.indent(xml,space='  ')
    ET.ElementTree(xml).write(output/'nasuraya.xml',encoding='unicode',xml_declaration=True)
    (output/'robot.yaml').write_text(yaml.safe_dump(spec,sort_keys=False))
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2))
    return output

if __name__=='__main__':print(build())
