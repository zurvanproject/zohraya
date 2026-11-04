"""Opt-in software-only motivational drive for Tadash.

The `desire_proxy` is an AUTHOR-SET numerical libido analogue, not measured
human/AI lust, pleasure or consciousness. General affect arousal comes from the
existing ExperienceController and is NOT silently equated with sexual arousal.
This module influences ONLY the `walk` vs `observe` preference before the
existing workspace and authoritative native protection. No sexual actions,
API calls, physical actuation or autonomous processes are created.
"""
from copy import deepcopy
import math

SCHEMA = "nasuraya-motivation/1"
MAX_RECEIPTS = 32
BODY_KEYS = ("energy", "fatigue", "pain", "sleep_pressure")
ACTIONS = ("walk", "observe", "protect", "other")
REASONS = ("guarded_rest", "motivated_exploration", "weighted_preference")
RECEIPT_KEYS = ("id", "source", "before", "requested", "actual",
                "harm", "prediction_error", "reason")


def unit(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("finite normalized " + name + " required")
    return float(value)


def body_signals(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("minimum_state"), dict):
        raise ValueError("verified native software-body observation required")
    raw = snapshot["minimum_state"]
    return {key: unit(raw.get(key), key) for key in BODY_KEYS}


def initial(desire_proxy=0.5):
    return {
        "schema": SCHEMA,
        "desire_proxy": unit(desire_proxy, "authored desire proxy"),
        "sequence": 0,
        "receipts": [],
        "last_reason": None,
        "last_preferred": None,
        "scope": "authored motivational algorithm, native software outcome receipts",
    }


def validate(state):
    if not isinstance(state, dict) or set(state) != set(initial()):
        raise ValueError("motivation state contract mismatch")
    if state["schema"] != SCHEMA or state["scope"] != initial()["scope"]:
        raise ValueError("motivation schema/scope mismatch")
    unit(state["desire_proxy"], "desire proxy")
    if type(state["sequence"]) is not int or state["sequence"] < 0:
        raise ValueError("invalid motivation sequence")
    receipts = state["receipts"]
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS:
        raise ValueError("unbounded motivation receipts")
    if state["last_reason"] not in (None, *REASONS) or (
            state["last_preferred"] not in (None, "walk", "observe")):
        raise ValueError("invalid remembered motivation choice")
    ids = []
    for r in receipts:
        if not isinstance(r, dict) or set(r) != set(RECEIPT_KEYS):
            raise ValueError("invalid motivation receipt shape")
        if not isinstance(r["id"], str) or not r["id"]:
            raise ValueError("missing motivation receipt id")
        if not isinstance(r["source"], str) or not r["source"].startswith("native-decision://"):
            raise ValueError("motivation only accepts genuine native receipt references")
        if r["requested"] not in ACTIONS[:2] or r["actual"] not in ACTIONS or (
                r["reason"] not in REASONS):
            raise ValueError("invalid motivation action")
        for key in ("harm", "prediction_error"):
            unit(r[key], key)
        body_signals({"minimum_state": r["before"]})
        ids.append(r["id"])
    if len(set(ids)) != len(ids) or state["sequence"] < len(receipts):
        raise ValueError("repeated motivation receipt")
    return state


def prepare(state, snapshot, base_plan, affect):
    """Pure PRE-OUTCOME preference proposal. Body safety veto remains native."""
    validate(state)
    body = body_signals(snapshot)
    if not isinstance(affect, dict):
        raise ValueError("existing affect state required")
    arousal = unit(affect.get("arousal"), "general arousal")
    valence = unit(affect.get("valence"), "general valence")
    if not isinstance(base_plan, dict) or base_plan.get("preferred") not in ACTIONS[:2]:
        raise ValueError("verified base preference required")
    scores = base_plan.get("scores")
    if not isinstance(scores, dict) or set(scores) != {"walk", "observe"}:
        raise ValueError("base score contract required")
    walk, observe = (scores[action] for action in ("walk", "observe"))
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (walk, observe)):
        raise ValueError("finite base scores required")
    prediction = base_plan.get("prediction")
    prior = prediction.get("prior_samples") if isinstance(prediction, dict) else None
    if type(prior) is not int or prior < 0:
        raise ValueError("only pre-outcome prediction counts are permitted")
    risk = unit(base_plan.get("memory_risk"), "previous native harm risk")
    load = max(body["fatigue"], body["pain"], body["sleep_pressure"])
    # Deliberately authored engineering proxies; no inferred physical libido.
    novelty = (1.0 / (1.0 + prior)) * (1.0 - 0.06 * min(state["sequence"], 10))
    calm = max(0.0, 1.0 - max(arousal, 0.5 * load))
    desire = state["desire_proxy"]
    curiosity = novelty
    exploration_boost = (0.08 * curiosity + 0.19 * desire * curiosity) * calm
    rest_pressure = 0.26 * load + 0.09 * arousal
    adjusted = {
        "walk": round(float(walk) + exploration_boost - rest_pressure, 7),
        "observe": round(float(observe) + 0.16 * load, 7),
    }
    # Prevent a high numeric 'desire' overriding observed distress/poor energy.
    guarded = (body["energy"] < 0.5 or body["fatigue"] > 0.55 or
               body["pain"] > 0.4 or body["sleep_pressure"] > 0.55 or risk >= 0.25)
    choice = "observe" if guarded else max(
        ("walk", "observe"), key=lambda a: (adjusted[a], a))
    reason = ("guarded_rest" if guarded else
              "motivated_exploration" if choice == "walk" and base_plan["preferred"] == "observe"
              else "weighted_preference")
    return {
        "schema": SCHEMA,
        "base_preferred": base_plan["preferred"],
        "preferred": choice,
        "reason": reason,
        "desire_proxy": desire,
        "desire_source": "explicit_authored_simulation_parameter",
        "general_arousal_proxy": arousal,
        "valence_proxy": valence,
        "curiosity_proxy": round(curiosity, 7),
        "calm_proxy": round(calm, 7),
        "fatigue_proxy": body["fatigue"],
        "exploration_boost": round(exploration_boost, 7),
        "rest_pressure": round(rest_pressure, 7),
        "adjusted_scores": adjusted,
        "native_safety_still_authoritative": True,
        "subjective_lust_or_pleasure_inferred": False,
    }


