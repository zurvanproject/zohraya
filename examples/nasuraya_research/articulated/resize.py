"""Build and measure the user-requested smaller body; baseline remains reproducible.

Uniform geometric scaling is authored, not an optimized biological morphology.
Torque/Kp scale as M*L; Kd as M*L**1.5; armature as M*L**2.
This preserves approximate gravitational dynamic similarity, not proven control.
"""
import json
import xml.etree.ElementTree as ET
import numpy as np
import mujoco
import yaml
from .build import OUT, ROOT, fmt
from .evaluate import load, rollout

SMALL = ROOT / 'assets/nasuraya_articulated_v02'
EVIDENCE = ROOT / 'evidence/articulated-body-v02/results.json'


def build_small():
    length = 1.85 / 2.5
    mass = 85. / 165.
    torque = mass * length
    damping = mass * length**1.5
    inertia = mass * length**2
    tree = ET.parse(OUT / 'nasuraya.xml')
    xml = tree.getroot()
    xml.set('model', 'nasuraya_articulated_v02')
    # Only the robot subtree is scaled: floor, lighting and solver stay fixed.
    robot = xml.find("./worldbody/body[@name='pelvis']")
    for item in robot.iter():
        for key in ['pos', 'fromto', 'size']:
            if key in item.attrib:
                item.set(key, fmt(float(v)*length for v in item.get(key).split()))
        if 'mass' in item.attrib:
            item.set('mass', str(float(item.get('mass'))*mass))
        if item.tag == 'joint':
            for key, scale in [('damping', damping), ('armature', inertia)]:
                if key in item.attrib:
                    item.set(key, str(float(item.get(key))*scale))
    for motor in xml.findall('./actuator/motor'):
        for key in ['ctrlrange', 'forcerange']:
            motor.set(key, fmt(float(v)*torque for v in motor.get(key).split()))
    spec = yaml.safe_load((OUT / 'robot.yaml').read_text())
    spec['id'] = 'nasuraya-small'
    spec['description'] = 'Nasuraya 85 kg, 1.85 m crown height; untrained smaller candidate.'
    spec['init_height'] *= length
    for joint in spec['joints'].values():
        for key, scale in [('effort', torque), ('stiffness', torque), ('damping', damping), ('armature', inertia)]:
            joint[key] *= scale
    provenance = {
        'status': 'authored_smaller_candidate_not_optimized_or_biological_measurement',
        'request': 'Shorter body and total mass below 100 kg, including tail and horns.',
        'mass_kg': 85., 'crown_height_m': 1.85,
        'horn_tip_site_height_m': 2.68*length, 'tail_length_m': 1.2*length,
        'source': 'assets/nasuraya_articulated_v01',
        'scale_factors': {'length': length, 'mass': mass, 'torque_and_kp': torque,
                          'damping_and_kd': damping, 'armature': inertia},
        'mass_compartments_kg': {k: v*mass for k,v in json.loads((OUT/'provenance.json').read_text())['mass_compartments_kg'].items()},
        'assumptions': ['Uniform lengths preserve silhouette and joint ranges.',
                        'Reduced torque limits avoid giving smaller body baseline motor strength.',
                        'Density changes: mass and length targets are independent.',
                        '1.85 m measures crown, excludes horns; primitive horn radius extends beyond tip site.'],
        'limitations': ['No trained balance or running controller.', 'No tendon, muscle or tissue model.',
                        'Legacy physiological runtime and v01 fixtures are historical, not migrated.']}
    SMALL.mkdir(parents=True, exist_ok=True)
    ET.indent(xml, space='  ')
    tree.write(SMALL/'nasuraya.xml', encoding='unicode', xml_declaration=True)
    (SMALL/'robot.yaml').write_text(yaml.safe_dump(spec, sort_keys=False))
    (SMALL/'provenance.json').write_text(json.dumps(provenance, indent=2))


def main():
    build_small()
    from wbc_mjlab.robots import custom
    results = {'scope': 'CPU articulated simulation; no learned running', 'models': {}}
    for label, folder, expected_mass, expected_height in [('baseline', OUT, 165., 2.5), ('smaller', SMALL, 85., 1.85)]:
        m,d = load(folder)
        crown = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, 'crown')
        floor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, 'floor')
        assert abs(m.body_mass.sum()-expected_mass) < 1e-7
        assert abs(d.site_xpos[crown,2]-expected_height) < 1e-7
        assert m.nu == 55 and np.all(m.body_inertia[1:] > 0)
        assert all(floor in [c.geom1,c.geom2] for c in d.contact[:d.ncon])
        imported = custom.inspect_model(folder/'nasuraya.xml')
        assert imported['dof'] == 55
        data = {'mass_kg': float(m.body_mass.sum()), 'crown_height_m': float(d.site_xpos[crown,2]),
                'initial_com_height_m': float(d.subtree_com[1,2]), 'upstream_imported_joints': imported['dof'],
                'morphology_and_inertia_checks_passed': True, 'trials': {}}
        for trial, seconds in [('pose_hold_0_5s', .5), ('pose_hold_5s', 5.)]:
            result = rollout(seconds=seconds, drop=.005, model_dir=folder)
            result['first_nonfoot_contact_time_s_sampled'] = next((row['t'] for row in result['trace'] if any(not n.startswith(('ball_', 'toe_pad_')) for n in row['contacts'])), None)
            result['balance_pass'] = bool(result['numerically_finite'] and not result['nonfoot_ground_geoms'] and result['root_height_final_m'] > .8*m.qpos0[2])
            result.pop('trace')
            data['trials'][trial] = result
        results['models'][label] = data
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
