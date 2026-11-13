"""Embodied origin v0.1: native MuJoCo 78 kg efference/afference consistency.

A read-only lab for prediction-versus-observation. An unexplained residual is NOT
proof of an external stimulus: sensor noise, missing data and model error can
also cause it. No consciousness, clinical anatomy or hardware claim is made.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "assets/nasuraya_articulated_v03/nasuraya.xml"
PINNED_GIT_BLOB = "b7177c1a43715a8eb27e1f837c7c72bbbcee932e"
FEATURES = (
    ("pelvis_yaw_rad", 1.0),
    ("tail_yaw_rad", 1.0),
    ("com_x_m", 3.0),
    ("com_y_m", 3.0),
    ("foot_left_n", 0.002),
    ("foot_right_n", 0.002),
)
THRESHOLD = 0.025  # frozen engineering distance, not a calibrated noise bound
CAPTURE_STEPS = 240
SAMPLE_EVERY = 20


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\\0" + data).hexdigest()


def source_identity(path=MODEL):
    path = Path(path)
    raw = path.read_bytes()
    blob = git_blob_sha(raw)
    if blob != PINNED_GIT_BLOB:
        raise ValueError("model_source_pin_mismatch:" + blob)
    return {"git_blob_sha1": blob, "sha256": hashlib.sha256(raw).hexdigest()}


def _yaw(quaternion):
    w, x, y, z = (float(v) for v in quaternion)
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def _contacts(model, data, mujoco, np):
    result = {"L": 0.0, "R": 0.0}
    floor_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
    for i in range(data.ncon):
        contact = data.contact[i]
        a, b = int(contact.geom1), int(contact.geom2)
        if floor_id not in (a, b):
            continue
        other = b if a == floor_id else a
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, other) or ""
        for side in ("L", "R"):
            if name == "ball_" + side or name.startswith("toe_pad_" + side + "_"):
                f = np.zeros(6, dtype=float)
                mujoco.mj_contactForce(model, data, i, f)
                result[side] += max(float(f[0]), 0.0)
    return result


def capture_native(model, mujoco, np, identity, command_nm=0.0, external_torque_nm=0.0):
    """Fresh native trajectory. Exogenous torque is NOT visible to the interpreter."""
    if not all(math.isfinite(float(v)) for v in (command_nm, external_torque_nm)):
        raise ValueError("non_finite_stimulus")
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    motor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "tail_yaw_1_motor")
    joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "tail_yaw_1")
    pelvis = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    torso = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "torso")
    if min(motor, joint, pelvis, torso) < 0:
        raise ValueError("required_mujoco_name_missing")
    if not (model.actuator_ctrlrange[motor, 0] <= command_nm <=
            model.actuator_ctrlrange[motor, 1]):
        raise ValueError("motor_command_out_of_range")
    frames = []
    for step in range(1, CAPTURE_STEPS + 1):
        data.ctrl[:] = 0
        data.ctrl[motor] = command_nm
        data.xfrc_applied[:] = 0
        if 20 <= step < 160:
            data.xfrc_applied[torso, 5] = external_torque_nm
        mujoco.mj_step(model, data)
        if step % SAMPLE_EVERY:
            continue
        ground = _contacts(model, data, mujoco, np)
        row = {
            "t_s": float(data.time),
            "pelvis_yaw_rad": _yaw(data.qpos[3:7]),
            "tail_yaw_rad": float(data.qpos[model.jnt_qposadr[joint]]),
            "com_x_m": float(data.subtree_com[pelvis, 0]),
            "com_y_m": float(data.subtree_com[pelvis, 1]),
            "foot_left_n": ground["L"],
            "foot_right_n": ground["R"],
        }
        if not all(math.isfinite(v) for v in row.values()):
            raise ValueError("non_finite_native_telemetry")
        frames.append(row)
    return {
        "source_sha256": identity["sha256"],
        "quality": "native_simulated",
        "command_nm": float(command_nm),
        "frames": frames,
    }


def _validated(trace, expected_sha):
    if not isinstance(trace, dict) or trace.get("source_sha256") != expected_sha:
        return False
    if trace.get("quality") != "native_simulated":
        return False
    command = trace.get("command_nm")
    if type(command) not in (int, float) or not math.isfinite(command):
        return False
    frames = trace.get("frames")
    if not isinstance(frames, list) or len(frames) != CAPTURE_STEPS // SAMPLE_EVERY:
        return False
    last = -math.inf
    for row in frames:
        if not isinstance(row, dict):
            return False
        keys = ("t_s", *(f for f, _ in FEATURES))
        if any(type(row.get(k)) not in (int, float) or
               not math.isfinite(row[k]) for k in keys):
            return False
        if row["t_s"] <= last or row["foot_left_n"] < 0 or row["foot_right_n"] < 0:
            return False
        last = row["t_s"]
    return True


def deviation(a, b):
    """Max normalized vector residual; always compare equal native time grids."""
    if len(a["frames"]) != len(b["frames"]):
        return math.inf
    worst = 0.0
    for left, right in zip(a["frames"], b["frames"]):
        if abs(left["t_s"] - right["t_s"]) > 1e-8:
            return math.inf
        worst = max(worst, *(abs(left[key] - right[key]) * scale
                             for key, scale in FEATURES))
    return worst


def interpret(reference, prediction, actual, intended_command_nm, threshold=THRESHOLD):
    """Compare efference copy and measured simulated body; never infer awareness."""
    if type(intended_command_nm) not in (int, float) or not math.isfinite(intended_command_nm):
        return {"state": "unverified", "reason": "invalid_intent"}
    if not (math.isfinite(threshold) and threshold > 0):
        return {"state": "unverified", "reason": "invalid_threshold"}
    source = reference.get("source_sha256") if isinstance(reference, dict) else None
    if not source or not all(_validated(t, source) for t in (reference, prediction, actual)):
        return {"state": "unverified", "reason": "invalid_or_untrusted_telemetry"}
    if abs(reference["command_nm"]) > 1e-9 or abs(prediction["command_nm"] - intended_command_nm) > 1e-9:
        return {"state": "unverified", "reason": "prediction_command_mismatch"}
    predicted_change = deviation(reference, prediction)
    observed_change = deviation(reference, actual)
    residual = deviation(prediction, actual)
    values = {"predicted_change": predicted_change,
              "observed_change": observed_change, "prediction_residual": residual,
              "threshold": threshold}
    if not all(math.isfinite(v) for v in values.values()):
        return {"state": "unverified", "reason": "incompatible_time_grid"}
    if abs(intended_command_nm) <= 1e-9:
        state = "unexplained_change" if observed_change > threshold or abs(actual["command_nm"]) > 1e-9 else "no_detectable_change"
    elif predicted_change <= threshold:
        state = "unverified"
    elif residual <= threshold and abs(actual["command_nm"] - intended_command_nm) <= 1e-9:
        state = "command_consistent"
    else:
        state = "command_outcome_mismatch"
    return {"state": state, "metrics": values,
            "scope": "known-native-physics command/afference consistency only"}


def run_experiment(path=MODEL):
    import mujoco
    import numpy as np

    source = source_identity(path)
    model = mujoco.MjModel.from_xml_path(str(path))
    if model.nu != 55 or model.nv != 61 or abs(float(model.body_mass.sum()) - 78) > 1e-5:
        raise ValueError("unexpected_compiled_body")
    rest = capture_native(model, mujoco, np, source)
    expected = capture_native(model, mujoco, np, source, command_nm=8.0)
    replicate = capture_native(model, mujoco, np, source, command_nm=8.0)
    disturbance = capture_native(model, mujoco, np, source, external_torque_nm=35.0)
    combined = capture_native(model, mujoco, np, source, command_nm=8.0, external_torque_nm=35.0)
    degraded = copy.deepcopy(rest)
    degraded["quality"] = "synthetic_noise_not_native"
    degraded["frames"][3]["tail_yaw_rad"] += 2.0
    scenarios = {
        "no_command_control": interpret(rest, rest, rest, 0.0),
        "motor_command_repeated": interpret(rest, expected, replicate, 8.0),
        "uncommanded_exogenous_torque": interpret(rest, rest, disturbance, 0.0),
        "command_with_exogenous_torque": interpret(rest, expected, combined, 8.0),
        "degraded_sensor_only": interpret(rest, rest, degraded, 0.0),
    }
    requirements = {
        "no_command_control": "no_detectable_change",
        "motor_command_repeated": "command_consistent",
        "uncommanded_exogenous_torque": "unexplained_change",
        "command_with_exogenous_torque": "command_outcome_mismatch",
        "degraded_sensor_only": "unverified",
    }
    passed = {name: scenarios[name]["state"] == label for name, label in requirements.items()}
    return {
        "pass": all(passed.values()),
        "source": source,
        "mujoco_version": mujoco.__version__,
        "protocol": {"steps": CAPTURE_STEPS, "sample_every": SAMPLE_EVERY,
                     "native_timestep_s": float(model.opt.timestep),
                     "motor_nm": 8.0, "external_torque_nm": 35.0,
                     "threshold": THRESHOLD, "metric_weights": FEATURES},
        "scenario_checks": passed, "scenarios": scenarios,
        "limits": [
            "Native deterministic simulated joint/contact/COM feedback only",
            "No sensor noise estimator; corrupted data must abstain or remain unexplained",
            "Source-consistent motion does not prove subjective self-awareness",
            "No hardware, tissue, real proprioception or live memory/DIOS connection",
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    try:
        report = run_experiment()
    except Exception as exc:
        report = {"pass": False, "error": type(exc).__name__ + ":" + str(exc)}
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
