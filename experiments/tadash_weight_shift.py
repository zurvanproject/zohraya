"""Bounded bilateral weight-shift probe on the existing pinned v03 Tadash MuJoCo body.

Uses the original torque-limited ContactController with both feet grounded.
This adds a trial script, NOT a learned policy, new actuator or modified body.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys

from experiments import tadash_motion_episode as evidence

SCHEMA = "tadash-weight-shift/1"
MAX_SHIFT_M = 0.004
TRIAL_S = 4
FIRST_SHIFT_M = 0.002
MIN_SHIFT_M = 0.001
MIN_RESPONSE_RATIO = 0.20
NATIVE = r"""
import json, math, sys
import numpy as np
import mujoco
from examples.nasuraya_research.articulated.canon_trial import CANDIDATE
from examples.nasuraya_research.articulated.evaluate import load
from examples.nasuraya_research.articulated.balance import BalanceController
from examples.nasuraya_research.articulated.stepping import ContactController, contact_state, smooth

shift = float(sys.argv[1])
friction = float(sys.argv[2]) if len(sys.argv) > 2 else 0.6
if not math.isfinite(friction) or not 0.45 <= friction <= 0.7:
    raise ValueError("Friction outside frozen experiment range")
if not math.isfinite(shift) or abs(shift) > 0.004:
    raise ValueError("Nonfinite or unapproved shift")

m, d = load(CANDIDATE)
m.opt.timestep = 0.001
m.geom_friction[:, 0] = friction
standing = BalanceController(m, CANDIDATE)
d.qpos[:] = m.qpos0
d.qpos[2] += 0.005
for _ in range(2000):
    d.ctrl[:] = standing.command(d)[0]
    mujoco.mj_step(m, d)
mujoco.mj_forward(m, d)
ctrl = ContactController(m, d, geometry_support=True)
origin = ctrl.com0.copy()
targets = ctrl.anchors.copy()
height = float(standing.q0[2])
peak_tilt = 0.
peak_motor_fraction = 0.
peak_joint_excess = 0.
min_height = float(d.qpos[2])
nonfeet = set()
trace = []
failure = None
held = []
returned = []
last_speed = 0.
both_contact_samples = 0
for i in range(4000):
    t = i * 0.001
    # 1 second smooth outward; 1 second hold; 1 second return; 1 second rest.
    if t < 1:
        amp = smooth(t)
    elif t < 2:
        amp = 1.
    elif t < 3:
        amp = 1 - smooth(t - 2)
    else:
        amp = 0.
    com = origin.copy()
    com[1] += shift * amp
    if i % 5 == 0:
        try:
            d.ctrl[:] = ctrl.command(d, com, targets, [True, True])
        except RuntimeError as exc:
            failure = "solver: " + str(exc)
            break
    d.xfrc_applied[:] = 0.
    mujoco.mj_step(m, d)
    mujoco.mj_forward(m, d)
    if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all() or any(w.number for w in d.warning):
        failure = "nonfinite_or_native_warning"
        break
    forces, other = contact_state(m, d)
    nonfeet.update(other)
    tilt = math.degrees(math.acos(float(np.clip(d.xmat[1].reshape(3, 3)[2, 2], -1, 1))))
    peak_tilt = max(peak_tilt, tilt)
    min_height = min(min_height, float(d.qpos[2]))
    joints = d.qpos[m.jnt_qposadr[1:]]
    excess = float(np.maximum(m.jnt_range[1:, 0] - joints, joints - m.jnt_range[1:, 1]).max())
    peak_joint_excess = max(peak_joint_excess, excess)
    motor = float(np.max(np.abs(d.ctrl) / np.maximum(np.abs(m.actuator_ctrlrange[:, 1]), 1e-12)))
    peak_motor_fraction = max(peak_motor_fraction, motor)
    both_contact_samples += int(bool(np.all(forces > 1.)))
    if i % 50 == 0:
        trace.append({"t_s": round(t, 3), "commanded_y_shift_m": float(shift * amp),
                      "observed_com_y_delta_m": float(d.subtree_com[1, 1] - origin[1]),
                      "foot_normal_n": forces.tolist(), "tilt_deg": tilt})
    if 1.5 <= t < 2.:
        held.append(float(d.subtree_com[1, 1] - origin[1]))
    if 3.5 <= t < 4.:
        returned.append(float(d.subtree_com[1, 1] - origin[1]))
        last_speed = max(last_speed, float(np.max(np.abs(d.qvel))))
    if other or tilt > 20 or excess > .02 or d.qpos[2] < .8 * height:
        failure = "balance_contact_or_joint_limit_guard"
        break
