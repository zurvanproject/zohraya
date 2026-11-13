"""Unit and native failure-injection contracts for the v0.3 virtual pose witness."""
from __future__ import annotations

import copy
import math
import unittest

from experiments.tadash_dual_sense import (
    MODEL, POSE_QUALITY, POSE_WEIGHTS, capture_paired, fuse_body_evidence,
)
from experiments.tadash_embodied_origin import source_identity, capture_native


def fixture(command=0., primary_shift=0., pose_shift=0., source="fixture"):
    n=12
    return {
        "primary": {
            "source_sha256": source, "quality": "native_simulated",
            "command_nm": float(command),
            "frames": [{
                "t_s": .02*(i+1), "pelvis_yaw_rad": primary_shift,
                "tail_yaw_rad": primary_shift, "com_x_m": 0.,
                "com_y_m": 0., "foot_left_n": 0., "foot_right_n": 0.,
            } for i in range(n)]
        },
        "pose": {
            "source_sha256": source, "quality": POSE_QUALITY,
            "command_nm": float(command),
            "frames": [{
                "t_s": .02*(i+1), "torso_yaw": pose_shift, "head_yaw": pose_shift,
                "tail_4_x": pose_shift, "tail_4_y": pose_shift,
                "head_x": 0., "head_y": 0.,
            } for i in range(n)]
        },
    }


def drift(pair, which="primary", amplitude=.35):
    result=copy.deepcopy(pair)
    for i in range(12):
        value=amplitude*(i+1)/12
        if which in ("primary","both"):
            result["primary"]["frames"][i]["pelvis_yaw_rad"] += value
            result["primary"]["frames"][i]["tail_yaw_rad"] += value
        if which in ("pose","both"):
            result["pose"]["frames"][i]["torso_yaw"] += value
            result["pose"]["frames"][i]["tail_4_x"] += value
    return result


class DualSenseUnitTests(unittest.TestCase):
    def setUp(self):
        self.rest=fixture()

    def classify(self, actual, prediction=None, command=0.):
        return fuse_body_evidence(self.rest, self.rest if prediction is None else prediction,
                                  actual, command)

    def test_quiet_synthetic_control(self):
        self.assertEqual(self.classify(copy.deepcopy(self.rest))["state"],
                         "no_detectable_change")

    def test_primary_smooth_spoof_does_not_count_as_real_agreement(self):
        result=self.classify(drift(self.rest,"primary"))
        self.assertEqual(result["state"],"sensor_disagreement")
        self.assertEqual(result["causal_origin"],"unknown")

    def test_witness_smooth_spoof_does_not_count_as_real_agreement(self):
        self.assertEqual(self.classify(drift(self.rest,"pose"))["state"],
                         "sensor_disagreement")

    def test_white_noise_like_alternation_abstains(self):
        actual=copy.deepcopy(self.rest)
        for i in range(12):
            for key in ("pelvis_yaw_rad","tail_yaw_rad"):
                actual["primary"]["frames"][i][key]=.2*(-1)**i
        self.assertEqual(self.classify(actual)["state"],
                         "uncertain_noise_or_missing")

    def test_dual_coherent_spoof_remains_unattributed_failure_mode(self):
        both=drift(self.rest,"both")
        out=self.classify(both)
        self.assertEqual(out["state"],"agreement_unattributed_change")
        self.assertEqual(out["causal_origin"],"unknown")
        self.assertIn("one_MuJoCo_solver",out["scope"])

    def test_clean_known_command_consistent(self):
        expected=fixture(command=8.,primary_shift=.2,pose_shift=.2)
        result=self.classify(copy.deepcopy(expected),prediction=expected,command=8.)
        self.assertEqual(result["state"],"command_consistent")

    def test_predicted_command_without_pose_change_fails(self):
        expected=fixture(command=8.,primary_shift=.2,pose_shift=0.)
        self.assertEqual(self.classify(expected,prediction=expected,command=8.)["state"],
                         "unverified")

    def test_wrong_pose_source_fails_closed(self):
        actual=copy.deepcopy(self.rest)
        actual["pose"]["source_sha256"]="wrong"
        self.assertEqual(self.classify(actual)["state"],"unverified")

    def test_pose_time_mismatch_fails_closed(self):
        actual=copy.deepcopy(self.rest)
        actual["pose"]["frames"][6]["t_s"]+=.001
        self.assertEqual(self.classify(actual)["state"],"unverified")

    def test_pose_nan_fails_closed(self):
        actual=copy.deepcopy(self.rest)
        actual["pose"]["frames"][5]["tail_4_x"]=math.nan
        self.assertEqual(self.classify(actual)["state"],"unverified")

    def test_missing_pose_fails_closed(self):
        actual=copy.deepcopy(self.rest)
        del actual["pose"]
        self.assertEqual(self.classify(actual)["state"],"unverified")

    def test_false_witness_quality_fails_closed(self):
        actual=copy.deepcopy(self.rest)
        actual["pose"]["quality"]="web_camera_unverified"
        self.assertEqual(self.classify(actual)["state"],"unverified")

    def test_witness_unfounded_command_change_fails_closed(self):
        actual=copy.deepcopy(self.rest)
        actual["pose"]["command_nm"]=9.
        self.assertEqual(self.classify(actual)["state"],"unverified")

    def test_native_readouts_match_existing_primary_and_expose_real_perturbation(self):
        try:
            import mujoco
            import numpy as np
        except ImportError:
            self.skipTest("native MuJoCo required in GitHub Actions")
        source=source_identity(MODEL)
        model=mujoco.MjModel.from_xml_path(str(MODEL))
        rest=capture_paired(model,mujoco,np,source)
        command=capture_paired(model,mujoco,np,source,command_nm=8.)
        external=capture_paired(model,mujoco,np,source,external_torque_nm=35.)
        both=capture_paired(model,mujoco,np,source,command_nm=8.,external_torque_nm=35.)
        independent_run=capture_native(model,mujoco,np,source)
        self.assertEqual(rest["primary"],independent_run)
        cases={
            "rest":(rest,rest,rest,0.,"no_detectable_change"),
            "known_command":(rest,command,command,8.,"command_consistent"),
            "external_torque":(rest,rest,external,0.,"agreement_unattributed_change"),
            "command_external":(rest,command,both,8.,"agreement_command_mismatch"),
        }
        for name,(r,p,a,cmd,target) in cases.items():
            with self.subTest(name=name):
                result=fuse_body_evidence(r,p,a,cmd)
                self.assertEqual(result["state"],target,result)


if __name__=="__main__":
    unittest.main()
