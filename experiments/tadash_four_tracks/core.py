"""Offline evidence contracts for four Tadash research tracks.

Original adapter code, inspired by the referenced projects, NOT their runtime.
No network client, model API, weight update, physical actuation or live state.
Thresholds are experimental software choices, not clinical safety limits.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import fmean
from typing import Any
import xml.etree.ElementTree as ET

METRICS = ("arousal", "pain", "fatigue", "energy", "hydration")
ACTIONS = {"observe", "slow_breath", "protect", "walk"}
SOURCES = {
    "outcome": {"repo": "PhyAgentOS/PhyAgentOS-core", "ref": "v1.1.1",
        "use": "execution is distinct from verified task success; original implementation"},
    "memory": {"repo": "vectorize-io/hindsight", "ref": "v1.1.0",
        "path": "hindsight-docs/docs/developer/api/retain.mdx",
        "use": "offline retain items; no extraction or recall service invoked"},
    "motion": {"repo": "mujocolab/mjlab", "ref": "v1.6.0",
        "use": "asset/readiness audit only; no GPU training"},
    "rehearsal": {"repo": "gurpnijjer/dream-rehearsal", "ref": None,
        "use": "concept only; immutable revision and license review required before import"},
}


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def number(value: Any, low: float, high: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError("invalid finite number")
    return float(value)


def snapshot(value: dict) -> dict[str, float]:
    return {key: number(value[key], 0.0, 1.0) for key in METRICS}


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ValueError("invalid experiment identifier")
    return value


def review_pair(treatment: dict, control: dict, *, min_effect: float = .005,
                guard_tolerance: float = .01) -> dict:
    """Assess a paired software intervention, never infer success from dispatch."""
    number(min_effect, 1e-12, 1.0)
    number(guard_tolerance, 0.0, 1.0)
    for trial in (treatment, control):
        if trial.get("synthetic") is not True or trial.get("status") != "completed":
            raise ValueError("only completed synthetic trial receipts are admitted")
        identifier(trial["id"])
        snapshot(trial["before"]); snapshot(trial["after"])
        number(trial["duration_s"], .1, 2.0)
        actions = trial["actual_actions"]
        if not actions or any(a not in ACTIONS for a in actions):
            raise ValueError("missing or unknown executed action")
        if len(actions) != round(trial["duration_s"] * 10):
            raise ValueError("action count does not match fixed 0.1s ticks")
        if not re.fullmatch(r"[0-9a-f]{64}", trial["initial_checkpoint_sha256"]):
            raise ValueError("missing initial checkpoint digest")
    if treatment["id"] == control["id"]:
        raise ValueError("treatment and control must be different executions")
    if (treatment["initial_checkpoint_sha256"] != control["initial_checkpoint_sha256"]
            or snapshot(treatment["before"]) != snapshot(control["before"])
            or treatment["duration_s"] != control["duration_s"]):
        raise ValueError("unmatched initial conditions or time horizon")
    if treatment["requested"] != "slow_breath" or control["requested"] != "observe":
        raise ValueError("predeclared comparison is slow_breath versus observe")
    effects = {k: (treatment["after"][k] - treatment["before"][k])
                  - (control["after"][k] - control["before"][k]) for k in METRICS}
    veto = any(a != "slow_breath" for a in treatment["actual_actions"])
    veto |= any(a != "observe" for a in control["actual_actions"])
    adverse = any(effects[k] > guard_tolerance for k in ("pain", "fatigue"))
    adverse |= any(effects[k] < -guard_tolerance for k in ("energy", "hydration"))
    verdict = ("inconclusive" if veto else
               "met" if effects["arousal"] <= -min_effect and not adverse else "not_met")
    return {"schema": "tadash-outcome-review/1", "synthetic": True,
        "treatment_id": treatment["id"], "control_id": control["id"],
        "duration_s": treatment["duration_s"], "verdict": verdict,
        "reason": "native_veto" if veto else "predeclared_paired_endpoint",
        "effects_vs_control": effects, "adverse_proxy_difference": adverse,
        "thresholds": {"min_arousal_effect": min_effect, "guard_tolerance": guard_tolerance},
        "evidence_sha256": digest([treatment, control]),
        "empirical_physiology": False, "generalization_established": False}


def hindsight_items(treatment: dict, control: dict, review: dict) -> dict:
    """Build allowlisted synthetic retain payloads; never send them anywhere.

    category is our metadata, not a claim about Hindsight's inferred fact_type.
    Raw signed-by-hash receipts remain outside Hindsight's lossy extraction.
    """
    recomputed = review_pair(treatment, control,
        min_effect=review["thresholds"]["min_arousal_effect"],
        guard_tolerance=review["thresholds"]["guard_tolerance"])
    if encode(recomputed) != encode(review):
        raise ValueError("review does not match raw receipts")
    source = review["evidence_sha256"]
    parts = {
        "intention": {"goal": "reduce software arousal relative to observe",
            "requested": treatment["requested"], "duration_s": treatment["duration_s"]},
        "observation": {"treatment_actual": treatment["actual_actions"],
            "control_actual": control["actual_actions"],
            "treatment_before": snapshot(treatment["before"]),
            "treatment_after": snapshot(treatment["after"]),
            "control_after": snapshot(control["after"])},
        "interpretation": {"verdict": review["verdict"], "reason": review["reason"],
            "effects_vs_control": review["effects_vs_control"],
            "not_a_general_rule": True, "not_subjective_experience": True},
    }
    items = [{"content": encode(value), "timestamp": "unset",
        "context": "Synthetic Tadash software experiment, not a human event or lived experience",
        "document_id": f"tadash-{source}-{category}",
        "metadata": {"category": category, "evidence_sha256": source,
            "synthetic": "true", "schema": "tadash-memory-export/1"},
        "tags": ["tadash-synthetic", category]} for category, value in parts.items()]
    return {"items": items}


def vector_rows(rows: list) -> list[list[float]]:
    if not rows:
        raise ValueError("empty evaluation")
    result = []
    for row in rows:
        if len(row) != len(METRICS):
            raise ValueError("all five normalized channels are required")
        result.append([number(v, 0.0, 1.0) for v in row])
    return result


def rehearsal_gate(predicted: list, observed: list, persistence: list,
                   train_ids: list[str], eval_ids: list[str]) -> dict:
    """Pilot scoring only. No pilot result can authorize imagined replay.

    A separate prospective independent evaluation is mandatory. Keeping the
    gate closed here avoids a caller turning a boolean into evidence.
    """
    p, y, b = map(vector_rows, (predicted, observed, persistence))
    if not (len(p) == len(y) == len(b) == len(eval_ids)):
        raise ValueError("unaligned outcomes/predictions/baseline")
    for item in train_ids + eval_ids:
        identifier(item)
    if not train_ids or len(set(train_ids)) != len(train_ids):
        raise ValueError("invalid training identifiers")
    if len(set(eval_ids)) != len(eval_ids) or set(train_ids).intersection(eval_ids):
        raise ValueError("duplicate outcomes or train/evaluation leakage")
    mae = fmean(abs(a - z) for row, truth in zip(p, y) for a, z in zip(row, truth))
    baseline = fmean(abs(a - z) for row, truth in zip(b, y) for a, z in zip(row, truth))
    better = mae < baseline - 1e-12
    return {"schema": "tadash-world-model-pilot/1", "rows": len(y),
        "mae": mae, "persistence_mae": baseline, "provisionally_better": better,
        "rollout_authorized": False, "actor_training_started": False,
        "reason": "independent_prospective_multistep_validation_missing" if better
                  else "candidate_does_not_beat_persistence",
        "independent_samples_claimed": False, "upstream_dreamer_executed": False}


def inspect_mjcf(path: Path) -> dict:
    """Structural preflight; explicit masses do not replace MuJoCo compilation."""
    raw = path.read_bytes()
    if len(raw) > 2_000_000 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("unsupported XML document")
    root = ET.fromstring(raw)
    if root.tag != "mujoco":
        raise ValueError("not MJCF")
    masses = [number(float(e.attrib["mass"]), 1e-12, 10000)
              for e in root.iter("inertial") if "mass" in e.attrib]
    return {"xml_sha256": hashlib.sha256(raw).hexdigest(),
        "body_count": len(list(root.iter("body"))),
        "explicit_inertial_mass_sum_kg": sum(masses),
        "includes_present": bool(list(root.iter("include"))),
        "compiled_total_mass_kg": None, "compiled": False,
        "note": "geoms/defaults/includes can contribute mass; sum is not verified total"}


def motion_readiness(repo: Path) -> dict:
    runtime = repo / "runtimes/tadash_body/unified_body_v2.py"
    text = runtime.read_text() if runtime.exists() else ""
    literal = "195.0*3500.0" in text
    # This does not silently substitute a toy robot for the user's atlas.
    assets = sorted((repo / "examples/nasuraya_research").glob("**/*.xml"))
    checked = [{"path": str(p.relative_to(repo)), **inspect_mjcf(p)} for p in assets[:20]]
    return {"schema": "tadash-mjlab-preflight/1", "assets": checked,
        "asset_list_truncated": len(assets) > 20,
        "native_thermal_mass_literal_kg": 195.0 if literal else None,
        "reported_atlas_mass_kg": 78.0,
        "atlas_mass_provenance": "PR100 description, not compiled in this experiment",
        "status": "blocked_uncompiled_assets" if checked else "blocked_missing_atlas_xml_on_base",
        "mjlab_imported": False, "gpu_training_started": False,
        "state_mutated": False,
        "next": "fetch and audit pinned PR95 articulated source; compile actual atlas on CPU"}


def summarize_trials(trials: list[dict]) -> dict:
    return {"trial_count": len(trials),
        "native_cycles": sum(len(t["actual_actions"]) for t in trials),
        "actions": dict(Counter(a for t in trials for a in t["actual_actions"]))}
