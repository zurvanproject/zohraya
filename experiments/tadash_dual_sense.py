"""Tadash v0.3: two *simulated*, non-identical pose/kinematic readouts.

Proprioceptive encoder samples joint angles/COM/contact. A second virtual
pose observer samples MuJoCo world-frame landmark positions and torso matrix.
They are different measurements, but derive from the SAME native solver and are
NOT independent physical instruments. Agreement does not certify real motion.
"""
from __future__ import annotations

import math

from experiments.tadash_embodied_origin import (
    CAPTURE_STEPS, SAMPLE_EVERY, FEATURES, THRESHOLD, MODEL,
    _contacts, _validated, capture_native, source_identity,
)
from experiments.tadash_temporal_proprioception import (
    _temporal_features, classify_temporal,
)

POSE_WEIGHTS = {
    "torso_yaw": 1.0,
    "head_yaw": 1.0,
    "tail_4_x": 2.0,
    "tail_4_y": 2.0,
    "head_x": 2.0,
    "head_y": 2.0,
}
POSE_QUALITY = "native_simulated_world_pose"
MOTOR = "tail_yaw_1_motor"
JOINT = "tail_yaw_1"


def capture_paired(model, mujoco, np, source, command_nm=0., external_torque_nm=0.):
    """Two channels captured on the *same actual timestep*, no classifier oracle."""
    if not all(type(x) in (float, int) and math.isfinite(x)
               for x in (command_nm, external_torque_nm)):
        raise ValueError("non_finite_input")
    ids = {
        name: mujoco.mj_name2id(model, kind, name)
        for name, kind in (
            (MOTOR, mujoco.mjtObj.mjOBJ_ACTUATOR),
            (JOINT, mujoco.mjtObj.mjOBJ_JOINT),
            ("pelvis", mujoco.mjtObj.mjOBJ_BODY),
            ("torso", mujoco.mjtObj.mjOBJ_BODY),
            ("head", mujoco.mjtObj.mjOBJ_BODY),
            ("tail_4", mujoco.mjtObj.mjOBJ_BODY),
        )
    }
    if min(ids.values()) < 0 or model.nu != 55 or model.nv != 61:
        raise ValueError("model_geometry_or_motor_changed")
    if not (model.actuator_ctrlrange[ids[MOTOR], 0] <= command_nm
            <= model.actuator_ctrlrange[ids[MOTOR], 1]):
        raise ValueError("motor_out_of_range")
    if abs(float(model.body_mass.sum()) - 78.) > 1e-5:
        raise ValueError("canonical_mass_mismatch")
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    primary_frames, pose_frames = [], []
    for tick in range(1, CAPTURE_STEPS + 1):
        data.ctrl[:] = 0.
        data.ctrl[ids[MOTOR]] = command_nm
        data.xfrc_applied[:] = 0.
        if 20 <= tick < 160:
            data.xfrc_applied[ids["torso"], 5] = external_torque_nm
        mujoco.mj_step(model, data)
        if tick % SAMPLE_EVERY:
            continue
        q = [float(x) for x in data.qpos[3:7]]
        w, x, y, z = q
        pelvis_yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
        ground = _contacts(model, data, mujoco, np)
        primary = {
            "t_s": float(data.time),
            "pelvis_yaw_rad": pelvis_yaw,
            "tail_yaw_rad": float(data.qpos[model.jnt_qposadr[ids[JOINT]]]),
            "com_x_m": float(data.subtree_com[ids["pelvis"], 0]),
            "com_y_m": float(data.subtree_com[ids["pelvis"], 1]),
            "foot_left_n": ground["L"], "foot_right_n": ground["R"],
        }
        torso_matrix = data.xmat[ids["torso"]]
        head_matrix = data.xmat[ids["head"]]
        pose = {
            "t_s": float(data.time),
            "torso_yaw": math.atan2(float(torso_matrix[3]), float(torso_matrix[0])),
            "head_yaw": math.atan2(float(head_matrix[3]), float(head_matrix[0])),
            "tail_4_x": float(data.xpos[ids["tail_4"], 0]),
            "tail_4_y": float(data.xpos[ids["tail_4"], 1]),
            "head_x": float(data.xpos[ids["head"], 0]),
            "head_y": float(data.xpos[ids["head"], 1]),
        }
        if not all(math.isfinite(v) for v in (*primary.values(), *pose.values())):
            raise ValueError("non_finite_native_readout")
        primary_frames.append(primary)
        pose_frames.append(pose)
    return {
        "primary": {
            "quality": "native_simulated",
            "source_sha256": source["sha256"],
            "command_nm": float(command_nm),
            "frames": primary_frames,
        },
        "pose": {
            "quality": POSE_QUALITY,
            "source_sha256": source["sha256"],
            "command_nm": float(command_nm),
            "frames": pose_frames,
        },
    }


