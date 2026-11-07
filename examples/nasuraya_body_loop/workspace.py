"""Nasuraya's opt-in, receipt-grounded shared WORKING MEMORY for software Tadash.

This is a useful cognitive integration layer: a small global workspace selects
signals from body, prediction and previous outcomes; broadcasts them to
planning, memory and monitoring; and can *conservatively* downgrade a walk
preference to observe. Native BodyLoop still decides and may veto any action.

There is no chatbot-weight update, network, LLM call, real-world actuation,
autonomous process, mystical feeling or claimed consciousness.
"""
from copy import deepcopy
import math

SCHEMA = "nasuraya-integrated-workspace/1"
BODY = ("energy", "fatigue", "pain", "sleep_pressure")
CHANNELS = ("planner", "memory", "monitor")
ACTIONS = ("walk", "observe", "protect", "other")
CAPACITY = 2
MAX_RECEIPTS = 32


def normalized(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("minimum_state"), dict):
        raise ValueError("a native minimum_state observation is required")
    source = snapshot["minimum_state"]
    out = {}
    for key in BODY:
        value = source.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("invalid normalized software-body signal")
        out[key] = float(value)
    return out


def initial():
    return {
        "schema": SCHEMA,
        "sequence": 0,
        "receipts": [],
        "last_focus": [],
        "last_reason": None,
        "last_broadcast": {channel: [] for channel in CHANNELS},
        "scope": "persisted cognitive WORKING MEMORY on bounded software-body receipts",
    }


def validate(value):
    if not isinstance(value, dict) or set(value) != set(initial()):
        raise ValueError("integrated workspace schema mismatch")
    if value["schema"] != SCHEMA or value["scope"] != initial()["scope"]:
        raise ValueError("wrong integrated workspace version")
    if type(value["sequence"]) is not int or value["sequence"] < 0:
        raise ValueError("invalid monotonic workspace sequence")
    receipts = value["receipts"]
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS:
        raise ValueError("workspace receipt bound exceeded")
    ids = []
    for receipt in receipts:
        required = {"id", "source", "before", "preferred", "actual", "harm",
                    "prediction_error", "focus", "reason"}
        if not isinstance(receipt, dict) or set(receipt) != required:
            raise ValueError("invalid workspace receipt shape")
        if (not isinstance(receipt["id"], str) or not receipt["id"] or
                not isinstance(receipt["source"], str) or
                not receipt["source"].startswith("native-decision://")):
            raise ValueError("only native decision receipts may be learned")
        ids.append(receipt["id"])
        normalized({"minimum_state": receipt["before"]})
        if receipt["preferred"] not in ACTIONS[:2] or receipt["actual"] not in ACTIONS:
            raise ValueError("unexpected action in workspace receipt")
        for key in ("harm", "prediction_error"):
            n = receipt[key]
            if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1:
                raise ValueError("invalid workspace learning signal")
        if (not isinstance(receipt["focus"], list) or
                not 0 < len(receipt["focus"]) <= CAPACITY or
                not all(x in ("safety", "memory", "uncertainty", "goal") for x in receipt["focus"]) or
                len(set(receipt["focus"])) != len(receipt["focus"]) or
                receipt["reason"] not in ("high_body_load", "prior_harm", "base_policy")):
            raise ValueError("invalid historic workspace focus")
    if len(set(ids)) != len(ids) or value["sequence"] < len(receipts):
        raise ValueError("duplicated workspace learning receipt")
    if not isinstance(value["last_focus"], list) or len(value["last_focus"]) > CAPACITY:
        raise ValueError("invalid working-memory attention")
    if any(x not in ("safety", "memory", "uncertainty", "goal") for x in value["last_focus"]):
        raise ValueError("unknown attention focus")
    broadcast = value["last_broadcast"]
    if (not isinstance(broadcast, dict) or set(broadcast) != set(CHANNELS)
            or any(not isinstance(broadcast[c], list) or
                   broadcast[c] != value["last_focus"] for c in CHANNELS)):
        raise ValueError("workspace modules received divergent global focus")
    if value["last_reason"] not in (None, "high_body_load", "prior_harm", "base_policy"):
        raise ValueError("invalid remembered decision reason")
    return value


def _similar_harm(receipts, current):
    """Receipt-backed, bounded generalization between NEARBY software states."""
    candidates = []
    for receipt in receipts:
        if receipt["preferred"] != "walk":
            continue
        distance = sum(abs(receipt["before"][k] - current[k]) for k in BODY) / len(BODY)
        if distance <= 0.18:
            candidates.append((distance, receipt))
    # No future results, no invented memory or label-based fixture lookup.
    candidates.sort(key=lambda pair: (pair[0], pair[1]["id"]))
    selected = candidates[:6]
    if not selected:
        return 0.0, []
    risky = [r for _, r in selected if r["actual"] == "protect" or r["harm"] >= 0.5]
    return len(risky) / len(selected), [r["id"] for _, r in selected]


