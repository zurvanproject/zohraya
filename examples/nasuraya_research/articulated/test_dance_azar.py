"""Score contract tests, including endpoints and physical joint bounds."""
import unittest
import numpy as np
import mujoco
from .dance_azar import score, duration, INTRO, CANDIDATE

class DanceScoreTests(unittest.TestCase):
    def test_ends_return_to_rest_and_motion_is_nonzero(self):
        for bpm in (84,96,108):
            for t in (0, INTRO, duration(bpm)-3, duration(bpm)):
                targets,offset,*_=score(t,bpm)
                self.assertLess(max(abs(x) for x in targets.values()),1e-12)
                self.assertLess(np.linalg.norm(offset),1e-12)
            self.assertGreater(score(INTRO+8*60/bpm,bpm)[0]['shoulder_roll_L'],1.)

    def test_joint_ranges_on_real_model(self):
        m=mujoco.MjModel.from_xml_path(str(CANDIDATE/'nasuraya.xml'))
        for t in np.linspace(0,duration(),1001):
            targets,*_=score(t)
            for name,q in targets.items():
                j=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_JOINT,name)
                self.assertGreater(j,0)
                lo,hi=m.jnt_range[j]
                self.assertTrue(lo <= q <= hi,(name,q,lo,hi))

    def test_invalid_tempo_rejected(self):
        for bpm in (0,-1,float('nan'),200):
            with self.assertRaises(ValueError): duration(bpm)

if __name__=='__main__': unittest.main()
