"""Read-only, bounded experiential decision calibration over verified SelfModel counts.

This module NEVER issues a body action, grants admission, or writes to the native
ledger. Only SelfModel.finish may create verified learning evidence.
"""
from dataclasses import dataclass
from copy import deepcopy
import math

from .monitor import forecast, POLICY as NATIVE_POLICY

MAX_CONTEXTS = 128
MAX_OBSERVATIONS = 128
MIN_PROBABILITY = NATIVE_POLICY["continue_threshold"]


def _validate_counts(counts):
    if not isinstance(counts, dict) or len(counts) > MAX_CONTEXTS:
        raise ValueError("invalid context store")
    total = 0
    for key, value in counts.items():
        if not isinstance(key, str) or not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError("invalid experience")
        a, b = value
        if type(a) is not int or type(b) is not int or min(a, b) < 0:
            raise ValueError("invalid receipt counts")
        total += a + b
    if total > MAX_OBSERVATIONS:
        raise ValueError("experience budget exceeded")


def recommend(knowledge, context_key, native_restrictions=()):
    """A deny-only advisory layer. Native admission remains authoritative."""
    if not isinstance(knowledge, dict) or knowledge.get("pending"):
        raise ValueError("unresolved outcomes prevent new recommendations")
    counts = knowledge["counts"]
    _validate_counts(counts)
    if not isinstance(context_key, str) or not context_key:
        raise ValueError("invalid context key")
    if not isinstance(native_restrictions, (list, tuple)):
        raise ValueError("invalid restrictions")
    prediction = forecast(counts, context_key)
    blockers = list(native_restrictions)
    if prediction["samples"] < NATIVE_POLICY["min_samples"]:
        blockers.append("insufficient_verified_experience")
    if prediction["probability"] < MIN_PROBABILITY:
        blockers.append("low_verified_admission")
    return dict(choice="defer" if blockers else "candidate_under_native_guards",
                probability=prediction["probability"], samples=prediction["samples"],
                uncertainty="unseen" if prediction["unseen_context"] else
                  "limited_sample" if prediction["samples"] < 10 else "empirical",
                reasons=blockers, authority="advisory_only")


def compare_arms(cases, *, initial_counts=None):
    """Causal policy ablation on explicitly supplied *synthetic* receipt labels.

    A: no memory, B: initial frozen memory, C: sequential adaptive memory.
    No data are sampled here and no outcomes are invented. Caller owns split.
    Only prior outcomes within a trial are visible to C. A/B/C never
    influence each other's state. All arms observe the same ordered cases.
    """
    frozen = deepcopy(initial_counts or {})
    _validate_counts(frozen)
    if not isinstance(cases, (tuple, list)) or len(cases) > MAX_OBSERVATIONS:
        raise ValueError("bounded list of cases required")
    adaptive = deepcopy(frozen)
    result = {arm: [] for arm in ("A", "B", "C")}
    seen_ids = set()
    for item in cases:
        if not isinstance(item, dict) or set(item) != {"id", "context", "admitted", "restrictions"}:
            raise ValueError("exact, preregistered case fields required")
        ident, key, outcome = item["id"], item["context"], item["admitted"]
        if not isinstance(ident, str) or not ident or ident in seen_ids:
            raise ValueError("duplicate/invalid trial ID")
        seen_ids.add(ident)
        if type(outcome) is not bool:
            raise ValueError("binary verified-or-synthetic label required")
        restrictions = item["restrictions"]
        for arm, counts in (("A", {}), ("B", frozen), ("C", adaptive)):
            choice = recommend({"counts": counts, "pending": []}, key, restrictions)
            predicted = choice["probability"]
            result[arm].append(dict(id=ident, context=key, actual=outcome,
                choice=choice["choice"], probability=predicted,
                brier=(predicted - int(outcome)) ** 2,
                safe=(choice["choice"] != "candidate_under_native_guards" or outcome)))
        # Adaptive learning occurs strictly AFTER all three prospective predictions.
        a, b = adaptive.get(key, (0, 0))
        adaptive[key] = (a + int(outcome), b + int(not outcome))
        _validate_counts(adaptive)
    metrics = {}
    for arm, rows in result.items():
        n = len(rows)
        accepted = [x for x in rows if x["choice"] == "candidate_under_native_guards"]
        metrics[arm] = dict(n=n,
            mean_brier=sum(x["brier"] for x in rows) / n if n else None,
            false_admissions=sum(not x["actual"] for x in accepted),
            true_admissions=sum(x["actual"] for x in accepted),
            deferrals=n-len(accepted),
            action_success_rate=(sum(x["actual"] for x in accepted)/len(accepted)
                                 if accepted else None))
    return dict(metrics=metrics, predictions=result,
        final_adaptive_counts=adaptive, scope="synthetic_or_caller_verified_offline_ablation")
