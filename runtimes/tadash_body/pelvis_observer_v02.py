"""Opt-in, read-only pelvis overlay for recorded/supplied Tadash V06 posture data.

Does NOT call BodyLoop, modify a checkpoint, advance simulated time, sense nerves,
measure biology, infer desire or authorize motor actions. Input source labels are
CLAIMS provided by a caller, not authentication or independent provenance.
"""
from math import cos, isfinite, sin, sqrt
import re

from .pelvis_v01 import FIXTURES, evaluate_pelvis

SCHEMA = "tadash-pelvis-observer/0.2"
SUPPORTED = {"posture_step_v06_report", "body_mirror_v06_record"}
PHASES = {
    "double_support", "shift", "lift", "single_support", "walk_swing",
    "lower", "protective_swing", "settle", "failed",
}


def _finite(value, name, low, high):
    if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return float(value)


def _vec(values, size, name, limit=10.0):
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise ValueError(f"{name} needs {size} coordinates")
    return [_finite(v, name, -limit, limit) for v in values]


def _hip(joints, side):
    if not isinstance(joints, dict) or side not in joints:
        raise ValueError(f"missing {side} hip")
    return _vec(joints[side], 3, f"hip_{side}")


def _extract_frame(frame):
    """Accept an existing V06 report or body-mirror record; never step a loop."""
    if type(frame) is not dict or frame.get("source") not in SUPPORTED:
        raise ValueError("explicit supported V06 source label required")
    source = frame["source"]
    if source == "posture_step_v06_report":
        posture = frame.get("posture")
        balance = frame.get("balance")
        if not isinstance(posture, dict) or not isinstance(balance, dict):
            raise ValueError("V06 posture and balance reports required")
        kinematics = posture.get("kinematics")
        if not isinstance(kinematics, dict):
            raise ValueError("missing V06 kinematics")
        hips = {}
        for side in ("L", "R"):
            leg = kinematics.get(side)
            if not isinstance(leg, dict) or not isinstance(leg.get("joints_m"), dict):
                raise ValueError("missing V06 leg joints")
            hips[side] = leg["joints_m"].get("hip")
        if type(balance.get("model_valid")) is not bool:
            raise ValueError("invalid balance validity")
        margin = balance.get("capture_margin_m")
        if margin is not None:
            margin = _finite(margin, "capture margin", -10., 10.)
        validity = balance["model_valid"]
        revision = None
        checkpoint = None
    else:
        posture = frame.get("record")
        if not isinstance(posture, dict):
            raise ValueError("recorded body-mirror fixture required")
        joints = posture.get("joints_m")
        if not isinstance(joints, dict):
            raise ValueError("missing mirrored joints")
        hips = {}
        for side in ("L", "R"):
            leg = joints.get(side)
            if not isinstance(leg, dict):
                raise ValueError("missing mirrored leg")
            hips[side] = leg.get("hip")
        revision = posture.get("revision")
        checkpoint = posture.get("checkpoint_sha256")
        if type(revision) is not int or not 1 <= revision <= 1_000_000:
            raise ValueError("invalid body-mirror revision")
        if not isinstance(checkpoint, str) or not re.fullmatch(r"[0-9a-f]{64}", checkpoint):
            raise ValueError("invalid checkpoint label")
        validity = posture.get("phase") != "failed"
        margin = None

    phase = posture.get("phase")
    if phase not in PHASES:
        raise ValueError("unsupported V06 gait phase")
    com = _vec(posture.get("com_m"), 2, "COM")
    tail = _vec(posture.get("tail_angle_rad"), 2, "tail angle", limit=.65 + 1e-8)
    out_hips = {side: _hip(hips, side) for side in ("L", "R")}
    if source == "posture_step_v06_report" and validity == (phase == "failed"):
        raise ValueError("balance model-valid flag conflicts with failed phase")
    return source, phase, com, tail, out_hips, validity, margin, revision, checkpoint


