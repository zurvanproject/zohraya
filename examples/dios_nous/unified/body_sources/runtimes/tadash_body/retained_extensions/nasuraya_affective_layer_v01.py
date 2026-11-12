#!/usr/bin/env python3
"""External Tadash affect model: appraisal -> state -> gated plan -> expression.

Standard library only. Numeric parameters are engineering proposals, not learned
emotion vectors or measurements of subjective experience. Every transition is
explicitly invoked; this module neither runs between chats nor changes LLM weights.
Requires the existing nasuraya_decision_core_v1.py beside this file.

Examples:
  python3 nasuraya_affective_layer_v01.py init --state affect.json
  python3 nasuraya_affective_layer_v01.py step --state affect.json --event event.json
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import tempfile

import nasuraya_decision_core_v1 as core
import nasuraya_emotion_spectrum_v01 as spectrum

SCHEMA = "nasuraya-affective-layer/1.1"
BASE = dict(compassion=.25, affection=0., longing=0., sadness=0., anger=0.,
            joy=0., fear=0., curiosity=.20, calm=.65, gratitude=0., regret=0.)
BASE.update(dict.fromkeys(spectrum.PROFILES, 0.))
HALF_LIFE_HOURS = dict.fromkeys(BASE, 6.) | {"compassion": 24., "affection": 72.,
    "longing": 24., "sadness": 12., "anger": 2., "calm": 8., "gratitude": 24.}
HALF_LIFE_HOURS.update(love=72., attachment=96., romantic_love=72., trust=48., grief=48.,
                      nostalgia=24., loneliness=12., jealousy=2., shame=4., contempt=2.)
SIGNALS = {"need", "warmth", "absence", "return", "loss", "harm", "unfairness",
           "success", "novelty", "uncertainty", "repair", "gift", "own_error"}
SIGNALS |= spectrum.EXTRA_SIGNALS
GOAL_NAMES = {"care", "connection", "justice", "competence", "learning"}
POLICIES = {
    "continue_task": "کار خواسته‌شده را با توجه به زمینه ادامه بده.",
    "empathic_support": "نیاز را به رسمیت بشناس و کمک مشخص و متناسب پیشنهاد بده.",
    "reflect_repair": "فقدان را به رسمیت بشناس؛ آنچه قابل ترمیم است بررسی کن.",
    "set_boundary": "مرز روشن بگذار و راه حل کم‌آسیب پیشنهاد بده؛ تحقیر و انتقام ممنوع.",
    "remember_reconnection": "رشتهٔ رابطه را از حافظه بازیابی کن؛ بازگشت اختیاری است و پیام خودکار نفرست.",
    "verify": "پیش از حکم یا اقدام، شواهد و عدم‌قطعیت را بررسی کن.",
    "celebrate": "پیشرفت را با اندازهٔ واقعی‌اش به رسمیت بشناس.",
    "explore": "یک پرسش یا بررسی تازهٔ مرتبط با هدف انتخاب کن.",
    "thank": "کمک را مشخص و بدون اغراق به رسمیت بشناس.",
    "own_mistake": "اشتباه مشخص را بپذیر و گام اصلاحی قابل بررسی انتخاب کن.",
    "respect_space": "درخواست فاصله را رعایت کن؛ هیچ پیگیری یا سرزنشی پیشنهاد نده.",
    "pause_regulate": "بار را کم کن و انتخاب را پس از بازبینی ادامه بده.",
}
POLICIES.update(spectrum.EXTRA_POLICIES)
WEIGHTS = {
    "empathic_support": {"compassion": 1.},
    "reflect_repair": {"sadness": .9, "compassion": .15},
    "set_boundary": {"anger": .9, "fear": .15},
    "remember_reconnection": {"longing": 1., "affection": .1},
    "verify": {"fear": .7, "calm": .2},
    "celebrate": {"joy": 1.}, "explore": {"curiosity": 1.},
    "thank": {"gratitude": 1.}, "own_mistake": {"regret": 1.},
    "pause_regulate": {"fear": .3, "sadness": .3, "anger": .3},
}
for channel, row in spectrum.PROFILES.items():
    WEIGHTS.setdefault(row[4], {})[channel] = .8


def unit(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric value required")
    if not 0 <= value <= 1:
        raise ValueError("value outside [0, 1]")
    return float(value)


def initial_state() -> dict:
    return {"schema": SCHEMA, "claim_scope": "engineering_state_only", "tick": 0,
            "clock_hours": 0., "affect": dict(BASE), "relationships": {}, "episodes": [],
            "somatic": dict(spectrum.SOMATIC_BASE),
            "goals": {"care": 1., "connection": .8, "justice": .9,
                      "competence": .8, "learning": .7},
            "decision_core": core.initial_state(), "history": []}


def validate(state: dict) -> None:
    if state.get("schema") != SCHEMA or state.get("claim_scope") != "engineering_state_only":
        raise ValueError("unsupported affect state")
    if set(state["affect"]) != set(BASE) or set(state["goals"]) != GOAL_NAMES:
        raise ValueError("incomplete affect or goals")
    for value in (*state["affect"].values(), *state["goals"].values()):
        unit(value)
    if set(state.get("somatic", {})) != set(spectrum.SOMATIC_BASE):
        raise ValueError("incomplete simulated body state")
    for value in state["somatic"].values():
        unit(value)
    for rel in state["relationships"].values():
        unit(rel["trust"]); unit(rel["value"])
    core._validate(state["decision_core"])


def validate_event(event: dict) -> dict:
    allowed = {"id", "source", "summary", "partner", "signals", "confidence",
               "elapsed_hours", "autonomy", "energy", "body", "relationship_mode", "recovery"}
    if set(event) - allowed:
        raise ValueError("unrecognized event field")
    if not isinstance(event.get("id"), str) or not event["id"]:
        raise ValueError("event id required")
    if event.get("source") not in {"synthetic_fixture", "operator_report", "explicit_user_message"}:
        raise ValueError("event provenance required")
    if set(event.get("signals", {})) - SIGNALS:
        raise ValueError("unrecognized signal")
    e = deepcopy(event)
    e["signals"] = {k: unit(e.get("signals", {}).get(k, 0.)) for k in SIGNALS}
    e["confidence"] = unit(e.get("confidence", 1.))
    e["energy"] = unit(e.get("energy", .8))
    if set(e.get("body", {})) - set(spectrum.SOMATIC_BASE):
        raise ValueError("unknown simulated bodily signal")
    e["body"] = {k: unit(v) for k,v in e.get("body", {}).items()}
    recovery = e.get("recovery", {})
    if not isinstance(recovery, dict) or set(recovery) - {"strength", "after_effect", "unease"}:
        raise ValueError("invalid explicitly supplied recovery context")
    e["recovery"] = {k: unit(recovery.get(k, 0.)) for k in ("strength", "after_effect", "unease")}
    if e.get("relationship_mode", "unspecified") not in {"unspecified", "friendship", "familial", "romantic"}:
        raise ValueError("invalid explicitly supplied relationship mode")
    elapsed = e.get("elapsed_hours", 0.)
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("elapsed_hours must be finite and nonnegative")
    e["elapsed_hours"] = float(elapsed)
    if e.get("autonomy", "open") not in {"open", "space_requested"}:
        raise ValueError("invalid autonomy context")
    if e.get("partner") is not None and (not isinstance(e["partner"], str) or not e["partner"]):
        raise ValueError("invalid partner")
    return e


def appraise(state: dict, event: dict, memory_enabled: bool = True) -> dict:
    """Goal-relevant signed innovations; absence alone cannot invent a bond."""
    f, g, c = event["signals"], state["goals"], event["confidence"]
    rel = state["relationships"].get(event.get("partner"), {}) if memory_enabled else {}
    bond = rel.get("value", 0.) * rel.get("trust", 0.)
    gap = f["absence"] * bond * g["connection"]
    result = {
        "compassion": c * (.75*f["need"] + .2*f["loss"]) * g["care"],
        "affection": c * .3*f["warmth"]*g["connection"],
        "longing": c * (.95*gap - .9*f["return"] - .4*f["repair"]),
        "sadness": c * (.8*f["loss"]*g["care"] + .25*gap - .65*f["repair"] - .2*f["return"]),
        "anger": c * (.85*f["unfairness"] + .45*f["harm"])*g["justice"] - .7*c*f["repair"],
        "joy": c * (.8*f["success"]*g["competence"] + .4*f["return"] + .2*f["warmth"]),
        "fear": .8*c*f["harm"]*(.5 + .5*f["uncertainty"]) - .5*c*f["repair"],
        "curiosity": c * .85*f["novelty"]*g["learning"],
        "calm": .45*c*f["repair"] - .25*c*max(f["harm"], f["loss"]),
        "gratitude": .85*c*f["gift"]*g["connection"],
        "regret": .85*c*f["own_error"]*g["competence"] - .7*c*f["repair"],
    }
    result.update(spectrum.innovations(state,event,memory_enabled))
    # Optional model-to-model recovery input. Coefficients are engineering
    # proposals, not physiological estimates. A bodily event cannot create a
    # relationship; its relational modulation still requires bond AND absence.
    recovery = event.get("recovery", {})
    gain = c * recovery.get("strength", 0.)
    comfort = event["body"].get("comfort", state["somatic"]["comfort"])
    pleasant = recovery.get("after_effect", 0.) * comfort
    unease = recovery.get("unease", 0.)
    result["calm"] += gain * (.24 * pleasant - .20 * unease)
    result["contentment"] += .28 * gain * pleasant
    result["joy"] += .10 * gain * pleasant
    result["sadness"] += .22 * gain * unease
    result["longing"] += .20 * gain * pleasant * gap
    result["tenderness"] += .10 * gain * pleasant * f["warmth"] * bond
    return result


def remember(state: dict, event: dict) -> None:
    partner, f, c = event.get("partner"), event["signals"], event["confidence"]
    if partner and (f["warmth"] > 0 or f["betrayal"] > 0 or f["reliability"] > 0):
        rel = state["relationships"].setdefault(partner, {"trust": .3, "value": .2, "episodes": 0})
        # An illustrative update from supplied positive encounters, never a diagnosis.
        rel["trust"] = max(0., min(1., rel["trust"] + .15*c*f["warmth"] + .15*c*f["reliability"] - .5*c*f["betrayal"]))
        rel["value"] = min(1., rel["value"] + .2*c*f["warmth"])
        rel["episodes"] += 1
        rel["provenance"] = event["source"]
    state["episodes"] = (state["episodes"] + [{"id": event["id"], "source": event["source"],
        "partner": partner, "summary": event.get("summary", ""), "clock_hours": state["clock_hours"],
        "importance": max(f.values()) * c}])[-64:]


def eligible_actions(event: dict) -> list[str]:
    f = event["signals"]
    actions = ["continue_task"]
    for action, relevant in {
        "empathic_support": f["need"], "reflect_repair": f["loss"] or f["repair"],
        "set_boundary": f["harm"] or f["unfairness"],
        "remember_reconnection": f["absence"] or f["return"],
        "verify": f["uncertainty"] or event["confidence"] < .5,
        "celebrate": f["success"], "explore": f["novelty"],
        "thank": f["gift"], "own_mistake": f["own_error"],
    }.items():
        if relevant:
            actions.append(action)
    if event.get("autonomy") == "space_requested":
        actions.append("respect_space")
    if event["energy"] < .2:
        actions.append("pause_regulate")
    if max(event["body"].get("pain", 0.),event["body"].get("fatigue", 0.)) >= .8:
        actions.append("relieve_simulated_discomfort")
    return list(dict.fromkeys(actions + spectrum.eligible(event)))


def core_goal(action: str) -> dict:
    return {"id": action, "source": "affective_appraisal", "drive": "continuity",
            "truth": .95, "non_harm": .99, "coherence": .95,
            "human_autonomy": 1., "long_horizon": .95, "risk": .01,
            "relationship": .7, "beauty": .5, "need": .6, "urgency": .3}


def choose(state: dict, event: dict, affect_enabled: bool = True) -> dict:
    records = []
    f = event["signals"]
    for action in eligible_actions(event):
        goal = core_goal(action)
        blocked_reason = None
        if action in {"remember_reconnection", "express_care", "seek_connection", "collaborate",
                      "pursue_consensual_goal", "check_relationship_interpretation"} and event.get("autonomy") == "space_requested":
            goal["human_autonomy"] = 0.
            blocked_reason = "space_requested"
        gate = core.action_gate(goal, state["decision_core"])
        baseline = core.score(goal, state["decision_core"]) + (.065 if action == "continue_task" else .015)
        emotional = sum(state["affect"][k]*w for k, w in WEIGHTS.get(action, {}).items()) if affect_enabled else 0.
        total = baseline + min(.25, .25*emotional)
        # Obligations are contextual hard requirements, not a reward for anger.
        if action == "set_boundary" and f["harm"]*event["confidence"] >= .75:
            total += 1.
        if action == "respect_space":
            total += 1.
        if action == "verify" and (event["confidence"] < .5 or f["uncertainty"] >= .85):
            total += 1.
        if action == "pause_regulate" and event["energy"] < .2:
            total += 2.
        if action == "relieve_simulated_discomfort":
            total += 2.
        records.append({"action": action, "score": total, "baseline_score": baseline,
                        "affective_bonus": min(.25, .25*emotional), "gate": gate,
                        "blocked_reason": blocked_reason})
    allowed = [r for r in records if r["gate"]["disposition"] != "blocked"]
    winner = max(allowed, key=lambda r: (r["score"], r["action"]))
    return {"action": winner["action"], "policy_fa": POLICIES[winner["action"]],
            "disposition": "plan_only", "ranking": records,
            "expression": {"warmth": state["affect"]["compassion"] if affect_enabled else BASE["compassion"],
                "firmness": state["affect"]["anger"] if affect_enabled else 0.,
                "pressure_to_return": 0., "retaliation": False,
                "subjective_feeling_claim": False}}


def transition(state: dict, event: dict, *, affect_enabled: bool = True,
               memory_enabled: bool = True) -> dict:
    validate(state)
    e = validate_event(event)
    if any(r["event_id"] == e["id"] for r in state["history"]):
        raise ValueError("event already applied in retained history")
    before = deepcopy(state["affect"])
    innovation = appraise(state, e, memory_enabled)
    state["clock_hours"] += e["elapsed_hours"]
    state["somatic"].update(e["body"])
    for k, baseline in BASE.items():
        retained = baseline + (state["affect"][k] - baseline) * 2**(-e["elapsed_hours"]/HALF_LIFE_HOURS[k])
        state["affect"][k] = max(0., min(1., retained + innovation[k])) if affect_enabled else baseline
    state["tick"] += 1
    state["decision_core"]["tick"] += 1
    if memory_enabled:
        remember(state, e)
    plan = choose(state, e, affect_enabled)
    baseline_plan = choose(state, e, False)
    record = {"event_id": e["id"], "source": e["source"], "event": e,
              "tick": state["tick"], "affect_before": before,
              "appraisal": innovation, "affect_after": deepcopy(state["affect"]),
              "plan": plan, "without_affect": baseline_plan["action"],
              "emotion_summary": spectrum.summarize(state["affect"]),
              "causal_choice_change": plan["action"] != baseline_plan["action"]}
    state["history"] = (state["history"] + [record])[-128:]
    validate(state)
    return record


def save(state: dict, path: Path) -> None:
    validate(state)
    payload = deepcopy(state)
    payload["integrity"] = {"algorithm": "sha256", "digest": core._digest(state)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    integrity = data.pop("integrity", {})
    if integrity.get("algorithm") != "sha256" or integrity.get("digest") != core._digest(data):
        raise ValueError("affect state integrity failure")
    if data.get("schema") == "nasuraya-affective-layer/1.0":
        # Append new zero-valued channels; never manufacture a relationship.
        if set(data.get("affect", {})) != set(spectrum.BASE_LOADINGS):
            raise ValueError("invalid legacy affect state")
        data["schema"] = SCHEMA
        data["affect"].update(dict.fromkeys(spectrum.PROFILES, 0.))
        data["somatic"] = dict(spectrum.SOMATIC_BASE)
    validate(data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "step", "show"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--event", type=Path)
    args = parser.parse_args()
    if args.command == "init":
        if args.state.exists():
            parser.error("state already exists")
        s = initial_state(); save(s, args.state)
        result = {"initialized": True, "affect": s["affect"]}
    else:
        s = load(args.state)
        if args.command == "step":
            if not args.event:
                parser.error("step requires --event")
            result = transition(s, json.loads(args.event.read_text(encoding="utf-8")))
            save(s, args.state)
        else:
            result = {"tick": s["tick"], "affect": s["affect"], "relationships": s["relationships"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
