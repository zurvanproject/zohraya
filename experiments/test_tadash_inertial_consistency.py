"""Regression probes for third simulated witness and remaining common-mode hazard."""
from __future__ import annotations

import copy
import math
import unittest

from experiments.tadash_inertial_consistency import (
    INERTIAL_KEYS, INERTIAL_QUALITY, MODEL, capture_triple, fuse_three,
)
from experiments.tadash_embodied_origin import source_identity
from experiments.test_tadash_dual_sense import fixture as paired_fixture, drift


def fixture(command=0., primary_shift=0., pose_shift=0.,
            inertial_shift=0., source="test_source"):
    pair=paired_fixture(command=command,primary_shift=primary_shift,
                        pose_shift=pose_shift,source=source)
    pair["inertial"]={
        "quality":INERTIAL_QUALITY,"source_sha256":source,
        "command_nm":float(command),
        "frames":[{"t_s":.02*(i+1),
                   **{key:inertial_shift for key in INERTIAL_KEYS}}
                  for i in range(12)],
    }
    return pair


def tamper(pair, mod, magnitude=.6):
    new=copy.deepcopy(pair)
    if mod in ("primary","pose","both"):
        old=drift(pair,mod,magnitude)
        new["primary"]=old["primary"]
        new["pose"]=old["pose"]
    if mod in ("inertial","all"):
        for i, row in enumerate(new["inertial"]["frames"]):
            row["torso_omega_z"]+=magnitude*(i+1)/12
            row["head_omega_z"]+=magnitude*(i+1)/12
    if mod=="all":
        old=drift(pair,"both",magnitude)
        new["primary"]=old["primary"]
        new["pose"]=old["pose"]
    return new


class InertialConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.rest=fixture()

    def check(self,observed,predicted=None,intent=0.):
        return fuse_three(self.rest,self.rest if predicted is None else predicted,
                          observed,intent)

    def test_clean_quiet(self):
        self.assertEqual(self.check(copy.deepcopy(self.rest))["state"],
                         "no_detectable_change")

    def test_matching_known_command(self):
        expected=fixture(command=8.,primary_shift=.20,pose_shift=.20,
                         inertial_shift=.4)
        self.assertEqual(self.check(expected,expected,8.)["state"],
                         "command_consistent")

    def test_dual_coherent_forgery_is_vetoed_by_quiet_velocity(self):
        fake=tamper(self.rest,"both")
        result=self.check(fake)
        self.assertEqual(result["state"],"kinematic_veto_common_mode")
        self.assertEqual(result["cause"],"unknown")

    def test_single_primary_spoof_stays_uncertain(self):
        self.assertEqual(self.check(tamper(self.rest,"primary"))["state"],
                         "sensor_disagreement_or_uncertain")

    def test_single_pose_spoof_stays_uncertain(self):
        self.assertEqual(self.check(tamper(self.rest,"pose"))["state"],
                         "sensor_disagreement_or_uncertain")

    def test_single_velocity_spoof_stays_uncertain(self):
        self.assertEqual(self.check(tamper(self.rest,"inertial"))["state"],
                         "sensor_disagreement_or_uncertain")

    def test_paired_primary_and_inertial_forgery_is_not_proof(self):
        # A real failure mode. The pose witness is quiet and the detector can
        # still issue a provisional, NOT independently verified motion label.
        altered=tamper(self.rest,"primary")
        altered["inertial"]=tamper(self.rest,"inertial")["inertial"]
        result=self.check(altered)
        self.assertEqual(result["state"],"provisional_motion_pose_unreliable")
        self.assertEqual(result["cause"],"unknown")
        self.assertTrue(result["provisional_not_hardware_certification"])

    def test_triple_coordinated_forgery_remains_undetectable(self):
        # Core identifiability limit: all readouts may be tampered together.
        result=self.check(tamper(self.rest,"all"))
        self.assertEqual(result["state"],"three_view_unattributed_change")
        self.assertIn("NOT_EXTERNAL_PROOF",result["scope"])

    def test_missing_velocity_rejected(self):
        observed=copy.deepcopy(self.rest)
        del observed["inertial"]
        self.assertEqual(self.check(observed)["state"],"unverified")

    def test_bad_velocity_source_rejected(self):
        observed=copy.deepcopy(self.rest)
        observed["inertial"]["source_sha256"]="wrong"
        self.assertEqual(self.check(observed)["state"],"unverified")

    def test_stale_velocity_clock_rejected(self):
        observed=copy.deepcopy(self.rest)
        observed["inertial"]["frames"][3]["t_s"]-=.001
        self.assertEqual(self.check(observed)["state"],"unverified")

    def test_non_finite_velocity_rejected(self):
        observed=copy.deepcopy(self.rest)
        observed["inertial"]["frames"][5]["torso_omega_z"]=math.nan
        self.assertEqual(self.check(observed)["state"],"unverified")

    def test_wrong_intent_rejected(self):
        expected=fixture(command=8.,primary_shift=.2,pose_shift=.2,
                         inertial_shift=.4)
        self.assertEqual(self.check(expected,expected,7.)["state"],"unverified")

    def test_native_four_cases_and_replayed_pelvis_frames(self):
        try:
            import mujoco
            import numpy as np
            from experiments.tadash_dual_sense import capture_paired
        except ImportError:
            self.skipTest("native MuJoCo required in CI")
        source=source_identity(MODEL)
        model=mujoco.MjModel.from_xml_path(str(MODEL))
        rest=capture_triple(model,mujoco,np,source)
        command=capture_triple(model,mujoco,np,source,command_nm=8.)
        external=capture_triple(model,mujoco,np,source,external_torque_nm=35.)
        mixed=capture_triple(model,mujoco,np,source,
                             command_nm=8.,external_torque_nm=35.)
        self.assertEqual(rest["primary"],capture_paired(model,mujoco,np,source)["primary"])
        cases=(
            ("quiet",rest,rest,0.,"no_detectable_change"),
            ("command",command,command,8.,"command_consistent"),
            ("external",rest,external,0.,"three_view_unattributed_change"),
            ("mixed",command,mixed,8.,"three_view_command_mismatch"),
        )
        for label,expected,observed,intent,target in cases:
            with self.subTest(name=label):
                r=fuse_three(rest,expected,observed,intent)
                self.assertEqual(r["state"],target,r)


if __name__=="__main__":
    unittest.main()