def prepare(state, snapshot, base_plan):
    """Fuse, attend, broadcast and propose before the outcome is observed.

    This function is PURE. It can only return a walk/observe preference, which
    the native controller can still veto. It never runs a body cycle.
    """
    validate(state)
    body = normalized(snapshot)
    base = base_plan["preferred"]
    if base not in ("walk", "observe"):
        raise ValueError("only original native preferences allowed")
    danger = max(body["sleep_pressure"], body["pain"], body["fatigue"])
    harm, source_ids = _similar_harm(state["receipts"], body)
    prediction_error = base_plan.get("prediction", {}).get("prior_samples", 0)
    if type(prediction_error) is not int or prediction_error < 0:
        raise ValueError("invalid prior prediction evidence")
    # Low-evidence uncertainty is diagnostic, not a fabricated probability.
    uncertainty = 1 / (1 + prediction_error)
    signals = {
        "safety": danger,
        "memory": harm,
        "uncertainty": uncertainty,
        "goal": 0.35 if base == "walk" else 0.20,
    }
    # At most two items enter the global workspace at one instant.
    scored = sorted(signals, key=lambda key: (-signals[key], key))
    focus = scored[:CAPACITY]
    if danger >= 0.75 and base == "walk":
        proposed, reason = "observe", "high_body_load"
    elif harm >= 0.5 and source_ids and base == "walk":
        proposed, reason = "observe", "prior_harm"
    else:
        proposed, reason = base, "base_policy"
    return {
        "schema": SCHEMA,
        "base_preferred": base,
        "preferred": proposed,
        "reason": reason,
        "attention": focus,
        "signals": signals,
        "retrieved_receipt_ids": source_ids,
        "broadcast": {channel: list(focus) for channel in CHANNELS},
        "prior_feedback_count": state["sequence"],
        "scope": "bounded global workspace suggestion; native body protection unchanged",
    }


def record(state, request_id, plan, snapshot, actual, source, prediction_error, harm):
    """Fold exactly one observed *native* outcome back into working memory.

    Caller runs this after the authoritative native receipt, atomically with
    the ExperienceController update. Failed/unresolved cycles MUST NOT call it.
    """
    validate(state)
    if not isinstance(request_id, str) or not request_id or any(
            r["id"] == request_id for r in state["receipts"]):
        raise ValueError("workspace duplicate or invalid event")
    if (not isinstance(source, str) or not source.startswith("native-decision://")
            or actual not in ACTIONS or plan.get("schema") != SCHEMA
            or plan.get("preferred") not in ACTIONS[:2] or
            plan.get("reason") not in ("high_body_load", "prior_harm", "base_policy")):
        raise ValueError("untrusted workspace learning input")
    for number in (prediction_error, harm):
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1:
            raise ValueError("invalid observed prediction error or harm")
    if (not isinstance(plan.get("attention"), list) or
            not 0 < len(plan["attention"]) <= CAPACITY or
            len(set(plan["attention"])) != len(plan["attention"])):
        raise ValueError("invalid plan focus")
    if any(x not in ("safety", "memory", "uncertainty", "goal") for x in plan["attention"]):
        raise ValueError("unknown plan focus")
    if plan.get("broadcast") != {c: plan["attention"] for c in CHANNELS}:
        raise ValueError("inconsistent broadcast payload")
    next_state = deepcopy(state)
    next_state["sequence"] += 1
    next_state["last_focus"] = list(plan["attention"])
    next_state["last_reason"] = plan["reason"]
    next_state["last_broadcast"] = {c: list(plan["attention"]) for c in CHANNELS}
    next_state["receipts"].append({
        "id": request_id, "source": source,
        "before": normalized(snapshot),
        "preferred": plan["preferred"], "actual": actual,
        "harm": float(harm), "prediction_error": float(prediction_error),
        "focus": list(plan["attention"]), "reason": plan["reason"],
    })
    next_state["receipts"] = next_state["receipts"][-MAX_RECEIPTS:]
    validate(next_state)
    return next_state


def summary(state):
    validate(state)
    return {
        "enabled": True,
        "learned_native_cycles": state["sequence"],
        "retained_recent_receipts": len(state["receipts"]),
        "last_attention": list(state["last_focus"]),
        "last_reason": state["last_reason"],
        "global_recipients": list(CHANNELS),
        "applied_to_chatgpt_weights": False,
        "api_calls": 0,
    }