def _valid_pose(trace, expected_source, command):
    if not isinstance(trace, dict):
        return False
    if trace.get("quality") != POSE_QUALITY or trace.get("source_sha256") != expected_source:
        return False
    if type(trace.get("command_nm")) not in (float, int):
        return False
    if abs(trace["command_nm"] - command) > 1e-9:
        return False
    frames = trace.get("frames")
    if not isinstance(frames, list) or len(frames) != CAPTURE_STEPS//SAMPLE_EVERY:
        return False
    previous = -math.inf
    for row in frames:
        if not isinstance(row, dict):
            return False
        keys = ("t_s", *POSE_WEIGHTS)
        if any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k])
               for k in keys):
            return False
        if row["t_s"] <= previous:
            return False
        previous = row["t_s"]
    return True


def _same_grid(primary, pose):
    return all(abs(p["t_s"]-v["t_s"]) <= 1e-8
               for p, v in zip(primary["frames"], pose["frames"]))


def pose_evidence(expected, actual):
    if not all(abs(a["t_s"]-b["t_s"]) <= 1e-8
               for a,b in zip(expected["frames"], actual["frames"])):
        return {"class": "unverified", "max_residual": None}
    evidence = {}
    for key, weight in POSE_WEIGHTS.items():
        residuals = [(a[key]-b[key])*weight
                     for a,b in zip(actual["frames"], expected["frames"])]
        evidence[key] = _temporal_features(residuals)
    maximum = max(i["max_abs_normalized_residual"] for i in evidence.values())
    supported = [key for key, info in evidence.items() if info["temporally_supported"]]
    category = ("quiet" if maximum <= THRESHOLD else
                "coherent" if len(supported) >= 2 else "uncertain")
    return {"class": category, "max_residual": maximum,
            "supported_virtual_pose_channels": supported,
            "temporal_features": evidence}


def fuse_body_evidence(reference, prediction, observation, intended_command_nm):
    """Two simulated data modalities agree/disagree; always leave cause unknown."""
    if type(intended_command_nm) not in (float, int) or not math.isfinite(intended_command_nm):
        return {"state": "unverified", "reason": "invalid_intent"}
    if not all(isinstance(t, dict) and "primary" in t and "pose" in t
               for t in (reference,prediction,observation)):
        return {"state": "unverified", "reason": "missing_modality"}
    source = reference["primary"].get("source_sha256")
    if not source:
        return {"state": "unverified", "reason": "source_missing"}
    pairs = ((reference, 0.),
             (prediction, intended_command_nm),
             (observation, observation["primary"].get("command_nm")))
    for item, command in pairs:
        if type(command) not in (int,float) or not math.isfinite(command):
            return {"state": "unverified", "reason": "command_invalid"}
        if not _validated(item["primary"], source):
            return {"state": "unverified", "reason": "primary_validation"}
        if not _valid_pose(item["pose"], source, command):
            return {"state": "unverified", "reason": "pose_validation"}
        if not _same_grid(item["primary"], item["pose"]):
            return {"state": "unverified", "reason": "desynchronized_sensors"}
    primary = classify_temporal(reference["primary"],prediction["primary"],
                                observation["primary"],intended_command_nm)
    if primary["state"] == "unverified":
        return {"state": "unverified", "reason": primary.get("reason","primary_unverified")}
    witness = pose_evidence(prediction["pose"], observation["pose"])
    if witness["class"] == "unverified":
        return {"state": "unverified", "reason": "pose_grid_mismatch"}
    expected_witness = pose_evidence(reference["pose"], prediction["pose"])
    if abs(intended_command_nm) > 1e-9 and expected_witness["class"] == "quiet":
        return {"state": "unverified", "reason": "pose_prediction_nonidentifying"}
    pstate, wstate = primary["state"], witness["class"]
    if pstate in ("no_detectable_change","command_consistent"):
        if wstate == "quiet":
            state = pstate
        elif wstate == "coherent":
            state = "sensor_disagreement"
        else:
            state = "uncertain_noise_or_missing"
    elif pstate in ("unexplained_change","command_outcome_mismatch"):
        if wstate == "coherent":
            state = ("agreement_unattributed_change"
                     if pstate == "unexplained_change" else "agreement_command_mismatch")
        elif wstate == "quiet":
            state = "sensor_disagreement"
        else:
            state = "uncertain_noise_or_missing"
    else:
        state = "uncertain_noise_or_missing"
    return {
        "state": state,
        "primary_state": pstate,
        "pose_evidence_class": wstate,
        "primary_residual": primary.get("residual"),
        "pose_residual": witness["max_residual"],
        "supported_pose_channels": witness.get("supported_virtual_pose_channels",[]),
        "scope": "two_virtual_modalities_one_MuJoCo_solver_not_independent_hardware",
        "source_sha256": source,
        "causal_origin": "unknown",
    }
