"""Contract tests for the fixed Nasuraya render-pose anatomy reference.

These tests reject malformed pose geometry; they cannot certify image pixels or
physical dynamics, which require separate visual and biomechanical review.
"""
import copy
import json
import math
from pathlib import Path
import unittest

REF = Path(__file__).resolve().parents[1] / 'docs/visual/nasuraya_pose_contract_v1.json'
CHAIN = ('hip', 'knee', 'hock', 'metatarsal_head', 'toe_tip')


def check(data):
    failures = []
    a = data['anatomy']
    for key, value in (('horns',2),('feet',2),('toes_per_foot',3),
                       ('hands',2),('fingers_per_hand',5)):
        if type(a.get(key)) is not int or a.get(key)!=value:
            failures.append('count:'+key)
    if a.get('gait')!='digitigrade' or tuple(a.get('chain',[]))!=CHAIN:
        failures.append('topology')
    horns = data['horn_points_head_local_m']
    if len(horns['left'])!=len(horns['right']) or len(horns['left'])<4:
        failures.append('horn-pairs')
    else:
        for left,right in zip(horns['left'], horns['right']):
            if not (math.isclose(left[0], -right[0], abs_tol=1e-6) and
                    math.isclose(left[1], right[1], abs_tol=1e-6) and
                    math.isclose(left[2], right[2], abs_tol=1e-6)):
                failures.append('horn-mirror')
                break
    poses=data['lateral_poses_m']
    lengths={}
    for name, pose in poses.items():
        if not all(p in pose for p in CHAIN):
            failures.append('missing-joint:'+name)
            continue
        hip,knee,hock,ball,toe=(pose[p] for p in CHAIN)
        lengths[name]=[math.dist(pose[CHAIN[i]],pose[CHAIN[i+1]]) for i in range(4)]
        if not (knee[0]>hip[0] and knee[0]>hock[0] and
                hip[1]>knee[1]>hock[1] and hock[0]<ball[0]<toe[0]):
            failures.append('hock-knee-orientation:'+name)
        if name=='standing' and hock[1]<.24:
            failures.append('standing-heel-touch')
        if name=='sitting' and (hock[1]>.20 or 'pelvis' not in pose['support']):
            failures.append('sitting-support')
        if not .02<=toe[1]<=.12:
            failures.append('toe-ground:'+name)
    if len(lengths)==2:
        for i,(v1,v2) in enumerate(zip(lengths['standing'],lengths['sitting'])):
            if abs(v1-v2)/max(v1,v2)>.025:
                failures.append('bone-length-changed:'+str(i))
    toes=data['foot_toes_front_m']
    if len(toes)!=3 or len({t['id'] for t in toes})!=3 or len({t['x'] for t in toes})!=3:
        failures.append('toes-not-distinct')
    if not data.get('image_gate'):
        failures.append('missing-visual-gate')
    return failures


class VisualAnatomyTest(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(REF.read_text(encoding='utf-8'))
    def test_reference(self):
        self.assertEqual(check(self.data), [])
    def test_asymmetric_horn_fails(self):
        self.data['horn_points_head_local_m']['right'][2][0]+=.04
        self.assertIn('horn-mirror',check(self.data))
    def test_extra_toe_fails(self):
        self.data['foot_toes_front_m'].append({'id':'extra','x':.13,'y':.19})
        self.assertIn('toes-not-distinct',check(self.data))
    def test_swapped_hock_fails(self):
        self.data['lateral_poses_m']['sitting']['hock'][0]=.8
        self.assertTrue(check(self.data))
    def test_human_flat_heel_fails(self):
        self.data['lateral_poses_m']['standing']['hock'][1]=.01
        self.assertIn('standing-heel-touch',check(self.data))
    def test_sitting_does_not_shorten_shin(self):
        self.data['lateral_poses_m']['sitting']['knee'][1]=.36
        self.assertTrue(any(e.startswith('bone-length-changed:') for e in check(self.data)))

if __name__ == '__main__':
    unittest.main()
