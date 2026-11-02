"""Bounded synthetic pilot; output directory is an exclusive, no-retry claim.

Run from a complete repository checkout. All native work uses a disposable
runtime copy. A successful run is not an installed upstream framework.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from statistics import fmean
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.tadash_four_tracks.core import (METRICS, SOURCES, digest, encode,
    hindsight_items, motion_readiness, rehearsal_gate, review_pair, snapshot,
    summarize_trials)

PLAN = {"schema": "tadash-four-track-plan/1", "contexts": ["baseline", "post_walk"],
    "horizons_s": [.1, .5, 1.0], "arms": ["slow_breath", "observe"],
    "tick_s": .1, "min_arousal_effect": .005, "guard_tolerance": .01,
    "candidate": "action-conditioned mean delta, not upstream Dreamer",
    "train_context": "baseline", "evaluation_context": "post_walk",
    "independent_samples": False, "max_native_intervention_cycles": 64,
    "paid_api_calls": 0, "model_training": "small deterministic delta estimator only"}


def write(path: Path, value: dict | list) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        f.write(encode(value) + "\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def append(path: Path, value: dict) -> None:
    with path.open("a") as f:
        f.write(encode(value) + "\n"); f.flush(); os.fsync(f.fileno())


def file_hashes(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()
            and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def stamp(seconds: float) -> str:
    return (datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(seconds=seconds)).isoformat()


def worker(runtime: Path, output: Path) -> None:
    if os.environ.get("TADASH_FOUR_TRACK_SANDBOX") != str(runtime):
        raise RuntimeError("use the disposable runtime launcher")
    sys.path.insert(0, str(runtime))
    from synthetic_fixture import prepare_defaults, synthetic_body
    from symbolic_action_v1 import NativeBodyPort
    prepare_defaults()
    trials, transitions, reviews, exported = [], [], [], []
    train_ids, eval_ids, predictions, targets, persistence = [], [], [], [], []
    delta_model = None
    max_errors = {"energy_error_J": 0., "water_error_L": 0., "neural_clock_error_s": 0.}
    warmup_native_cycles = 0
    for context in PLAN["contexts"]:
        if context == "post_walk":
            buckets = defaultdict(list)
            for row in transitions:
                buckets[row["requested"]].append(
                    [row["after"][k]-row["before"][k] for k in METRICS])
            delta_model = {action: [fmean(v[i] for v in values) for i in range(len(METRICS))]
                           for action, values in sorted(buckets.items())}
            write(output / "frozen-delta-model.json", {"model": delta_model,
                "training_ids": train_ids, "sha256": digest(delta_model),
                "frozen_before_evaluation": True})
        for horizon in PLAN["horizons_s"]:
            pair = []
            initial_hash = None
            for action in PLAN["arms"]:
                body = synthetic_body()
                # Each synthetic_body includes one native 7s initialization cycle.
                warmup_native_cycles += 1
                trial_id = f"{context}-{round(horizon*10)}-{action}"
                if context == "post_walk":
                    for j in range(3):
                        body.cycle(event_id=f"shared-prep{j}", at_utc=stamp(8+j*.1),
                            duration_s=.1, requested="walk", external={},
                            expected_revision=body.revision)
                        warmup_native_cycles += 1
                port = NativeBodyPort(body)
                before = snapshot(port.snapshot())
                # Same preparatory events in separate synthetic bodies.
                cp = body.checkpoint()
                initial = digest(cp)
                if initial_hash is None: initial_hash = initial
                if initial != initial_hash:
                    raise AssertionError("paired full initial checkpoints differ")
                actual = []
                for step in range(round(horizon*10)):
                    event = f"{trial_id}-step{step}"
                    pre = snapshot(port.snapshot())
                    if delta_model is not None:
                        guess = [min(1., max(0., pre[k]+delta_model[action][i]))
                                 for i, k in enumerate(METRICS)]
                        append(output / "pre-action-predictions.jsonl", {
                            "event_id": event, "prediction": guess,
                            "persistence": [pre[k] for k in METRICS],
                            "frozen_model_sha256": digest(delta_model)})
                    result = body.cycle(event_id=event, at_utc=stamp(9+step*.1),
                        duration_s=.1, requested=action, external={},
                        expected_revision=body.revision)
                    after = snapshot(port.snapshot())
                    selected = result["owner"]["selected_action"]
                    audit = result["whole_body_audit"]
                    for key, limit in (("energy_error_J", 5e-5),
                                       ("water_error_L", 1e-8),
                                       ("neural_clock_error_s", 1e-7)):
                        error = abs(float(audit[key]))
                        if not error <= limit:
                            raise AssertionError(f"native conservation failed: {key}")
                        max_errors[key] = max(max_errors[key], error)
                    row = {"event_id": event, "episode_id": trial_id,
                        "context": context, "synthetic": True,
                        "requested": action, "actual": selected,
                        "before": pre, "after": after, "native_audit": audit}
                    append(output / "native-transitions.jsonl", row)
                    transitions.append(row); actual.append(selected)
                    if delta_model is None:
                        train_ids.append(event)
                    else:
                        eval_ids.append(event); predictions.append(guess)
                        targets.append([after[k] for k in METRICS])
                        persistence.append([pre[k] for k in METRICS])
                trial = {"id": trial_id, "synthetic": True, "status": "completed",
                    "duration_s": horizon, "requested": action, "actual_actions": actual,
                    "initial_checkpoint_sha256": initial, "before": before,
                    "after": snapshot(port.snapshot())}
                pair.append(trial); trials.append(trial)
            review = review_pair(*pair, min_effect=PLAN["min_arousal_effect"],
                                 guard_tolerance=PLAN["guard_tolerance"])
            reviews.append(review)
            exported.extend(hindsight_items(*pair, review)["items"])
    gate = rehearsal_gate(predictions, targets, persistence, train_ids, eval_ids)
    write(output / "native-trials.json", trials)
    write(output / "outcome-reviews.json", reviews)
    write(output / "hindsight-retain.json", {"items": exported})
    write(output / "world-model-gate.json", gate)
    report = {"schema": "tadash-four-track-native/1", **summarize_trials(trials),
        "initialization_native_cycles": warmup_native_cycles,
        "paired_comparisons": len(reviews),
        "verdicts": {v: sum(r["verdict"] == v for r in reviews)
                     for v in ("met", "not_met", "inconclusive")},
        "hindsight_items_prepared": len(exported), "hindsight_service_called": False,
        "world_model": gate, "maximum_conservation_errors": max_errors,
        "source_projects": SOURCES, "paid_api_calls": 0,
        "canonical_state_modified": False, "empirical_physiology": False}
    if report["native_cycles"] != PLAN["max_native_intervention_cycles"]:
        raise AssertionError("unexpected number of intervention cycles")
    write(output / "native-summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-runtime", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker_runtime:
        worker(args.worker_runtime.resolve(), output)
        return 0
    # This is an at-most-once claim on this output path, not a distributed lock.
    output.mkdir(parents=True, exist_ok=False)
    write(output / "status.json", {"status": "running", "automatic_retry": False})
    write(output / "plan.json", {**PLAN, "plan_sha256": digest(PLAN)})
    write(output / "mjlab-readiness.json", motion_readiness(REPO))
    runtime = REPO / "runtimes/tadash_body"
    if not (runtime / "synthetic_fixture.py").exists():
        write(output / "status.json", {"status": "blocked", "reason": "complete_native_checkout_missing"})
        return 2
    before = file_hashes(runtime)
    write(output / "native-source-hashes.json", before)
    try:
        with tempfile.TemporaryDirectory(prefix="tadash-four-") as tmp:
            target = Path(tmp) / "runtime"
            shutil.copytree(runtime, target, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.sqlite", "*.sqlite-*", "*.db", "*.db-*"))
            env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp,
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "TADASH_FOUR_TRACK_SANDBOX": str(target)}
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                "--worker-runtime", str(target), "--output", str(output)],
                cwd=tmp, env=env, capture_output=True, text=True, timeout=180)
            (output / "native.stdout.log").write_text(run.stdout)
            (output / "native.stderr.log").write_text(run.stderr)
            sys.stdout.write(run.stdout); sys.stderr.write(run.stderr)
            if run.returncode:
                raise RuntimeError(f"native worker exit {run.returncode}")
        if before != file_hashes(runtime):
            raise AssertionError("canonical runtime changed")
        write(output / "status.json", {"status": "completed", "canonical_runtime_unchanged": True,
            "upstream_frameworks_installed": False, "live_deployment": False})
        manifest = file_hashes(output)
        write(output / "manifest.json", manifest)
        return 0
    except BaseException as exc:
        write(output / "status.json", {"status": "failed_or_unknown", "automatic_retry": False,
            "error_type": type(exc).__name__, "message": str(exc),
            "canonical_runtime_unchanged": before == file_hashes(runtime)})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
