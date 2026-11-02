"""Pre-registered single-parameter motor calibration on the REAL pinned Tadash v03.

This tests a narrow observable form of motor learning: a controller command gain
is updated from native sensorimotor errors, frozen, and evaluated against an
unchanged controller on disjoint targets and contact friction. It is NOT
a neural policy, conscious experience, or evidence for humanoid generalization.
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
from experiments import tadash_weight_shift as motor

SCHEMA = "tadash-motor-learning/1"
TRAIN_TARGETS = (0.0, 0.002, -0.002)
TRAIN_FRICTION = 0.6
HOLDOUT_TARGETS = (0.001, -0.001, 0.003, -0.003)
HOLDOUT_FRICTIONS = (0.6, 0.5)
MIN_IMPROVEMENT = 0.20
MIN_WIN_CASES = 6
MAX_COMMAND_M = 0.004
MAX_TRIALS = 19
GAIN_LIMITS = (0.8, 1.3)


def learn_gain(positive, negative, zero):
    """Fit y = gain * x + baseline from ONLY ±2mm observations."""
    observed = []
    for target, record in ((0.002, positive), (-0.002, negative)):
        if not isinstance(record, dict) or not math.isfinite(evidence.finite(record.get("held_com_y_delta_m"))):
            raise ValueError("Missing finite training outcome")
        observed.append((target, record["held_com_y_delta_m"] - evidence.finite(zero["held_com_y_delta_m"])))
    gain = sum(x * y for x, y in observed) / sum(x * x for x, _ in observed)
    if not 0.7 <= gain <= 1.05:
        raise ValueError("Learning gain not physically plausible in frozen contract")
    correction = min(GAIN_LIMITS[1], max(GAIN_LIMITS[0], 1.0 / gain))
    if abs(correction - 1.0) < 1e-5:
        raise ValueError("No nontrivial learning update")
    return {"schema": "tadash-frozen-gain/1",
            "learned_plant_gain": gain, "command_gain": correction,
            "training_targets_m": TRAIN_TARGETS, "training_friction": TRAIN_FRICTION,
            "training_baseline_y_m": zero["held_com_y_delta_m"],
            "fitting_rule": "bounded_inverse_of_least_squares_signed_plant_gain",
            "parameter_updated_from_native_feedback": True,
            "gradient_or_deep_rl_training": False}


def eval_metrics(records):
    if len(records) != len(HOLDOUT_TARGETS) * len(HOLDOUT_FRICTIONS):
        raise ValueError("Incomplete heldout comparison")
    errors_base, errors_learned = [], []
    improvements_per_friction = {str(fr): [] for fr in HOLDOUT_FRICTIONS}
    wins = 0
    for row in records:
        target = evidence.finite(row["target_m"])
        b = abs(evidence.finite(row["baseline_observed_m"]) - target)
        l = abs(evidence.finite(row["learned_observed_m"]) - target)
        errors_base.append(b); errors_learned.append(l)
        improvements_per_friction[str(row["friction"])].append((b, l))
        wins += int(l < b - 1e-10)
    base_mae = sum(errors_base) / len(errors_base)
    learned_mae = sum(errors_learned) / len(errors_learned)
    if base_mae < 1e-7:
        raise ValueError("Baseline error too small to demonstrate improved tracking")
    improvement = (base_mae - learned_mae) / base_mae
    conditions = {"gain_changed": True, "holdout_no_retraining": True,
                  "relative_mae_at_least_20_percent": improvement >= MIN_IMPROVEMENT,
                  "win_at_least_six_of_eight": wins >= MIN_WIN_CASES,
                  "improvement_under_both_friction_conditions": all(
                      sum(l for b, l in pairs) < sum(b for b, l in pairs)
                      for pairs in improvements_per_friction.values())}
    return {"baseline_mae_m": base_mae, "learned_mae_m": learned_mae,
            "relative_improvement": improvement, "heldout_wins": wins, "heldout_count": len(records),
            "per_friction_mae_m": {key: {"baseline": sum(b for b, l in pairs) / len(pairs),
                                        "learned": sum(l for b, l in pairs) / len(pairs)}
                                   for key, pairs in improvements_per_friction.items()},
            "frozen_acceptance": conditions,
            "criterion_met": all(conditions.values())}


def run(source, output, timeout=240):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.is_relative_to(source):
        raise ValueError("Output must be outside pinned source")
    if type(timeout) is not int or not 30 <= timeout <= 600:
        raise ValueError("Invalid timeout")
    identity = evidence.source_identity(source)
    scriptsha = evidence.sha(Path(__file__))
    native_sha = evidence.sha(Path(motor.__file__))
    output.mkdir(parents=True, exist_ok=False)
    plan = {"schema": SCHEMA, "source": identity, "script_sha256": scriptsha,
            "native_wrapper_sha256": native_sha,
            "training": {"desired_m": TRAIN_TARGETS, "friction": TRAIN_FRICTION},
            "holdout": {"desired_m": HOLDOUT_TARGETS, "frictions": HOLDOUT_FRICTIONS},
            "original_unchanged_controller": "ContactController v03, both feet down",
            "model": "single_scalar_inverse_gain_fit_from_measured_COM_feedback",
            "baseline": "unchanged command_gain_1.0",
            "evaluation": "same target/fresh independent episode for baseline vs learned, no fit on holdout",
            "min_relative_mae_improvement": MIN_IMPROVEMENT,
            "min_case_wins": MIN_WIN_CASES,
            "max_native_trials": MAX_TRIALS, "timeout_per_trial_s": timeout,
            "safety": "reject unknown outcomes, no retry, pinned source, native guards, no root actuator",
            "limitations": "deterministic rigid-body simulation, narrow parameter learning only; no human claims"}
    evidence.write(output / "plan.json", plan)
    plan_sha = evidence.sha(output / "plan.json")
    evidence.write(output / "status.json", {"status": "running",
                                           "utc": datetime.now(timezone.utc).isoformat()})
    trials = []
    try:
        def trial(phase, target, applied, friction, mode):
            if len(trials) >= MAX_TRIALS:
                raise ValueError("Exceeded pre-registered budget")
            if (evidence.source_identity(source) != identity or
                    evidence.sha(Path(__file__)) != scriptsha or
                    evidence.sha(Path(motor.__file__)) != native_sha or
                    evidence.sha(output / "plan.json") != plan_sha):
                raise ValueError("Source or frozen contract changed")
            for val in (target, applied, friction):
                evidence.finite(val)
            if abs(applied) > MAX_COMMAND_M or not 0.45 <= friction <= 0.7:
                raise ValueError("Actuator target or friction out of bounds")
            tag = f"trial-{len(trials)+1:02d}"
            intent = {"schema": "tadash-motor-intention/1", "phase": phase,
                      "desired_target_m": target, "applied_command_m": applied,
                      "friction": friction, "mode": mode, "plan_sha256": plan_sha}
            evidence.write(output / (tag + "-intent.json"), intent)
            try:
                proc = subprocess.run([sys.executable, "-c", motor.NATIVE, str(applied), str(friction)],
                                      cwd=source, env=evidence.clean_env(), capture_output=True,
                                      text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Native evaluation timed out; no automatic retry") from exc
            (output / (tag + ".stdout.log")).write_text(proc.stdout)
            (output / (tag + ".stderr.log")).write_text(proc.stderr)
            if proc.returncode:
                raise RuntimeError(f"Native run exited {proc.returncode}; stop, inspect evidence")
            native = json.loads(proc.stdout, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite native JSON")))
            evidence.write(output / (tag + "-native.json"), native)
            motor.validate(native, applied)
            if native.get("friction") != friction:
                raise ValueError("Native friction mismatch")
            row = {"id": tag, "phase": phase, "mode": mode, "desired_target_m": target,
                   "applied_command_m": applied, "friction": friction,
                   "observed_com_y_m": native["held_com_y_delta_m"],
                   "return_y_m": native["returned_com_y_delta_m"],
                   "max_tilt_deg": native["peak_tilt_deg"],
                   "peak_motor_fraction": native["peak_motor_fraction"],
                   "intent_sha256": evidence.sha(output / (tag + "-intent.json")),
                   "native_sha256": evidence.sha(output / (tag + "-native.json"))}
            evidence.write(output / (tag + "-receipt.json"), row)
            trials.append(row)
            return native
        zero = trial("train", 0., 0., TRAIN_FRICTION, "train_zero")
        p = trial("train", 0.002, 0.002, TRAIN_FRICTION, "train_positive")
        n = trial("train", -0.002, -0.002, TRAIN_FRICTION, "train_negative")
        trained = learn_gain(p, n, zero)
        trained.update({"plan_sha256": plan_sha, "training_receipt_sha256": [
            evidence.sha(output / (row["id"] + "-receipt.json")) for row in trials]})
        evidence.write(output / "frozen-model.json", trained)
        frozen_sha = evidence.sha(output / "frozen-model.json")
        comparisons = []
        for friction in HOLDOUT_FRICTIONS:
            for target in HOLDOUT_TARGETS:
                if evidence.sha(output / "frozen-model.json") != frozen_sha:
                    raise ValueError("Frozen learned model changed during holdout")
                applied = target * trained["command_gain"]
                # Pair-order alternation checks against only always-running control first.
                if len(comparisons) % 2 == 0:
                    b = trial("holdout", target, target, friction, "unchanged_baseline")
                    l = trial("holdout", target, applied, friction, "frozen_learned")
                else:
                    l = trial("holdout", target, applied, friction, "frozen_learned")
                    b = trial("holdout", target, target, friction, "unchanged_baseline")
                comparisons.append({"target_m": target, "friction": friction,
                                    "baseline_observed_m": b["held_com_y_delta_m"],
                                    "learned_observed_m": l["held_com_y_delta_m"],
                                    "baseline_return_m": b["returned_com_y_delta_m"],
                                    "learned_return_m": l["returned_com_y_delta_m"],
                                    "baseline_command_m": target,
                                    "learned_command_m": applied})
        if len(trials) != MAX_TRIALS or evidence.sha(output / "frozen-model.json") != frozen_sha:
            raise ValueError("Incomplete trials or modified learned model")
        result = eval_metrics(comparisons)
        summary = {"schema": SCHEMA, "status": "complete", "source": identity,
                   "plan_sha256": plan_sha, "frozen_model_sha256": frozen_sha,
                   "training_observations": [{"target": row["desired_target_m"], "measured": row["observed_com_y_m"]}
                                             for row in trials[:len(TRAIN_TARGETS)]],
                   "learned_plant_gain": trained["learned_plant_gain"],
                   "learned_command_gain": trained["command_gain"],
                   "native_trials": len(trials), "holdout_pairs": comparisons,
                   "metrics": result,
                   "interpretation": ("bounded_within_simulator_sensorimotor_calibration_demonstrated"
                                      if result["criterion_met"] else "motor_learning_effect_NOT_demonstrated"),
                   "not_proven": ["subjective experience", "brain-like adaptation",
                                  "long-term retention", "real-world robot transfer", "general humanoid learning"],
                   "source_unchanged": evidence.source_identity(source) == identity}
        evidence.write(output / "summary.json", summary)
        evidence.write(output / "status.json", {"status": "complete",
                                               "summary_sha256": evidence.sha(output / "summary.json")},
                       replace=True)
        return summary
    except BaseException as exc:
        evidence.write(output / "status.json", {"status": "failed_or_unknown",
                                               "error_type": type(exc).__name__, "completed_trials": len(trials),
                                               "no_automatic_retry": True}, replace=True)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--motion-source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=240)
    a = ap.parse_args()
    print(json.dumps(run(a.motion_source, a.output, a.timeout),
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
