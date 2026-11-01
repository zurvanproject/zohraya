"""Five-action shadow self-model with explicit metacognitive abstention.

Offline estimator for Tadash native software action receipts, not a feeling,
subjective introspection, calibrated confidence or permission to act.
The four-class control is lifted onto the SAME five-class outcome space using
only frozen training frequencies, so the Brier comparison is interpretable.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math

from .self_knowledge import forecast_action

SCHEMA = "nasuraya-five-action-metacognition/1"
SCORE_SCHEMA = "nasuraya-five-action-metacognition-score/1"
LABELS = ("walk", "observe", "protect", "slow_breath", "other")
MIN_LOCAL = 3
MIN_TOP_PROBABILITY = 0.60
MIN_MARGIN = 0.20


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


def bucket(action):
    if not isinstance(action, str) or not action.strip():
        raise ValueError("nonempty native action required")
    return action if action in LABELS[:4] else "other"


def distribution(rows):
    counts = dict.fromkeys(LABELS, 1)
    for row in rows:
        counts[bucket(row["actual_action"])] += 1
    total = len(rows) + len(LABELS)
    return {k: counts[k] / total for k in LABELS}


def validate_distribution(values):
    if not isinstance(values, Mapping) or set(values) != set(LABELS):
        raise ValueError("five-class distribution must have all five exact labels")
    if any(type(v) not in (float, int) or not math.isfinite(v) or
           v < 0 or v > 1 for v in values.values()):
        raise ValueError("probabilities must be finite and in [0,1]")
    if not math.isclose(sum(values.values()), 1., abs_tol=1e-12, rel_tol=0):
        raise ValueError("probabilities do not sum to one")


def forecast_five(episodes, *, context, preferred, duration_s):
    """Freeze five-class forecast and four-class control before the action.

    Same available training rows for all models. The legacy 4-way 'other'
    mass is split by a Beta(1,1)-smoothed fraction, fit on training ONLY.
    Confidence gate is heuristic and explicitly NOT empirically calibrated.
    """
    episodes = list(episodes)
    legacy = forecast_action(episodes, context=context, preferred=preferred,
                             duration_s=duration_s, enabled=True)
    selected_ids = legacy["pooled_source_ids"]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("duplicate source IDs in native training")
    selected = set(selected_ids)
    pooled = [e for e in episodes if isinstance(e, Mapping) and e.get("id") in selected]
    if len(pooled) != len(selected):
        raise ValueError("missing or duplicated training receipts")
    local = [e for e in pooled if e.get("context") == context]
    if len(local) != legacy["samples"] or len(pooled) != legacy["pooled_samples"]:
        raise ValueError("training counts differ from legacy evidence")
    estimate = distribution(local)
    pooled_estimate = distribution(pooled)
    other_events = sum(bucket(e["actual_action"]) in ("slow_breath", "other")
                       for e in pooled)
    slow_events = sum(bucket(e["actual_action"]) == "slow_breath" for e in pooled)
    split = (slow_events + 1) / (other_events + 2)
    baseline = {k: legacy["distribution"][k] for k in LABELS[:3]}
    baseline["slow_breath"] = legacy["distribution"]["other"] * split
    baseline["other"] = legacy["distribution"]["other"] * (1 - split)
    for probabilities in (estimate, pooled_estimate, baseline):
        validate_distribution(probabilities)

    top_two = sorted(LABELS, key=lambda k: (-estimate[k], LABELS.index(k)))[:2]
    top, second = top_two
    confidence = estimate[top]
    margin = confidence - estimate[second]
    entropy = -sum(p * math.log(p) for p in estimate.values() if p) / math.log(len(LABELS))
    if len(local) < MIN_LOCAL:
        status = "abstain_insufficient_local_evidence"
    elif confidence < MIN_TOP_PROBABILITY or margin < MIN_MARGIN:
        status = "abstain_uncertain_prediction"
    else:
        status = "eligible_for_shadow_prediction"
    result = dict(
        schema=SCHEMA, labels=list(LABELS), context=context, preferred=preferred,
        duration_s=duration_s, distribution=estimate, pooled_distribution=pooled_estimate,
        lifted_four_distribution=baseline, samples=len(local), pooled_samples=len(pooled),
        source_ids=list(legacy["source_ids"]), pooled_source_ids=list(selected_ids),
        legacy_model_digest=legacy["model_digest"], rare_training_events=slow_events,
        raw_top_action=top, predicted_action=(top if status.startswith("eligible") else None),
        status=status, abstained=not status.startswith("eligible"),
        top_probability=confidence, probability_margin=margin,
        normalized_entropy=entropy,
        scope="offline software-action shadow forecast; heuristic abstention; no actuator authority",
    )
    result["model_digest"] = digest(result)
    return result


def brier(probabilities, actual):
    validate_distribution(probabilities)
    label = bucket(actual)
    return sum((probabilities[k] - float(k == label)) ** 2 for k in LABELS)


def score_five(forecast, actual_action, source):
    if not isinstance(forecast, Mapping) or forecast.get("schema") != SCHEMA:
        raise ValueError("unknown five-class forecast schema")
    if forecast.get("model_digest") != digest({
            k: v for k, v in forecast.items() if k != "model_digest"}):
        raise ValueError("changed forecast evidence")
    if not isinstance(source, str) or not source.startswith("native-decision://"):
        raise ValueError("only authoritative native action outcomes accepted")
    for key in ("distribution", "pooled_distribution", "lifted_four_distribution"):
        validate_distribution(forecast.get(key))
    if type(forecast.get("abstained")) is not bool:
        raise ValueError("explicit abstention flag required")
    if forecast["abstained"] != (forecast["predicted_action"] is None):
        raise ValueError("abstention inconsistent with prediction")
    actual = bucket(actual_action)
    result = dict(
        schema=SCORE_SCHEMA, actual_action=actual_action, actual=actual,
        source=source, model_digest=forecast["model_digest"],
        brier=brier(forecast["distribution"], actual),
        pooled_brier=brier(forecast["pooled_distribution"], actual),
        lifted_four_brier=brier(forecast["lifted_four_distribution"], actual),
        abstained=forecast["abstained"], predicted_action=forecast["predicted_action"],
        top_probability=forecast["top_probability"],
        correct_when_covered=(None if forecast["abstained"] else
                              forecast["predicted_action"] == actual),
    )
    result["evidence_digest"] = digest(result)
    return result
