"""Predeclared, first-tick affect-to-autonomic ablation on synthetic Tadash only.

This experiment is separate from the historical 64-cycle outcome pilot.
Four cells per context: route enabled/disabled x slow_breath/observe.
Each cell runs two 100ms ticks. Native body code is never edited.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from experiments.tadash_four_tracks.core import (
    METRICS, digest, encode, number, snapshot)
from experiments.tadash_four_tracks.run_probe import file_hashes, write

PLAN = {
    "schema": "tadash-affect-autonomic-ablation-plan/1",
    "contexts": ["baseline", "post_walk"],
    "actions": ["observe", "slow_breath"],
    "routes": ["enabled", "disabled"],
    "route_name": "affect_to_autonomic",
    "ticks_per_cell": 2,
    "tick_s": 0.1,
    "post_walk_prep_ticks": 3,
    "primary_endpoint": "arousal after first 0.1 second tick",
    "secondary_endpoint": "arousal after second tick",
    "interpretation": "within-simulator mechanism only; no clinical efficacy",
    "no_posthoc_exclusions": True,
    "model_weights_changed": False,
    "paid_api_calls": 0,
}
EXPECTED = {(c, a, r) for c in PLAN["contexts"]
            for a in PLAN["actions"] for r in PLAN["routes"]}


def ensure_one_row(row: dict) -> tuple[str, str, str]:
    if not isinstance(row, dict) or set(row) != {
        "context", "requested", "route", "synthetic", "initial_checkpoint_sha256",
        "initial", "readouts", "executed", "native_audits"}:
        raise ValueError("invalid cell structure")
    identity = row["context"], row["requested"], row["route"]
    if identity not in EXPECTED or row["synthetic"] is not True:
        raise ValueError("unknown or non-synthetic ablation cell")
    if not isinstance(row["initial_checkpoint_sha256"], str) or (
        len(row["initial_checkpoint_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in row["initial_checkpoint_sha256"])):
        raise ValueError("invalid starting digest")
    before = snapshot(row["initial"])
    if not isinstance(row["readouts"], list) or len(row["readouts"]) != PLAN["ticks_per_cell"]:
        raise ValueError("missing predeclared tick")
    if not isinstance(row["executed"], list) or len(row["executed"]) != PLAN["ticks_per_cell"]:
        raise ValueError("missing action receipt")
    if not isinstance(row["native_audits"], list) or len(row["native_audits"]) != PLAN["ticks_per_cell"]:
        raise ValueError("missing conservation evidence")
    for outcome in row["readouts"]:
        snapshot(outcome)
        # Readouts retain nonclinical autonomic channels for mechanistic diagnosis.
        for channel in ("sympathetic", "parasympathetic"):
            number(outcome[channel], 0, 1)
        if outcome["emotion"] not in ("neutral", "fear", "anger", "affection", "curiosity"):
            raise ValueError("unexpected native emotion")
        number(outcome["emotion_intensity"], 0, 1)
    for audit in row["native_audits"]:
        for key, limit in (("energy_error_J", 5e-5),
                           ("water_error_L", 1e-8),
                           ("neural_clock_error_s", 1e-7)):
            err = number(audit[key], 0, limit)
            if not math.isfinite(err):
                raise ValueError("nonfinite conservation error")
    return identity


def summarize(cells: list[dict]) -> dict:
    """Pure, predeclared 2x2 comparison; never count same-context cells as independent."""
    if not isinstance(cells, list) or len(cells) != len(EXPECTED):
        raise ValueError("exactly eight cells required")
    by_id = {}
    for cell in cells:
        key = ensure_one_row(cell)
        if key in by_id:
            raise ValueError("duplicate ablation identity")
        by_id[key] = cell
    if set(by_id) != EXPECTED:
        raise ValueError("incomplete ablation")
    out = []
    for context in PLAN["contexts"]:
        rows = {key: row for key, row in by_id.items() if key[0] == context}
        if len({row["initial_checkpoint_sha256"] for row in rows.values()}) != 1:
            raise ValueError("unmatched full initial checkpoints")
        if len({encode(snapshot(row["initial"])) for row in rows.values()}) != 1:
            raise ValueError("unmatched initial observations")
        all_executed = all(
            cell["executed"] == [cell["requested"]]*PLAN["ticks_per_cell"]
            for cell in rows.values())
        for action in PLAN["actions"]:
            on = rows[(context, action, "enabled")]
            off = rows[(context, action, "disabled")]
            initial = on["initial"]["arousal"]
            on_val = on["readouts"][0]["arousal"]
            off_val = off["readouts"][0]["arousal"]
            out.append({
                "context": context, "requested": action,
                "initial_arousal": initial,
                "first_tick_arousal_enabled": on_val,
                "first_tick_arousal_disabled": off_val,
                "first_tick_route_delta": on_val - off_val,
                "first_tick_arousal_change_enabled": on_val - initial,
                "first_tick_arousal_change_disabled": off_val - initial,
                "second_tick_route_delta": (on["readouts"][1]["arousal"] -
                                            off["readouts"][1]["arousal"]),
                "native_emotion_first_tick_enabled": on["readouts"][0]["emotion"],
                "native_emotion_first_tick_disabled": off["readouts"][0]["emotion"],
                "same_initial_checkpoint": True,
                "native_action_agreed": all_executed,
            })
    results = {
        "schema": "tadash-affect-autonomic-ablation-result/1",
        "synthetic": True,
        "plan_sha256": digest(PLAN),
        "cells": len(cells),
        "intervention_native_ticks": len(cells)*PLAN["ticks_per_cell"],
        "comparisons": out,
        "all_actions_executed_as_requested": all(x["native_action_agreed"] for x in out),
        "independent_replications": 0,
        "causal_scope": "controlled difference within deterministic synthetic software only",
        "human_physiology_claim": False,
        "main_modified": False,
        "model_weights_changed": False,
        "paid_api_calls": 0,
    }
    # The report is not a pretext to silently declare that the proposed cause
    # was proven. It exposes both negative and positive route effects unchanged.
    results["interpretation_status"] = (
        "admissible_software_ablation" if results["all_actions_executed_as_requested"]
        else "inconclusive_native_action_veto")
    return results


def timestamp(seconds: float) -> str:
    return (datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(seconds=seconds)).isoformat()


def metrics(body) -> dict:
    m = body.owner.body()["minimum_state"]
    return snapshot(m)


def readout(body) -> dict:
    d = metrics(body)
    aux = body.owner.aux
    d.update(sympathetic=number(aux["sympathetic"], 0, 1),
             parasympathetic=number(aux["parasympathetic"], 0, 1),
             emotion=aux["emotion"],
             emotion_intensity=number(aux["emotion_intensity"], 0, 1))
    return d


def native_worker(runtime: Path, output: Path) -> None:
    if os.environ.get("TADASH_ABLATION_SANDBOX") != str(runtime):
        raise RuntimeError("disposable runtime authorization mismatch")
    sys.path.insert(0, str(runtime))
    from synthetic_fixture import prepare_defaults, synthetic_body
    from unified_body_v2 import UnifiedBody
    prepare_defaults()
    cells = []
    preparation = []
    for context in PLAN["contexts"]:
        seed = synthetic_body()
        if context == "post_walk":
            for j in range(PLAN["post_walk_prep_ticks"]):
                preparatory = seed.cycle(
                    event_id=f"ablation-shared-prep-{j}",
                    at_utc=timestamp(8+j*PLAN["tick_s"]),
                    duration_s=PLAN["tick_s"], external={}, requested="walk",
                    expected_revision=seed.revision)
                preparation.append({
                    "context": context, "step": j,
                    "actual_action": preparatory["owner"]["selected_action"],
                    "audit": preparatory["whole_body_audit"]})
                if preparatory["owner"]["selected_action"] != "walk":
                    raise ValueError("preparation walked differently than declared")
        checkpoint = seed.checkpoint()
        reference_owner = seed.owner.checkpoint()
        for action in PLAN["actions"]:
            for route in PLAN["routes"]:
                body = UnifiedBody.restore(deepcopy(checkpoint))
                if body.owner.checkpoint() != reference_owner:
                    raise AssertionError("restoration changed native owner state")
                if route == "disabled":
                    # Explicit synthetic-route ablation BEFORE any action.
                    # Do not alter native source, affect state, organs or costs.
                    body.disabled = ["affect_to_autonomic"]
                if body.owner.checkpoint() != reference_owner:
                    raise AssertionError("ablation changed the pre-action owner")
                initial = metrics(body)
                readouts, executed, audits = [], [], []
                for tick in range(PLAN["ticks_per_cell"]):
                    result = body.cycle(
                        event_id=f"ablation-{context}-{action}-{route}-{tick}",
                        at_utc=timestamp(10+PLAN["tick_s"]*tick),
                        duration_s=PLAN["tick_s"], external={}, requested=action,
                        expected_revision=body.revision)
                    readouts.append(readout(body))
                    executed.append(result["owner"]["selected_action"])
                    audits.append({
                        k: result["whole_body_audit"][k]
                        for k in ("energy_error_J", "water_error_L", "neural_clock_error_s")})
                cells.append({
                    "context": context, "requested": action, "route": route,
                    "synthetic": True,
                    "initial_checkpoint_sha256": checkpoint["sha256"],
                    "initial": initial, "readouts": readouts,
                    "executed": executed, "native_audits": audits})
    write(output/"cells.json", cells)
    write(output/"preparation.json", preparation)
    report = summarize(cells)
    report["preparation_walk_ticks"] = len(preparation)
    report["fresh_synthetic_origins"] = len(PLAN["contexts"])
    write(output/"summary.json", report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worker-runtime", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker_runtime:
        native_worker(args.worker_runtime.resolve(), output)
        return 0
    # Exclusive path refuses replay, even if first run interrupted.
    output.mkdir(parents=True, exist_ok=False)
    write(output/"plan.json", {**PLAN, "sha256": digest(PLAN)})
    write(output/"status.json", {"status": "running", "automatic_retry": False})
    runtime = REPO/"runtimes/tadash_body"
    if not (runtime/"synthetic_fixture.py").exists():
        write(output/"status.json", {
            "status": "blocked", "reason": "complete_native_source_checkout_missing",
            "automatic_retry": False})
        return 2
    before = file_hashes(runtime)
    write(output/"native-source-hashes.json", before)
    try:
        with tempfile.TemporaryDirectory(prefix="tadash-ablation-") as tmp:
            target = Path(tmp)/"runtime"
            shutil.copytree(runtime, target, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.sqlite", "*.sqlite-*", "*.db", "*.db-*"))
            env = {
                "PATH": os.environ.get("PATH", ""), "HOME": tmp,
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "TADASH_ABLATION_SANDBOX": str(target),
            }
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                  "--worker-runtime", str(target),
                                  "--output", str(output)],
                                 cwd=tmp, env=env, capture_output=True, text=True,
                                 timeout=150)
            (output/"native.stdout.log").write_text(run.stdout)
            (output/"native.stderr.log").write_text(run.stderr)
            sys.stdout.write(run.stdout); sys.stderr.write(run.stderr)
            if run.returncode:
                raise RuntimeError(f"native ablation worker failed with code {run.returncode}")
        if before != file_hashes(runtime):
            raise AssertionError("original runtime changed")
        write(output/"status.json", {
            "status": "completed", "source_unchanged": True,
            "native_stocks_persisted": False, "paid_api_calls": 0,
            "upstream_frameworks_executed": False})
        write(output/"manifest.json", file_hashes(output))
        return 0
    except BaseException as exc:
        write(output/"status.json", {
            "status": "failed_or_unknown", "automatic_retry": False,
            "error_type": type(exc).__name__, "source_unchanged": before == file_hashes(runtime)})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
