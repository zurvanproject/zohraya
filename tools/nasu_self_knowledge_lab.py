#!/usr/bin/env python3
"""Nasuraya offline self-knowledge laboratory. No I/O, network, model calls or writes.

Inspired by Lyra capability inspection, Anima reversible memory consolidation,
and MetaCog-Bench deterministic calibration. No external code copied.
"""
import datetime as dt
import hashlib
import json
import math
import re

SCHEMA = "nasuraya-self-knowledge-lab/0.1"
SOURCE = "nasuraya-agent-diagnostics/1"
PROVENANCE = "unattested_sanitized_diagnostics"
CAPABILITIES = ("inference", "research", "memory")
ALLOWED = ("PROBE_PASSED", "OBSERVED", "UNKNOWN", "NOT_MEASURED")
LIMITS = ["no_subjective_awareness_inference", "no_live_dios_or_body_claim",
          "no_offsite_recovery_claim", "no_self_modification_claim"]


def require(ok, code):
    if not ok:
        raise ValueError(code)


def timestamp(value):
    require(type(value) is str and
            re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value),
            "invalid_utc")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid_utc") from None
    return parsed.replace(tzinfo=dt.timezone.utc)


def number(value):
    return type(value) is int and 0 <= value <= 100000000


def active(units, key):
    row = units.get(key, {})
    return isinstance(row, dict) and row.get("load") == "loaded" and row.get("active") == "active"


def self_model(receipt):
    """Project only explicitly evidenced capabilities. Input is not attested."""
    require(isinstance(receipt, dict) and receipt.get("schema") == SOURCE and
            receipt.get("mode") in ("status", "probe"), "invalid_diagnostic")
    timestamp(receipt.get("utc"))
    units, cognition, integration, executable = (
        receipt.get("units"), receipt.get("cognition"),
        receipt.get("integration"), receipt.get("executables"))
    require(all(isinstance(v, dict) for v in
                (units, cognition, integration, executable)), "invalid_shape")
    probe = receipt.get("probe", {})
    probed = (receipt["mode"] == "probe" and isinstance(probe, dict)
              and probe.get("state") == "success" and active(units, "ollama")
              and executable.get("match") is True)
    counts = [cognition.get(k) for k in ("completed", "drafts", "failed", "incomplete")]
    coherent = all(number(x) for x in counts) and counts[0] == counts[1] + counts[2]
    research = (coherent and counts[0] > 0
                and cognition.get("state") == "verified_history"
                and executable.get("match") is True
                and active(units, "cognition_timer"))
    memory = (integration.get("state") == "ok"
              and number(integration.get("records"))
              and integration.get("records") > 0)
    return {
        "schema": SCHEMA, "utc": receipt["utc"], "provenance": PROVENANCE,
        "capabilities": {
            "inference": "PROBE_PASSED" if probed else "NOT_MEASURED",
            "research": "OBSERVED" if research else "UNKNOWN",
            "memory": "OBSERVED" if memory else "UNKNOWN"},
        "limits": list(LIMITS),
    }


def validate_snapshot(item):
    require(isinstance(item, dict) and set(item) ==
            {"schema", "utc", "provenance", "capabilities", "limits"}
            and item["schema"] == SCHEMA and item["provenance"] == PROVENANCE
            and item["limits"] == LIMITS, "invalid_snapshot")
    moment = timestamp(item["utc"])
    values = item["capabilities"]
    require(isinstance(values, dict) and set(values) == set(CAPABILITIES)
            and all(type(x) is str and x in ALLOWED for x in values.values()),
            "invalid_capabilities")
    return moment


def consolidation_preview(snapshots):
    """Never delete original episodes or turn local digests into signatures."""
    require(type(snapshots) in (list, tuple) and 1 <= len(snapshots) <= 32,
            "invalid_snapshot_count")
    dates = [validate_snapshot(s) for s in snapshots]
    require(all(y > x for x, y in zip(dates, dates[1:])),
            "out_of_order")
    decisions = {}
    for name in CAPABILITIES:
        latest = snapshots[-1]["capabilities"][name]
        if len(snapshots) == 1 or latest in ("UNKNOWN", "NOT_MEASURED"):
            status = "INSUFFICIENT"
        elif snapshots[-2]["capabilities"][name] != latest:
            status = "REVIEW_CHANGED_EVIDENCE"
        else:
            status = "RETAIN_CANDIDATE"
        decisions[name] = {"state": status,
                           "value": latest if status == "RETAIN_CANDIDATE" else None}
    raw = json.dumps(snapshots, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {"schema": "nasuraya-memory-preview/0.1",
            "state": "PROPOSAL_NOT_APPLIED", "originals_retained": True,
            "snapshot_count": len(snapshots),
            "input_sha256": hashlib.sha256(raw.encode("ascii")).hexdigest(),
            "decisions": decisions,
            "limitations": ["no_deletion", "no_live_memory_write", "not_attested"]}


def calibration_preview(cases):
    """Deterministic five-bin ECE and Brier; never grade with model claims."""
    require(type(cases) in (list, tuple) and 1 <= len(cases) <= 1000,
            "invalid_cases")
    seen = set()
    buckets = [[] for _ in range(5)]
    brier = 0.0
    correct = 0
    for item in cases:
        require(isinstance(item, dict) and set(item) ==
                {"id", "confidence", "correct", "grader"}, "invalid_case")
        name, p, y = item["id"], item["confidence"], item["correct"]
        require(type(name) is str and
                re.fullmatch(r"[a-zA-Z0-9_.:-]{1,80}", name) and name not in seen,
                "duplicate_or_invalid_id")
        seen.add(name)
        require(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
                and type(y) is bool and item["grader"] == "independent_fixed_rubric",
                "untrusted_grade")
        buckets[min(int(p * 5), 4)].append((p, int(y)))
        brier += (p - int(y)) ** 2
        correct += int(y)
    n = len(cases)
    ece = sum((len(b) / n) *
              abs(sum(x for x, _ in b) / len(b) -
                  sum(y for _, y in b) / len(b)) for b in buckets if b)
    return {"schema": "nasuraya-calibration-preview/0.1",
            "status": "DESCRIPTIVE_ONLY" if n < 20 else "SCORED_HOLDOUT",
            "n": n, "accuracy": round(correct / n, 6),
            "ece_5bin": round(ece, 6), "brier": round(brier / n, 6),
            "model_calls": 0, "weight_updates": 0,
            "subjective_awareness_proven": False}
