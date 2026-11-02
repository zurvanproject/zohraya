"""Evidence-gated micro-practice on the PINNED 78 kg Tadash v03 mechanics.

Every attempt is a fresh native one-step trial, never an actuator continuation.
A finite rule repeats successes, promotes difficulty after two successes, and
simplifies an explicit failure. This is curriculum scaffolding, NOT motor learning.
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

SCHEMA = "tadash-micro-practice/1"
# Metres; the 0.06 m level is the current original native command length.
LEVELS = (0.0075, 0.015, 0.03, 0.06)
START_LEVEL = 1
MAX_ATTEMPTS = 4
CHILD = """import json, sys
from examples.nasuraya_research.articulated.canon_trial import CANDIDATE
from examples.nasuraya_research.articulated.stepping import walk_trial
r, _ = walk_trial(label="micro-practice", steps=1,
                  stride=float(sys.argv[1]), model_dir=CANDIDATE,
                  geometry_support=True, checkpoint_v03=True,
                  retain_checkpoint=True, capture=False)
print(json.dumps(r, ensure_ascii=False, allow_nan=False))
"""


def assess(result, stride):
    """Return 'met' or an explicit native 'not_met'; reject unknown evidence."""
    if not isinstance(result, dict):
        raise ValueError("Native result must be a JSON object")
    if type(result.get("requested_steps")) is not int or result["requested_steps"] != 1:
        raise ValueError("Wrong requested step count")
    if not math.isclose(evidence.finite(result.get("stride_m")), stride, abs_tol=1e-12):
        raise ValueError("Native stride differs from frozen intent")
    passed = result.get("walk_pass")
    failure = result.get("failure")
    if passed is False:
        if not isinstance(failure, str) or not failure:
            raise ValueError("Failure without a native failure reason is unknown")
        if type(result.get("accepted_steps")) is not int or not 0 <= result["accepted_steps"] <= 1:
            raise ValueError("Invalid accepted steps in failed result")
        return "not_met"
    if passed is not True or failure is not None:
        raise ValueError("Ambiguous native outcome")
    if type(result.get("accepted_steps")) is not int or result["accepted_steps"] != 1:
        raise ValueError("No accepted native step")
    if result.get("nonfoot_ground_contacts") != []:
        raise ValueError("Unsafe non-foot contact")
    for key in ("max_tilt_deg", "max_joint_limit_excess_rad", "final_max_generalized_speed",
                "max_motor_torque_fraction", "end_time", "start_time"):
        evidence.finite(result.get(key))
    if not (0 <= result["max_tilt_deg"] <= evidence.LIMITS["max_tilt_deg"]
            and 0 <= result["max_joint_limit_excess_rad"] <= evidence.LIMITS["max_joint_limit_excess_rad"]
            and 0 <= result["final_max_generalized_speed"] < evidence.LIMITS["final_max_generalized_speed_exclusive"]
            and 0 <= result["max_motor_torque_fraction"] <= 1.000001
            and result["end_time"] > result["start_time"]):
        raise ValueError("Native safety/settled guard exceeded")
    cp = result.get("checkpoint")
    if not isinstance(cp, dict) or set(cp) != {"value", "sha256"}:
        raise ValueError("Settled checkpoint absent")
    if evidence.digest(cp["value"]) != cp["sha256"]:
        raise ValueError("Native checkpoint digest mismatch")
    if cp["value"].get("schema") != "nasuraya-articulated-checkpoint/2":
        raise ValueError("Wrong native checkpoint schema")
    if result.get("final_qpos") != cp["value"].get("qpos") or result.get("final_qvel") != cp["value"].get("qvel"):
        raise ValueError("Checkpoint pose boundary mismatch")
    return "met"


def next_level(level, history):
    """Finite, deterministic instructional rule; never claims a learned policy."""
    if type(level) is not int or not 0 <= level < len(LEVELS):
        raise ValueError("Unknown level")
    if not history or history[-1].get("level") != level:
        raise ValueError("History does not match current level")
    outcome = history[-1].get("outcome")
    if outcome == "not_met":
        return (level - 1, "simplify_after_failure") if level else (None, "stop_at_smallest")
    if outcome != "met":
        raise ValueError("Unknown outcome cannot progress")
    streak = 0
    for record in reversed(history):
        if record["level"] != level or record["outcome"] != "met":
            break
        streak += 1
    if streak >= 2:
        return (level + 1, "promote_after_two") if level + 1 < len(LEVELS) else (None, "max_level_passed")
    return level, "repeat_same_easy_action"


def persist(path, value, *, replace=False):
    evidence.write(path, value, replace=replace)


def run(source, output, *, max_attempts=MAX_ATTEMPTS, timeout=480):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Practice output cannot be inside immutable motion source")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 8:
        raise ValueError("1-8 attempts only")
    if type(timeout) is not int or not 30 <= timeout <= 600:
        raise ValueError("Timeout must be 30-600 seconds")
    identity = evidence.source_identity(source)
    script_hash = evidence.sha(Path(__file__))
    output.mkdir(parents=True, exist_ok=False)
    plan = {"schema": SCHEMA, "source": identity, "script_sha256": script_hash,
            "levels_m": LEVELS, "start_level": START_LEVEL,
            "max_attempts": max_attempts, "timeout_seconds": timeout,
            "contract": "fresh independent v03 trials, 2 successes before advancing; failure halves stride",
            "no_learned_policy": True, "no_human_physiology_claim": True}
    persist(output / "plan.json", plan)
    plan_hash = evidence.sha(output / "plan.json")
    persist(output / "status.json", {"status": "running", "utc": datetime.now(timezone.utc).isoformat()})
    history = []
    level = START_LEVEL
    reason = "start_small"
    try:
        for i in range(max_attempts):
            if evidence.source_identity(source) != identity or evidence.sha(Path(__file__)) != script_hash:
                raise ValueError("Pinned source or curriculum code drifted")
            stride = LEVELS[level]
            prefix = f"trial-{i + 1:02d}"
            intent = {"schema": "tadash-micro-intent/1", "trial": i + 1, "level": level,
                      "stride_m": stride, "reason": reason, "plan_sha256": plan_hash}
            persist(output / f"{prefix}-intent.json", intent)  # frozen BEFORE native run
            cmd = [sys.executable, "-c", CHILD, str(stride)]
            try:
                proc = subprocess.run(cmd, cwd=source, env=evidence.clean_env(),
                                      capture_output=True, text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"{prefix} timed out; no replay or next action") from exc
            (output / f"{prefix}.stdout.log").write_text(proc.stdout)
            (output / f"{prefix}.stderr.log").write_text(proc.stderr)
            if proc.returncode:
                raise RuntimeError(f"{prefix} native process exited {proc.returncode}; no automatic retry")
            result = json.loads(proc.stdout, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite native JSON")))
            persist(output / f"{prefix}-native.json", result)
            outcome = assess(result, stride)
            receipt = {"schema": "tadash-micro-receipt/1", "intent_sha256": evidence.sha(output / f"{prefix}-intent.json"),
                       "native_sha256": evidence.sha(output / f"{prefix}-native.json"),
                       "trial": i + 1, "level": level, "stride_m": stride, "outcome": outcome,
                       "native_failure": result["failure"],
                       "accepted_steps": result["accepted_steps"],
                       "max_tilt_deg": result["max_tilt_deg"],
                       "max_motor_torque_fraction": result["max_motor_torque_fraction"],
                       "simulated_seconds": result["simulated_seconds"]}
            persist(output / f"{prefix}-receipt.json", receipt)
            history.append(receipt)
            target, reason = next_level(level, history)
            if target is None:
                break
            level = target
        if evidence.source_identity(source) != identity or evidence.sha(output / "plan.json") != plan_hash:
            raise ValueError("Source or frozen plan changed after execution")
        summary = {"schema": SCHEMA, "status": "complete", "source": identity,
                   "plan_sha256": plan_hash, "trials": len(history),
                   "observed_outcomes": [h["outcome"] for h in history],
                   "observed_strides_m": [h["stride_m"] for h in history],
                   "receipts": [evidence.sha(output / f"trial-{i + 1:02d}-receipt.json") for i in range(len(history))],
                   "next_level": level if target is not None else None,
                   "last_rule": reason,
                   "learned_improvement_established": False,
                   "generalization_established": False,
                   "source_model_unchanged": True}
        persist(output / "summary.json", summary)
        persist(output / "status.json", {"status": "complete", "summary_sha256": evidence.sha(output / "summary.json")}, replace=True)
        return summary
    except BaseException as error:
        persist(output / "status.json", {"status": "failed_or_unknown", "error_type": type(error).__name__,
                                         "completed_receipts": len(history), "no_automatic_retry": True}, replace=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    print(json.dumps(run(args.motion_source, args.output, max_attempts=args.max_attempts,
                         timeout=args.timeout), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