completed = len(returned) == 500 and failure is None
print(json.dumps({
    "schema": "native-v03-bilateral-shift/1",
    "requested_shift_y_m": shift, "friction": friction, "seconds_requested": 4.,
    "seconds_completed": float(d.time - 2.),
    "completed": completed, "failure": failure,
    "held_com_y_delta_m": float(np.mean(held)) if held else None,
    "returned_com_y_delta_m": float(np.mean(returned)) if returned else None,
    "peak_tilt_deg": peak_tilt, "peak_motor_fraction": peak_motor_fraction,
    "peak_joint_limit_excess_rad": peak_joint_excess, "min_pelvis_height_m": min_height,
    "last_half_second_max_speed": last_speed,
    "both_feet_loaded_fraction": both_contact_samples / 4000,
    "nonfoot_contacts": sorted(nonfeet), "qp_solves": ctrl.solves, "trace": trace,
    "controller": "original_v03_contact_QP_both_feet_grounded",
    "body_model": "unchanged_78kg_v03",
    "no_weight_update": True, "no_root_actuator": True
}, ensure_ascii=False, allow_nan=False))
"""


def finite(value):
    return evidence.finite(value)


def validate(native, requested):
    if not isinstance(native, dict) or native.get("schema") != "native-v03-bilateral-shift/1":
        raise ValueError("Wrong native result schema")
    if not math.isclose(finite(native.get("requested_shift_y_m")), requested, abs_tol=1e-12):
        raise ValueError("Wrong shift target")
    if native.get("completed") is not True or native.get("failure") is not None:
        raise ValueError("Incomplete or failed trial: cannot automatically retry")
    if native.get("no_weight_update") is not True or native.get("no_root_actuator") is not True:
        raise ValueError("Unsafe controller claim")
    if native.get("nonfoot_contacts") != []:
        raise ValueError("Nonfoot ground contact")
    if native.get("controller") != "original_v03_contact_QP_both_feet_grounded":
        raise ValueError("Unexpected controller")
    for k in ("seconds_completed", "held_com_y_delta_m", "returned_com_y_delta_m",
              "peak_tilt_deg", "peak_motor_fraction", "peak_joint_limit_excess_rad",
              "last_half_second_max_speed", "both_feet_loaded_fraction"):
        finite(native.get(k))
    if not (3.999 <= native["seconds_completed"] <= 4.001 and
            0 <= native["peak_tilt_deg"] <= 20 and
            0 <= native["peak_motor_fraction"] <= 1.000001 and
            0 <= native["peak_joint_limit_excess_rad"] <= 0.02 and
            0 <= native["last_half_second_max_speed"] < 0.05 and
            0.90 <= native["both_feet_loaded_fraction"] <= 1.):
        raise ValueError("Native guard violated")
    if not isinstance(native.get("trace"), list) or len(native["trace"]) != 80:
        raise ValueError("Missing time-series evidence")
    return True


def outcome(native, baseline):
    target = native["requested_shift_y_m"]
    signal = native["held_com_y_delta_m"] - baseline["held_com_y_delta_m"]
    # A signed, independently measured response, not a self-reported controller success.
    return ("met" if (signal * target > 0 and abs(signal) >= MIN_RESPONSE_RATIO * abs(target)
                       and abs(native["returned_com_y_delta_m"] - baseline["returned_com_y_delta_m"]) < 0.003)
            else "not_met"), signal


def next_magnitude(magnitude, state):
    if magnitude not in (MIN_SHIFT_M, FIRST_SHIFT_M) or state not in ("met", "not_met"):
        raise ValueError("Invalid curriculum transition")
    if state == "met":
        return magnitude, "repeat_to_check_same_direction"
    if magnitude > MIN_SHIFT_M:
        return MIN_SHIFT_M, "simplify_verified_insufficient_response"
    return None, "stop_at_smallest"


def run(source, output, timeout=240):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.is_relative_to(source):
        raise ValueError("Output must not overlap pinned source")
    if type(timeout) is not int or not 30 <= timeout <= 600:
        raise ValueError("Bad timeout")
    identity = evidence.source_identity(source)
    code_sha = evidence.sha(Path(__file__))
    output.mkdir(parents=True, exist_ok=False)
    plan = {"schema": SCHEMA, "source": identity, "script_sha256": code_sha,
            "method": "original ContactController bilateral fixed feet, native physics",
            "baseline_y_m": 0.0, "positive_and_negative_m": [FIRST_SHIFT_M, -FIRST_SHIFT_M],
            "fallback_y_m": MIN_SHIFT_M, "max_native_trials": 5,
            "four_phases_seconds": [1, 1, 1, 1], "response_threshold_ratio": MIN_RESPONSE_RATIO,
            "no_learning_or_generalization_claim": True}
    evidence.write(output / "plan.json", plan)
    planhash = evidence.sha(output / "plan.json")
    evidence.write(output / "status.json", {"status": "running", "utc": datetime.now(timezone.utc).isoformat()})
    rows = []
    try:
        def perform(shift, label):
            if evidence.source_identity(source) != identity or evidence.sha(Path(__file__)) != code_sha:
                raise ValueError("Pinned source or harness drifted")
            if not math.isfinite(shift) or abs(shift) > MAX_SHIFT_M:
                raise ValueError("Out-of-bounds shift")
            basename = f"trial-{len(rows) + 1:02d}"
            intention = {"schema": "weight-shift-intention/1", "label": label,
                         "shift_y_m": shift, "plan_sha256": planhash}
            evidence.write(output / f"{basename}-intention.json", intention)
            try:
                process = subprocess.run([sys.executable, "-c", NATIVE, str(shift)],
                                         cwd=source, env=evidence.clean_env(), capture_output=True,
                                         text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Native shift timed out; no auto retry") from exc
            (output / f"{basename}.stdout.log").write_text(process.stdout)
            (output / f"{basename}.stderr.log").write_text(process.stderr)
            if process.returncode:
                raise RuntimeError(f"Native process {basename} failed with code {process.returncode}")
            raw = json.loads(process.stdout, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
            evidence.write(output / f"{basename}-native.json", raw)
            validate(raw, shift)
            row = {"label": label, "shift_y_m": shift,
                   "intention_sha256": evidence.sha(output / f"{basename}-intention.json"),
                   "raw_sha256": evidence.sha(output / f"{basename}-native.json"),
                   "held_com_y_delta_m": raw["held_com_y_delta_m"],
                   "returned_com_y_delta_m": raw["returned_com_y_delta_m"],
                   "peak_tilt_deg": raw["peak_tilt_deg"],
                   "peak_motor_fraction": raw["peak_motor_fraction"],
                   "both_feet_loaded_fraction": raw["both_feet_loaded_fraction"]}
            evidence.write(output / f"{basename}-receipt.json", row)
            rows.append(row)
            return raw
        baseline = perform(0.0, "control_no_shift")
        for direction in (+1, -1):
            first = perform(direction * FIRST_SHIFT_M, "outward")
            first_state, observed = outcome(first, baseline)
            rows[-1]["outcome"] = first_state
            rows[-1]["response_vs_baseline_m"] = observed
            # Record interpretation AFTER raw measurement, separately from receipt.
            evidence.write(output / f"trial-{len(rows):02d}-interpretation.json",
                           {"outcome": first_state, "response_vs_baseline_m": observed,
                            "rule": "positive_signed_response >=20% and return <3mm"})
            new_magnitude, choice = next_magnitude(FIRST_SHIFT_M, first_state)
            if first_state == "not_met":
                fallback = perform(direction * new_magnitude, "simplified")
                state, measured = outcome(fallback, baseline)
                rows[-1]["outcome"] = state
                rows[-1]["response_vs_baseline_m"] = measured
                evidence.write(output / f"trial-{len(rows):02d}-interpretation.json",
                               {"outcome": state, "response_vs_baseline_m": measured,
                                "rule": choice})
            else:
                repeat = perform(direction * FIRST_SHIFT_M, "repeat")
                state, measured = outcome(repeat, baseline)
                rows[-1]["outcome"] = state
                rows[-1]["response_vs_baseline_m"] = measured
                evidence.write(output / f"trial-{len(rows):02d}-interpretation.json",
                               {"outcome": state, "response_vs_baseline_m": measured,
                                "rule": choice})
        if evidence.source_identity(source) != identity or evidence.sha(output / "plan.json") != planhash:
            raise ValueError("Source/plan drift")
        summary = {"schema": SCHEMA, "status": "complete", "source": identity, "plan_sha256": planhash,
                   "trials": len(rows), "observations": rows,
                   "learning_established": False, "generalization_established": False,
                   "purpose": "native fixed-controller primitive weight-shift response & bounded curriculum"}
        evidence.write(output / "summary.json", summary)
        evidence.write(output / "status.json",
                       {"status": "complete", "summary_sha256": evidence.sha(output / "summary.json")},
                       replace=True)
        return summary
    except BaseException as exc:
        evidence.write(output / "status.json",
                       {"status": "failed_or_unknown", "error_type": type(exc).__name__,
                        "completed_trials": len(rows), "no_automatic_retry": True},
                       replace=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    print(json.dumps(run(args.motion_source, args.output, args.timeout),
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
