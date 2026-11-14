"""Read-only spinal/sacral/tail postural reflex advisory for Tadash.

Input is an existing native software checkpoint and its simulated encoders.
Only a conservative walk->observe suggestion may be passed to the agent policy;
the native protective veto and postural controller always remain authoritative.
No motor/neuronal/visceral action is performed by this module.
"""
from copy import deepcopy
import math

SCHEMA = "tadash-spinal-postural-feedback/1"
SOURCE = "native_software_proprioceptive_encoders"

def number(x, key, lo=None, hi=None):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise ValueError("non-finite postural value: " + key)
    if lo is not None and x < lo or hi is not None and x > hi:
        raise ValueError("postural value outside declared bounds: " + key)
    return float(x)

def clamp(x, lo=0.0, hi=1.0):
    return min(hi, max(lo, x))

def capture(body):
    if body is None or not hasattr(body, "checkpoint"):
        raise ValueError("native UnifiedBody required")
    sha = body.checkpoint()["sha256"]
    native = body.owner.body()
    m, proprio, pose = native["minimum_state"], native["proprioception"], native["pose"]
    feet = {}
    for side in ("L", "R"):
        key = "foot_" + side
        p = proprio[key]
        if p.get("source") != "simulated_encoders_and_forward_kinematics":
            raise ValueError("not a native software encoder")
        position = [number(x, key+" position") for x in p["position"]]
        feet[side] = {
            "contact": bool(p["contact"]),
            "load_N": number(p["load"], key+" load", 0),
            "position_m": position,
            "velocity_m_s": [number(x,key+" velocity") for x in p["velocity"]],
        }
    com = [number(x, "COM") for x in body.owner.physical.state.com_m]
    tail_angle = [number(x,"tail angle") for x in pose["tail_orientation_rad"]]
    sample = {
        "schema": SCHEMA, "source": SOURCE,
        "native_checkpoint_sha256": sha,
        "native_revision": body.revision,
        "posture_phase": str(pose["posture_phase"]),
        "balance": number(m["balance"], "balance", 0, 1),
        "fatigue": number(m["fatigue"], "fatigue", 0, 1),
        "pain": number(m["pain"], "pain", 0, 1),
        "sleep_pressure": number(m["sleep_pressure"], "sleep", 0, 1),
        "muscle_tone": number(m["muscle_tone"], "tone", 0, 1),
        "com_xy_m": com, "feet": feet,
        "tail_angle_rad": tail_angle,
        "native_motor_phase": body.owner.physical.state.phase,
        "has_independent_joint_load_measurements": False,
        "full_multibody_dynamics_validated": False,
    }
    if body.checkpoint()["sha256"] != sha:
        raise ValueError("native state changed during proprioceptive sampling")
    return sample

def preview(sample):
    if not isinstance(sample, dict) or sample.get("schema") != SCHEMA or (
            sample.get("source") != SOURCE):
        raise ValueError("invalid native spinal source")
    feet=sample["feet"]
    if set(feet) != {"L","R"}:
        raise ValueError("two independent foot channels required")
    balance=number(sample["balance"],"balance",0,1)
    fatigue=number(sample["fatigue"],"fatigue",0,1)
    pain=number(sample["pain"],"pain",0,1)
    sleep=number(sample["sleep_pressure"],"sleep pressure",0,1)
    supported=[k for k, v in feet.items() if v["contact"]]
    loads={k: number(feet[k]["load_N"],"load",0) for k in ("L","R")}
    total=sum(loads.values())
    asymmetry=abs(loads["L"]-loads["R"])/total if total>1e-9 else None
    left=feet["L"]["position_m"][0]
    right=feet["R"]["position_m"][0]
    mid=(left+right)/2.0
    spread=max(abs(left-right),.05)
    com_x=number(sample["com_xy_m"][0],"COM x")
    shift=(com_x-mid)/spread
    suggested_tail_yaw=round(-.18*clamp(shift,-1.,1.),6)
    flags={
        "missing_support": len(supported)==0,
        "single_support": len(supported)==1,
        "weak_balance": balance < .62,
        "loaded_or_sleepy": max(pain,fatigue,sleep)>.58,
        "high_asymmetry_with_low_margin":
            asymmetry is not None and asymmetry>.8 and balance <.85,
        "lateral_com_outside_foot_span": abs(shift)>.8,
        "contact_load_unknown": total<=1e-9,
    }
    # Lower confidence never increases activity. A spinal proxy cannot
    # command new movements or override the native plant's protective action.
    downgrade=any(v for k,v in flags.items() if k!="contact_load_unknown")
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "native_checkpoint_sha256": sample["native_checkpoint_sha256"],
        "native_revision": sample["native_revision"],
        "supported_feet": supported,
        "support_count": len(supported),
        "foot_load_asymmetry_if_available": None if asymmetry is None
                                            else round(asymmetry,6),
        "mediolateral_com_offset_fraction": round(shift,6),
        "tail_counterbalance_yaw_not_actuated_rad": suggested_tail_yaw,
        "reflex_flags": flags,
        "recommendation": "observe" if downgrade else "walk",
        "native_protection_remains_authoritative": True,
        "native_motor_command_executed": False,
        "physical_actuation": False,
        "source_level": "B_uncalibrated_software_body",
    }
