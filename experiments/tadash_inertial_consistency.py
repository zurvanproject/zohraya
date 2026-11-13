"""Tadash v0.4: native spatial-velocity witness, not an external sensor.

The v0.3 joint/COM and world-pose readouts are retained unchanged. A third
*simulator-derived* witness records MuJoCo's cvel angular velocities from a
separately replayed, source-pinned deterministic episode. Its role is
consistency checking and conservative two-of-three evidence, not verification
of real movement, stimulus provenance, or consciousness.
"""
from __future__ import annotations

import math

from experiments.tadash_dual_sense import (
    MODEL, MOTOR, CAPTURE_STEPS, SAMPLE_EVERY, capture_paired,
    fuse_body_evidence, pose_evidence,
)
from experiments.tadash_embodied_origin import source_identity, _validated
from experiments.tadash_temporal_proprioception import classify_temporal

INERTIAL_QUALITY = "native_simulated_spatial_velocity"
INERTIAL_KEYS = ("pelvis_omega_z", "torso_omega_z", "head_omega_z")
INERTIAL_SMALL = 0.05
INERTIAL_SUPPORT = 0.15
INERTIAL_EXCURSION = 0.35
INERTIAL_MIN_SIGN_FRAMES = 5


def capture_triple(model, mujoco, np, source, command_nm=0., external_torque_nm=0.):
    """Simulate from rest twice, checking that geometric and velocity runs match."""
    paired = capture_paired(model, mujoco, np, source,
                           command_nm=command_nm,
                           external_torque_nm=external_torque_nm)
    ids = {
        name: mujoco.mj_name2id(model, kind, name)
        for name, kind in (
            (MOTOR, mujoco.mjtObj.mjOBJ_ACTUATOR),
            ("pelvis", mujoco.mjtObj.mjOBJ_BODY),
            ("torso", mujoco.mjtObj.mjOBJ_BODY),
            ("head", mujoco.mjtObj.mjOBJ_BODY),
        )
    }
    if min(ids.values()) < 0 or model.nu != 55 or model.nv != 61:
        raise ValueError("native_model_or_witness_missing")
    if abs(float(model.body_mass.sum())-78.) > 1e-5:
        raise ValueError("unexpected_canonical_mass")
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    frames = []
    for tick in range(1, CAPTURE_STEPS + 1):
        data.ctrl[:] = 0.
        data.ctrl[ids[MOTOR]] = float(command_nm)
        data.xfrc_applied[:] = 0.
        if 20 <= tick < 160:
            data.xfrc_applied[ids["torso"], 5] = float(external_torque_nm)
        mujoco.mj_step(model, data)
        if tick % SAMPLE_EVERY:
            continue
        idx = len(frames)
        t = float(data.time)
        if abs(t-paired["pose"]["frames"][idx]["t_s"]) > 1e-8:
            raise ValueError("native_trajectory_timestep_diverged")
        q = [float(x) for x in data.qpos[3:7]]
        w,x,y,z = q
        yaw = math.atan2(2.*(w*z+x*y),1.-2.*(y*y+z*z))
        if abs(yaw-paired["primary"]["frames"][idx]["pelvis_yaw_rad"]) > 1e-8:
            raise ValueError("native_trajectory_pose_diverged")
        frame = {"t_s": t}
        for name, key in zip(("pelvis","torso","head"),INERTIAL_KEYS):
            # cvel uses world-frame angular velocity in the first three entries.
            frame[key] = float(data.cvel[ids[name], 2])
        if not all(math.isfinite(v) for v in frame.values()):
            raise ValueError("nonfinite_native_velocity")
        frames.append(frame)
    return {
        **paired,
        "inertial": {
            "quality": INERTIAL_QUALITY,
            "source_sha256": source["sha256"],
            "command_nm": float(command_nm),
            "frames": frames,
        },
    }


def _valid_inertial(trace, source, command, primary):
    if not isinstance(trace,dict):
        return False
    if trace.get("quality") != INERTIAL_QUALITY or trace.get("source_sha256") != source:
        return False
    nm = trace.get("command_nm")
    if type(nm) not in (int,float) or not math.isfinite(nm) or abs(nm-command)>1e-9:
        return False
    rows = trace.get("frames")
    if not isinstance(rows,list) or len(rows) != CAPTURE_STEPS//SAMPLE_EVERY:
        return False
    previous = -math.inf
    for i,row in enumerate(rows):
        if not isinstance(row,dict):
            return False
        if any(type(row.get(key)) not in (int,float) or not math.isfinite(row[key])
               for key in ("t_s",*INERTIAL_KEYS)):
            return False
        if row["t_s"] <= previous or abs(row["t_s"]-primary["frames"][i]["t_s"])>1e-8:
            return False
        previous = row["t_s"]
    return True


