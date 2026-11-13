"""Native-body calibration and untouched-seed temporal noise benchmark.

Development and held-out splits share simulator/trajectory families and differ
in seeded noise draws. Therefore the holdout is an internal noise replay test,
NOT independent bodily physics or real-world sensory validation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter

from experiments.tadash_embodied_origin import (
    MODEL, _validated, capture_native, interpret, source_identity,
)
from experiments.tadash_temporal_proprioception import (
    LARGE_SMOOTH_EXCURSION, LARGE_SMOOTH_MAX_JAGGEDNESS,
    LARGE_SMOOTH_MIN_SIGN_FRAMES, MAX_JAGGEDNESS,
    PERSISTENCE_MIN_CHANNELS, PERSISTENCE_MIN_FRAMES,
    PERSISTENCE_THRESHOLD, PROPRIO_KEYS, WEIGHTS, classify_temporal,
)

DEV_SEED = 131113
HOLDOUT_SEED = 951113
GROUP_SIZES = {
    "high_noise_no_stimulus": 100,
    "high_noise_known_command": 80,
    "clean_no_command": 30,
    "clean_known_command": 30,
    "clean_external_change": 30,
    "clean_command_plus_external": 30,
    "novel_coherent_unknown": 80,
}
ABSTENTIONS = frozenset(("unverified", "uncertain_noise_or_weak_signal"))
STRONG_EVENT_STATES = frozenset(("unexplained_change", "command_outcome_mismatch"))


def altered(trace, rng, amplitude=0.1, coherent=False):
    result = copy.deepcopy(trace)
    for i, frame in enumerate(result["frames"]):
        for key in PROPRIO_KEYS:
            if coherent:
                # Unseen temporally coherent input; the interpreter is NOT told
                # whether it is a physical disturbance, modeling error or artifact.
                direction = 1. if key in ("pelvis_yaw_rad", "com_y_m") else -.6
                normalized = direction * amplitude * (i + 1) / len(result["frames"])
            else:
                normalized = rng.gauss(0., amplitude)
                if rng.random() < 0.04:
                    normalized += rng.choice((-1., 1.)) * amplitude * 2.5
            frame[key] += normalized / WEIGHTS[key]
    # Preserving the original quality and model source deliberately hides
    # sensor corruption from the decoder. NOT an authenticated measurement.
    return result


def make_cases(model, mujoco, np, identity, rng):
    rest = capture_native(model, mujoco, np, identity)
    action = capture_native(model, mujoco, np, identity, command_nm=8.)
    disturbance = capture_native(model, mujoco, np, identity, external_torque_nm=35.)
    combined = capture_native(model, mujoco, np, identity,
                              command_nm=8., external_torque_nm=35.)
    assert all(_validated(t, identity["sha256"])
               for t in (rest, action, disturbance, combined))
    cases = []
    for group, count in GROUP_SIZES.items():
        for i in range(count):
            if group == "high_noise_no_stimulus":
                prediction, measured, command = rest, altered(
                    rest, rng, .05 + rng.random()*.13), 0.
            elif group == "high_noise_known_command":
                prediction, measured, command = action, altered(
                    action, rng, .05 + rng.random()*.13), 8.
            elif group == "clean_no_command":
                prediction, measured, command = rest, copy.deepcopy(rest), 0.
            elif group == "clean_known_command":
                prediction, measured, command = action, copy.deepcopy(action), 8.
            elif group == "clean_external_change":
                prediction, measured, command = rest, copy.deepcopy(disturbance), 0.
            elif group == "clean_command_plus_external":
                prediction, measured, command = action, copy.deepcopy(combined), 8.
            else:
                prediction, measured, command = rest, altered(
                    rest, rng, .09 + rng.random()*.25, coherent=True), 0.
            cases.append({
                "id": group + ":" + str(i).zfill(3),
                "group": group, "reference": rest,
                "prediction": prediction, "actual": measured,
                "intent": command,
            })
    rng.shuffle(cases)
    return cases


def score(groups):
    n = {name: len(states) for name, states in groups.items()}
    def rate(group, positive):
        return sum(s in positive for s in groups[group]) / n[group]
    observed = {
        "high_noise_absence_false_event_rate": rate(
            "high_noise_no_stimulus", STRONG_EVENT_STATES),
        "high_noise_absence_abstention_rate": rate(
            "high_noise_no_stimulus", ABSTENTIONS),
        "high_noise_command_false_consistency_rate": rate(
            "high_noise_known_command", {"command_consistent"}),
        "clean_idle_correct": rate("clean_no_command", {"no_detectable_change"}),
        "clean_command_correct": rate("clean_known_command", {"command_consistent"}),
        "clean_external_detected": rate("clean_external_change", {"unexplained_change"}),
        "clean_command_mismatch_detected": rate(
            "clean_command_plus_external", {"command_outcome_mismatch"}),
        "novel_unknown_named_specific_cause_rate": 0.0,
        "novel_unknown_unexplained_or_abstain_rate": rate(
            "novel_coherent_unknown", STRONG_EVENT_STATES | ABSTENTIONS),
    }
    # No specific stimulus-type label exists, so unknown-specific type accuracy
    # is not measurable here. The zero above is structural, not learned skill.
    goals = {
        "high_noise_absence_false_event_rate": observed[
            "high_noise_absence_false_event_rate"] <= .05,
        "high_noise_command_false_consistency_rate": observed[
            "high_noise_command_false_consistency_rate"] <= .05,
        "clean_idle_correct": observed["clean_idle_correct"] == 1.,
        "clean_command_correct": observed["clean_command_correct"] == 1.,
        "clean_external_detected": observed["clean_external_detected"] >= .90,
        "clean_command_mismatch_detected": observed[
            "clean_command_mismatch_detected"] >= .90,
        "novel_unknown_unexplained_or_abstain_rate": observed[
            "novel_unknown_unexplained_or_abstain_rate"] >= .90,
    }
    return observed, goals


def run_benchmark(split="dev"):
    if split not in ("dev", "holdout"):
        raise ValueError("split_must_be_dev_or_holdout")
    import mujoco
    import numpy as np

    identity = source_identity(MODEL)
    model = mujoco.MjModel.from_xml_path(str(MODEL))
    if model.nu != 55 or model.nv != 61 or abs(float(model.body_mass.sum())-78.) > 1e-5:
        raise ValueError("wrong_physical_body")
    rng = random.Random(DEV_SEED if split == "dev" else HOLDOUT_SEED)
    cases = make_cases(model, mujoco, np, identity, rng)
    observations, naive, predictions = {}, {}, []
    for case in cases:
        group = case["group"]
        previous = interpret(case["reference"], case["prediction"],
                             case["actual"], case["intent"])
        outcome = classify_temporal(case["reference"], case["prediction"],
                                    case["actual"], case["intent"])
        observations.setdefault(group, []).append(outcome["state"])
        naive.setdefault(group, []).append(previous["state"])
        predictions.append({"id": case["id"], "prediction": outcome["state"]})
    metrics, targets = score(observations)
    naive_metrics, _ = score(naive)
    predicted_bytes = json.dumps(predictions, ensure_ascii=False,
                                 separators=(",", ":"), sort_keys=True).encode()
    return {
        "pass": all(targets.values()),
        "split": split,
        "seed": DEV_SEED if split == "dev" else HOLDOUT_SEED,
        "pinned_model_sha256": identity["sha256"],
        "native_mu_joco": mujoco.__version__,
        "thresholds_frozen_in_code": {
            "persistence_value": PERSISTENCE_THRESHOLD,
            "min_frames": PERSISTENCE_MIN_FRAMES,
            "min_channels": PERSISTENCE_MIN_CHANNELS,
            "max_jaggedness": MAX_JAGGEDNESS,
            "large_smooth_excursion": LARGE_SMOOTH_EXCURSION,
            "large_smooth_max_jaggedness": LARGE_SMOOTH_MAX_JAGGEDNESS,
            "large_smooth_min_sign_frames": LARGE_SMOOTH_MIN_SIGN_FRAMES,
        },
        "episode_counts": GROUP_SIZES,
        "total_episode_replays": len(cases),
        "prediction_before_truth_digest_sha256": hashlib.sha256(predicted_bytes).hexdigest(),
        "metrics": metrics,
        "naive_v01_comparison": naive_metrics,
        "group_classifications": {
            g: dict(sorted(Counter(states).items())) for g, states in observations.items()
        },
        "promotion_gates": targets,
        "limitations": [
            "Repeated seeded sensor replays of four native trajectories; not independent physics episodes",
            "Native physical torque provides known clean change; unknown novel trace is synthetic smooth corruption",
            "Noise unflagged to decoder; no authenticated physical sensors",
            "False-stimulus rate only in this synthetic white-noise family, not shift robustness",
            "No verified transfer to PR198 shared runtime or PR205 hourly worker",
            "No evidence of subjective self-awareness or biological physiology",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        report = run_benchmark(args.split)
    except Exception as exc:
        report = {"pass": False, "error": repr(exc), "split": args.split}
    rendered = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    print(rendered)
    if args.output:
        from pathlib import Path
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