def observe_pelvis(frame, *, profile="runtime_250_195", intra_abdominal_pressure_kpa=2.,
                   floor_activation=0.):
    """Generate a new immutable-by-convention report from a *supplied* snapshot.

    V06 posture motion assumes 195kg/250cm. The 170cm portrait model cannot
    be silently merged with its joint coordinates, so mixed-scale inputs fail.
    Both pressure and contraction remain explicit synthetic test parameters.
    """
    if profile != "runtime_250_195":
        raise ValueError("V06 posture can only overlay runtime_250_195; no portrait rescaling")
    source, phase, com, tail, hips, valid, margin, revision, checkpoint = _extract_frame(frame)
    d = FIXTURES[profile]
    if any(abs(hips[side][axis] - ([com[0] + (1 if side == 'L' else -1) * d.hip_half_width_m,
                                   com[1], d.hip_height_m][axis])) > 1e-6
           for side in ("L", "R") for axis in range(3)):
        raise ValueError("V06 hip anchors inconsistent with COM or phenotype fixture")
    if max(abs(v) for v in com) > .25:
        raise ValueError("COM exceeds calibrated synthetic offset domain")

    mechanical = evaluate_pelvis(
        profile=profile, com_left_m=com[0], com_forward_m=com[1],
        intra_abdominal_pressure_kpa=intra_abdominal_pressure_kpa,
        floor_activation=floor_activation,
    )
    world_landmarks = {
        name: [round(v + (com[axis] if axis < 2 else 0.), 7)
               for axis, v in enumerate(point)]
        for name, point in mechanical["landmarks_m"].items()
    }
    root = world_landmarks["sacrum_tail_root"]
    floor = world_landmarks["pelvic_floor_center"]
    scale = d.stature_m / 2.50
    nodes = {
        "lumbar_reference": [root[0], round(root[1] + .02 * scale, 7), round(root[2] + .15 * scale, 7)],
        "sacral_root_L": [round(root[0] + .035 * scale, 7), root[1], root[2]],
        "sacral_root_R": [round(root[0] - .035 * scale, 7), root[1], root[2]],
        "perineal_sensor_L": [round(floor[0] + .04 * scale, 7), floor[1], floor[2]],
        "perineal_sensor_R": [round(floor[0] - .04 * scale, 7), floor[1], floor[2]],
    }
    routing = {
        side: ["lumbar_reference", "sacral_root_" + side, "perineal_sensor_" + side]
        for side in ("L", "R")
    }
    # Retained V06 uses these direction terms without normalization. Here the
    # overlay normalizes its *hypothetical* sacral-root vector to prevent the
    # slight length inflation when both tail angles are nonzero.
    tail_direction = [sin(tail[0]), -cos(tail[0]) * cos(tail[1]), sin(tail[1])]
    direction_norm = sqrt(sum(v * v for v in tail_direction))
    tail_tip = [
        round(root[i] + d.tail_length_m * tail_direction[i] / direction_norm, 7)
        for i in range(3)
    ]
    tail_length_check = sqrt(sum((a - b)**2 for a, b in zip(tail_tip, root)))
    strain_proxy = min(1., mechanical["floor_deflection_m"] / d.max_deflection_m)
    tail_proxy = min(1., max(abs(v) for v in tail) / .65)
    afferent_proxy = round(min(1., .75 * strain_proxy + .25 * tail_proxy), 6)
    reasons = []
    if mechanical["floor_saturated"]:
        reasons.append("synthetic_floor_capacity_exceeded")
    if phase == "failed" or not valid:
        reasons.append("V06_posture_failed")
    if margin is not None and margin < 0.:
        reasons.append("capture_point_outside_support")
    return {
        "schema": SCHEMA,
        "source_declared": source,
        "source_authentication": "not_cryptographically_verified_by_observer",
        "profile": profile,
        "revision_label": revision,
        "checkpoint_label": checkpoint,
        "gait_phase": phase,
        "com_m": com,
        "hip_anchors_m": hips,
        "pelvis_landmarks_world_m": world_landmarks,
        "lumbar_sacral_and_perineal_proxy_nodes_m": nodes,
        "hypothetical_afferent_routes": routing,
        "route_scope": "geometric_illustration_not_anatomic_nerve_trace",
        "sacral_tail_tip_m": tail_tip,
        "tail_root_distance_m": round(tail_length_check, 6),
        "afferent_mechanical_load_proxy": afferent_proxy,
        "afferent_scope": "synthetic_mechanical_attention_only_not_sensation",
        "pelvic_floor": {
            "load_n": mechanical["floor_load_n"],
            "deflection_m": mechanical["floor_deflection_m"],
            "residual_load_n": mechanical["floor_residual_load_n"],
            "synthetic_capacity_exceeded": mechanical["floor_saturated"],
        },
        "hip_roll_moment_nm": mechanical["hip_roll_moment_nm"],
        "hip_pitch_moment_nm": mechanical["hip_pitch_moment_nm"],
        "capture_margin_m": margin,
        "guard": "review_required" if reasons else "within_synthetic_fixture",
        "guard_reasons": reasons,
        "native_cycles_caused": 0,
        "actuation_authorized": False,
        "sexual_state_inferred": False,
        "subjective_state_inferred": False,
    }