def inertial_evidence(prediction, observation):
    if len(prediction["frames"]) != len(observation["frames"]):
        return {"class":"unverified"}
    channels = {}
    for key in INERTIAL_KEYS:
        residual = [ob[key]-pred[key]
                    for pred,ob in zip(prediction["frames"],observation["frames"])]
        positive = sum(x >= INERTIAL_SUPPORT for x in residual)
        negative = sum(x <= -INERTIAL_SUPPORT for x in residual)
        channels[key] = {
            "max_abs_rad_s": max(abs(x) for x in residual),
            "same_sign_support": max(positive, negative),
        }
    max_abs = max(x["max_abs_rad_s"] for x in channels.values())
    supported = [key for key,v in channels.items()
                 if v["max_abs_rad_s"] >= INERTIAL_EXCURSION
                 and v["same_sign_support"] >= INERTIAL_MIN_SIGN_FRAMES]
    status = ("quiet" if max_abs <= INERTIAL_SMALL else
              "coherent" if supported else "uncertain")
    return {"class":status,"max_abs_rad_s":max_abs,
            "supported_inertial_channels":supported}


def fuse_three(reference, prediction, observation, intended_command_nm):
    """Do not treat two-of-three or three-of-three as authenticated observation."""
    if type(intended_command_nm) not in (int,float) or not math.isfinite(intended_command_nm):
        return {"state":"unverified","reason":"invalid_intent"}
    if any(not isinstance(t,dict) or "inertial" not in t for t in
           (reference,prediction,observation)):
        return {"state":"unverified","reason":"inertial_witness_missing"}
    # Earlier v0.3 checks source, pair synchronization, command, finite values.
    dual=fuse_body_evidence(reference,prediction,observation,intended_command_nm)
    if dual["state"]=="unverified":
        return dual
    source=dual["source_sha256"]
    for episode,cmd in (
        (reference,0.),
        (prediction,intended_command_nm),
        (observation,observation["primary"].get("command_nm")),
    ):
        if type(cmd) not in (int,float) or not math.isfinite(cmd):
            return {"state":"unverified","reason":"inertial_command_invalid"}
        if not _valid_inertial(episode["inertial"],source,cmd,episode["primary"]):
            return {"state":"unverified","reason":"inertial_source_or_clock_invalid"}
    motion=inertial_evidence(prediction["inertial"],observation["inertial"])
    if motion["class"]=="unverified":
        return {"state":"unverified","reason":"inertial_trajectory_mismatch"}
    primary = classify_temporal(
        reference["primary"],prediction["primary"],
        observation["primary"],intended_command_nm)
    pose = pose_evidence(prediction["pose"],observation["pose"])
    if primary["state"] == "unverified" or pose["class"] == "unverified":
        return {"state":"unverified","reason":"inconsistent_primary_or_pose"}
    p = primary["state"] in ("unexplained_change","command_outcome_mismatch")
    q = pose["class"] == "coherent"
    r = motion["class"] == "coherent"
    if p and q and r:
        result=("three_view_command_mismatch"
                if abs(intended_command_nm)>1e-9
                else "three_view_unattributed_change")
    elif p and q and not r:
        result="kinematic_veto_common_mode"
    elif p and r and not q:
        result="provisional_motion_pose_unreliable"
    elif q and r and not p:
        result="provisional_motion_primary_unreliable"
    elif p or q or r:
        result="sensor_disagreement_or_uncertain"
    elif (primary["state"]=="no_detectable_change"
          and pose["class"]=="quiet" and motion["class"]=="quiet"):
        result="no_detectable_change"
    elif (primary["state"]=="command_consistent"
          and pose["class"]=="quiet" and motion["class"]=="quiet"):
        result="command_consistent"
    else:
        result="uncertain_noise_or_missing"
    return {
        "state":result,
        "primary_state":primary["state"],
        "pose_evidence_class":pose["class"],
        "inertial_evidence_class":motion["class"],
        "source_sha256":source,
        "cause":"unknown",
        "scope":"THREE_CORRELATED_VIEWS_OF_ONE_SIMULATOR_NOT_EXTERNAL_PROOF",
        "inertial_max_delta_rad_s":motion["max_abs_rad_s"],
        "inertial_support":motion["supported_inertial_channels"],
        "provisional_not_hardware_certification":True,
    }
