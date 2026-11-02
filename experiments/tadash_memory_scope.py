"""Fail-closed, OFFLINE scope overlay for synthetic Tadash -> Hindsight v1.1.0.

Pure stdlib; never connects to a service or authorizes sending human data.
This adapts previously produced v1 retain items to a DISTINCT v2 document ID.
Hash links are not signatures. Hindsight tags are not an authentication boundary.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re

METRICS = ("arousal", "pain", "fatigue", "energy", "hydration")
ACTIONS = frozenset(("observe", "slow_breath", "protect", "walk"))
CATEGORIES = ("intention", "observation", "interpretation")
CONTEXT = "Synthetic Tadash software experiment, not a human event or lived experience"
GOAL = "reduce software arousal relative to observe"
SOURCE_RE = re.compile(r"[0-9a-f]{64}\Z")


def _exact_fields(obj, keys, label):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError(f"{label}: unexpected keys")


def _numeric(value, low, high, label):
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{label}: invalid finite number")
    return float(value)


def _metrics(obj, label):
    _exact_fields(obj, METRICS, label)
    return {key: _numeric(obj[key], 0, 1, f"{label}.{key}") for key in METRICS}


def _native_actions(value, length, label):
    if (not isinstance(value, list) or len(value) != length
            or any(not isinstance(x, str) or x not in ACTIONS for x in value)):
        raise ValueError(f"{label}: malformed native actions")
    return value


def _content(item, source, kind):
    if not isinstance(item.get("content"), str) or len(item["content"]) > 4096:
        raise ValueError("content must be bounded JSON text")
    try:
        parsed = json.loads(item["content"], parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid memory content") from exc
    if kind == "intention":
        _exact_fields(parsed, ("goal", "requested", "duration_s"), kind)
        if parsed["goal"] != GOAL or parsed["requested"] != "slow_breath":
            raise ValueError("unexpected intention or free text")
        ticks = round(_numeric(parsed["duration_s"], .1, 2.0, "duration")*10)
        if abs(float(parsed["duration_s"])*10-ticks) > 1e-8:
            raise ValueError("duration is not native-tick aligned")
        return {"duration_s": parsed["duration_s"], "ticks": ticks}
    if kind == "observation":
        _exact_fields(parsed, ("treatment_actual", "control_actual", "treatment_before",
                               "treatment_after", "control_after"), kind)
        return {"treatment": parsed["treatment_actual"], "control": parsed["control_actual"],
                "before": _metrics(parsed["treatment_before"], "treatment_before"),
                "after": _metrics(parsed["treatment_after"], "treatment_after"),
                "control_after": _metrics(parsed["control_after"], "control_after")}
    _exact_fields(parsed, ("verdict", "reason", "effects_vs_control",
                           "not_a_general_rule", "not_subjective_experience"), kind)
    if (parsed["verdict"] not in ("met", "not_met", "inconclusive")
            or parsed["reason"] not in ("native_veto", "predeclared_paired_endpoint")
            or parsed["not_a_general_rule"] is not True
            or parsed["not_subjective_experience"] is not True):
        raise ValueError("invalid interpretation")
    _exact_fields(parsed["effects_vs_control"], METRICS, "effects_vs_control")
    return {"verdict": parsed["verdict"], "reason": parsed["reason"],
            "effects": {key: _numeric(parsed["effects_vs_control"][key], -1, 1,
                                       f"effect.{key}") for key in METRICS}}


def verify_legacy_synthetic(batch):
    """Admit exactly one three-part **synthetic** comparison, no arbitrary text.

    This verifies internal consistency, not the raw native receipt or its source SHA.
    Caller must separately verify raw native receipts before trusting provenance.
    """
    _exact_fields(batch, ("items",), "batch")
    items = batch["items"]
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError("exactly one synthetic triple is required")
    docs = {}
    source = None
    for item in items:
        _exact_fields(item, ("content", "timestamp", "context", "document_id", "metadata", "tags"), "item")
        meta = item["metadata"]
        _exact_fields(meta, ("category", "evidence_sha256", "synthetic", "schema"), "metadata")
        if any(not isinstance(v, str) for v in meta.values()):
            raise ValueError("metadata values must be text")
        category, sha = meta["category"], meta["evidence_sha256"]
        if (category not in CATEGORIES or not isinstance(sha, str)
                or SOURCE_RE.fullmatch(sha) is None):
            raise ValueError("invalid evidence category or digest")
        if source is None:
            source = sha
        if source != sha or category in docs:
            raise ValueError("mixed sources or duplicate category")
        if (meta["synthetic"] != "true" or meta["schema"] != "tadash-memory-export/1"
                or item["timestamp"] != "unset" or item["context"] != CONTEXT
                or item["document_id"] != f"tadash-{sha}-{category}"
                or item["tags"] != ["tadash-synthetic", category]):
            raise ValueError("untrusted or non-synthetic input")
        docs[category] = _content(item, sha, category)
    if set(docs) != set(CATEGORIES):
        raise ValueError("incomplete comparison")
    intention, observed, interpretation = (docs[k] for k in CATEGORIES)
    ticks = intention["ticks"]
    _native_actions(observed["treatment"], ticks, "treatment")
    _native_actions(observed["control"], ticks, "control")
    # The v1 exported control-before is implicit because native trial checkpoints
    # were verified equal before the export, NOT proven by this reduced payload.
    for key in METRICS:
        actual = observed["after"][key] - observed["control_after"][key]
        if not math.isclose(actual, interpretation["effects"][key], abs_tol=1e-10, rel_tol=0):
            raise ValueError("interpretation disagrees with numeric observations")
    veto = (any(x != "slow_breath" for x in observed["treatment"])
            or any(x != "observe" for x in observed["control"]))
    if veto and (interpretation["verdict"] != "inconclusive"
                 or interpretation["reason"] != "native_veto"):
        raise ValueError("native veto not preserved")
    if not veto and interpretation["reason"] != "predeclared_paired_endpoint":
        raise ValueError("invalid conclusion reason")
    if interpretation["verdict"] == "met" and interpretation["effects"]["arousal"] >= 0:
        raise ValueError("unsupported improvement claim")
    return source


def _scoped_tags(source, kind):
    if kind not in CATEGORIES or not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None:
        raise ValueError("invalid scope token")
    return ["tadash-synthetic", f"tadash-evidence:{source}", f"tadash-kind:{kind}"]


def scope_one_synthetic_comparison(batch):
    """Produce offline-only retain-shaped data; never performs ingestion.

    Explicitly overrides potentially unsafe bank default observation scopes.
    v2 document IDs avoid replacing v1 memories accidentally during a dry run.
    """
    source = verify_legacy_synthetic(batch)
    out = deepcopy(batch)
    for item in out["items"]:
        category = item["metadata"]["category"]
        item["document_id"] = f"tadash-v2-{source}-{category}"
        item["tags"] = _scoped_tags(source, category)
        item["observation_scopes"] = "combined"
        item["update_mode"] = "replace"
    return out


def exact_recall_scope(source, category):
    """Generate fixed-text synthetic recall scope; not authorization/network."""
    return {"query": "summarize synthetic Tadash experiment evidence",
            "tags": _scoped_tags(source, category), "tags_match": "exact"}


def verify_exact_recall_scope(spec, expected_source, expected_category):
    """Verify against a trusted caller's expected evidence/category identity."""
    _exact_fields(spec, ("query", "tags", "tags_match"), "recall")
    wanted = exact_recall_scope(expected_source, expected_category)
    if spec != wanted:
        raise ValueError("scope filter must exactly match trusted expected identity")
    return True