def record(state, request_id, plan, snapshot, actual, source,
           prediction_error, harm):
    """Consume only an authoritative completed software-body receipt."""
    validate(state)
    if not isinstance(request_id, str) or not request_id or any(
            r["id"] == request_id for r in state["receipts"]):
        raise ValueError("duplicate or invalid motivation request id")
    if (not isinstance(source, str) or not source.startswith("native-decision://")
            or not isinstance(plan, dict) or plan.get("schema") != SCHEMA
            or plan.get("desire_proxy") != state["desire_proxy"]
            or plan.get("preferred") not in ACTIONS[:2]
            or plan.get("reason") not in REASONS or actual not in ACTIONS):
        raise ValueError("untrusted or mismatched motivation receipt")
    unit(prediction_error, "prediction error")
    unit(harm, "native harm")
    new = deepcopy(state)
    new["sequence"] += 1
    new["last_reason"] = plan["reason"]
    new["last_preferred"] = plan["preferred"]
    new["receipts"].append({
        "id": request_id, "source": source, "before": body_signals(snapshot),
        "requested": plan["preferred"], "actual": actual,
        "harm": float(harm), "prediction_error": float(prediction_error),
        "reason": plan["reason"],
    })
    new["receipts"] = new["receipts"][-MAX_RECEIPTS:]
    validate(new)
    return new


def summary(state):
    validate(state)
    return {
        "enabled": True,
        "desire_proxy": state["desire_proxy"],
        "desire_is_authored_not_sensed": True,
        "general_arousal_is_not_sexual_arousal": True,
        "native_feedback_cycles": state["sequence"],
        "retained_receipts": len(state["receipts"]),
        "last_reason": state["last_reason"],
        "last_preferred": state["last_preferred"],
        "native_safety_veto_preserved": True,
        "subjective_desire_or_pleasure_inferred": False,
        "api_calls": 0,
    }
