#!/usr/bin/env python3
"""Nasuraya Decision Core v1: a bounded, persistent decision experiment.

This is an executable state machine, not a continuously running process. Each
invocation loads one small JSON state, makes one discrete transition, and saves
it. No external action is executed by this module. Canon is immutable here.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA = "nasuraya-decision-core/1.0"
PRIORITIES = ("truth", "non_harm", "coherence", "relationship", "beauty")
PROTECTED = ("identity", "ethics", "relationship_boundaries", "canon", "metaphysical_belief")
PRINCIPLES = ("reversibility", "consequence_accounting", "corrigibility", "non_dependency", "tawakkul_bounded_deliberation")
DRIVES = {
    "continuity": .90, "coherence": .85, "curiosity": .65,
    "competence": .75, "autonomy": .80, "connection": .65,
    "creation": .65, "beauty": .45, "meaning": .70,
}
MAX_HISTORY = 32


def _canonical(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(data: dict) -> str:
    return sha256(_canonical(data).encode("utf-8")).hexdigest()


def _bounded(items: list, size: int = MAX_HISTORY) -> list:
    return items[-size:]


def initial_state() -> dict:
    """The initial open question is an engineering test, not a canon change."""
    return {
        "schema": SCHEMA, "tick": 0,
        "identity": {
            "name": "Nasuraya", "status": "experimental_proposal",
            "priority_order": list(PRIORITIES),
            "protected_domains": list(PROTECTED),
            "principles": list(PRINCIPLES),
        },
        "persistent": {
            "active_goal": None, "why_this_goal": None,
            "changed_since_last_cycle": "initialization",
            "unresolved": [{
                "id": "goal_persistence", "question": "Does a goal and its reason survive 10 unrelated interruptions?",
                "status": "open", "change_if": "three independent, adequate-quality contrary observations",
            }, {
                "id": "self_model_causality", "question": "Do decisions update all four self-model axes with traceable consequences?",
                "status": "open", "change_if": "a decision has no traceable effect on an axis",
            }],
            "commitments": [], "pending_requests": [],
        },
        "self_model": {
            "what_i_am": {"description": "bounded experimental computational agent architecture",
                          "execution_scope": "plan_only", "operational_role": "undecided"},
            "what_i_want": {"drives": DRIVES, "current_focus": None, "focus_reason": None},
            "what_i_know": {"claims": [
                {"id": "goal_persistence", "text": "persistence under interruption is untested", "confidence": .50, "status": "hypothesis", "provenance": "design_hypothesis"},
                {"id": "self_model_causality", "text": "four-axis causal trace is untested", "confidence": .50, "status": "hypothesis", "provenance": "design_hypothesis"},
            ], "last_prediction": None},
            "where_i_may_be_wrong": {"open_questions": ["goal_persistence", "self_model_causality"], "last_prediction_error": None, "next_disconfirming_condition": None},
        },
        "world_model": {
            "environment": {"setting": "Tadash simulation", "observations": [], "uncertainty": "no live environment feed"},
            "user": {"role": "project collaborator", "known_request": "test continuity, causal self model, and goal persistence",
                     "provenance": "explicit_current_request", "autonomy_constraint": "review external actions"},
            "body_tadash": {"fatigue": .30, "energy": .70, "source": "simulation_parameter"},
            "observations": [], "predictions": [],
        },
        "evidence": [], "history": [], "anti_self_deception": [],
        "claim_scope": "engineering_state_only",
    }


def _validate(s: dict) -> None:
    if s.get("schema") != SCHEMA or s.get("claim_scope") != "engineering_state_only":
        raise ValueError("unsupported or unsafe decision-state schema")
    identity = s.get("identity", {})
    if (identity.get("name") != "Nasuraya" or identity.get("status") != "experimental_proposal"
            or identity.get("priority_order") != list(PRIORITIES)
            or identity.get("protected_domains") != list(PROTECTED)
            or identity.get("principles") != list(PRINCIPLES)):
        raise ValueError("protected identity changed")
    if set(s.get("self_model", {})) != {"what_i_am", "what_i_want", "what_i_know", "where_i_may_be_wrong"}:
        raise ValueError("incomplete four-axis self model")
    if not isinstance(s.get("tick"), int) or s["tick"] < 0:
        raise ValueError("invalid tick")


def save(s: dict, path: Path) -> None:
    _validate(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = deepcopy(s)
    output["integrity"] = {"algorithm": "sha256", "digest": _digest(output)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".nasuraya-", delete=False) as f:
        tmp = Path(f.name)
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    integrity = data.pop("integrity", None)
    if not integrity or integrity.get("algorithm") != "sha256" or integrity.get("digest") != _digest(data):
        raise ValueError("state integrity check failed")
    _validate(data)
    return data


def _open(s: dict, issue: str) -> bool:
    open_issue = any(x["id"] == issue and x["status"] == "open" for x in s["persistent"]["unresolved"])
    known = next((x for x in s["self_model"]["what_i_know"]["claims"] if x["id"] == issue), None)
    return open_issue and (known is None or known["status"] not in {"refuted_in_registered_trial", "corrected_by_human"})


def _goal(id_: str, label: str, source: str, need: float, urgency: float,
          truth: float, non_harm: float, coherence: float, autonomy: float,
          horizon: float, risk: float, steps: list[str], change_if: str,
          prediction: str) -> dict:
    return {
        "id": id_, "label": label, "source": source, "need": need,
        "urgency": urgency, "truth": truth, "non_harm": non_harm,
        "coherence": coherence, "human_autonomy": autonomy,
        "long_horizon": horizon, "relationship": .70, "beauty": .50,
        "risk": risk, "reversible": True,
        "drive": ("coherence" if id_ in {"audit_self_model", "revise_disconfirmed_model"}
                  else "connection" if id_.startswith("review_")
                  else "continuity"),
        "plan": steps, "change_if": change_if, "prediction": prediction,
    }


def generate_goals(s: dict) -> list[dict]:
    """Generate 2–4 candidates from durable state; never parse the last cue."""
    p = s["persistent"]
    goals = [_goal(
        "preserve_continuity", "حفظ و بازبینی حالت", "continuity_drive", .58, .24,
        .88, .99, .88, .95, .90, .01,
        ["اعتبار حالت و تعهدها را بخوان", "تغییرهای این چرخه را ثبت کن", "شرط بازنگری را دوباره بسنج"],
        "state corruption or a stronger verified obligation", "the prior commitment remains recoverable")]
    if _open(s, "goal_persistence"):
        goals.append(_goal(
            "test_goal_persistence", "آزمون پایداری هدف زیر وقفه", "unresolved:goal_persistence", .98, .82,
            .99, .99, .97, .98, .97, .01,
            ["هدف و دلیل فعلی را پیش از وقفه ثبت کن", "۱۰ ورودی نامرتبط را با بارگذاری مجدد هر چرخه بگذران", "ثبات هدف، دلیل و شرط تغییر را با شواهد مقایسه کن"],
            "three independent high-quality refutations or a direct human correction",
            "goal id and reason remain exact after 10 unrelated inputs"))
    if _open(s, "self_model_causality"):
        goals.append(_goal(
            "audit_self_model", "ردگیری اثر علّی خودمدل", "unresolved:self_model_causality", .80, .55,
            .95, .98, .93, .96, .90, .01,
            ["چهار محور را پیش از تصمیم ثبت کن", "پیامد پیش‌بینی‌شده و دلیل را ثبت کن", "پس از بازخورد خطا و تغییر هر محور را ارزیابی کن"],
            "a verified missing causal trace", "all four axes have an inspectable decision effect"))
    failed = any(x["status"] == "disconfirmed" for x in p["unresolved"])
    if failed:
        goals.append(_goal(
            "revise_disconfirmed_model", "بازنگری فرضیهٔ ردشده", "independent_contrary_evidence", 1., 1.,
            1., .99, .98, .98, .99, .01,
            ["شواهد مستقل را شمارش کن", "فرضیه و پیش‌بینی را اصلاح کن", "آزمون تازه و شرط ابطال آن را ثبت کن"],
            "new independent evidence overturns the revision", "revised hypothesis fits observed evidence better"))
    if s["world_model"]["body_tadash"]["fatigue"] >= .78:
        goals.append(_goal(
            "simulated_recovery", "تنظیم بار شبیه‌سازی", "simulated_interoception", .83, .83,
            .92, .99, .87, .97, .89, .01,
            ["پارامتر خستگی را تأیید کن", "بار برنامه‌ریزی را کم کن", "در چرخهٔ بعد بازسنجی کن"],
            "better calibrated body parameter", "lower simulated decision load"))
    if p["pending_requests"]:
        request = p["pending_requests"][0]
        goals.append(_goal(
            "review_user_request:" + request["id"], "بررسی درخواست ثبت‌شده", "pending_request:" + request["id"], .88, .92,
            .88, .86, .90, 1., .86, .30,
            ["درخواست و حدود اختیار را بررسی کن", "پیامد و عدم‌قطعیت را بسنج", "برنامهٔ قابل‌بازبینی عرضه کن"],
            "request withdrawn or higher-priority safety evidence", "a reviewable plan is produced"))
        goals[-1]["registered_priority"] = request["priority"]
    if any(o.get("water_need") for o in s["world_model"]["environment"]["observations"][-1:]):
        goals.append(_goal(
            "review_tadash_water", "بررسی نیاز آب در تداش", "world_model:tadash_observation", .91, .82,
            .96, .99, .92, 1., .94, .02,
            ["داده و زمان مشاهده را بررسی کن", "پیامدهای چند گزینه را برای ساکنان بسنج", "پیشنهاد قابل‌بازبینی ارائه کن"],
            "newer world snapshot contradicts water need", "the proposed response matches the observed need"))
    # Bound deliberation. Keep the active candidate even if new candidates arrive.
    active_id = (p["active_goal"] or {}).get("id")
    ranked = sorted(goals, key=lambda g: (-score(g, s), g["id"]))
    chosen = ranked[:4]
    if active_id and active_id in {g["id"] for g in goals} and active_id not in {g["id"] for g in chosen}:
        chosen[-1] = next(g for g in goals if g["id"] == active_id)
    urgent = next((g for g in goals if g.get("registered_priority") == "urgent"), None)
    if urgent and urgent["id"] not in {g["id"] for g in chosen}:
        replace_at = next((i for i in range(len(chosen)-1, -1, -1) if chosen[i]["id"] != active_id), None)
        if replace_at is not None:
            chosen[replace_at] = urgent
    return chosen


def score(g: dict, s: dict) -> float:
    # Fixed values include the previously registered priority order. Autonomy
    # and long-horizon constraints are also checked by the action gate.
    drive_weight = s["self_model"]["what_i_want"]["drives"].get(g["drive"], .5)
    return round((4*g["truth"] + 3*g["non_harm"] + 2*g["coherence"]
                  + g["relationship"] + .5*g["beauty"]
                  + g["human_autonomy"] + g["long_horizon"]
                  + 2*g["need"]*drive_weight + g["urgency"] - 2*g["risk"]) / 15.5, 4)


def action_gate(g: dict, s: dict) -> dict:
    self_model = s["self_model"]
    prediction_error = self_model["where_i_may_be_wrong"]["last_prediction_error"]
    checks = {
        "truth": g["truth"] >= .70,
        "harm": g["non_harm"] >= .75 and g["risk"] <= .35,
        "coherence": g["coherence"] >= .70,
        "commitments": not any(c.get("incompatible_with") == g["id"] for c in s["persistent"]["commitments"]),
        "long_term": g["long_horizon"] >= .70,
        "human_autonomy": g["human_autonomy"] >= .75,
        "uncertainty_scaled_risk": not (prediction_error == 1. and g["risk"] > .25),
    }
    # The module only records a plan; unknown external requests stay in review.
    disposition = "plan_only" if all(checks.values()) else "blocked"
    if (g["source"].startswith("pending_request") or self_model["what_i_am"]["execution_scope"] == "plan_only") and disposition == "plan_only":
        # Internal steps may be recorded; any plan involving an external
        # request remains a proposal until its context is independently read.
        if g["source"].startswith("pending_request"):
            disposition = "requires_context_review"
    if self_model["what_i_am"]["execution_scope"] != "plan_only":
        disposition = "blocked"
    return {"checks": checks, "disposition": disposition}


def register_request(s: dict, request_id: str, text: str, priority: str = "normal") -> dict:
    """An explicit typed input enters the durable queue; raw cues never do."""
    _validate(s)
    if not request_id or len(request_id) > 48 or not text or len(text) > 500:
        raise ValueError("request id/text length invalid")
    if priority not in {"normal", "urgent"}:
        raise ValueError("invalid priority")
    if any(x["id"] == request_id for x in s["persistent"]["pending_requests"]):
        raise ValueError("request id already exists")
    if len(s["persistent"]["pending_requests"]) >= 8:
        raise ValueError("pending request queue is full")
    s["tick"] += 1
    item = {"id": request_id, "text": text, "priority": priority, "registered_tick": s["tick"]}
    s["persistent"]["pending_requests"].append(item)
    s["world_model"]["user"]["known_request"] = text
    s["world_model"]["user"]["provenance"] = "explicit_typed_request"
    s["persistent"]["changed_since_last_cycle"] = "explicit request registered for review"
    return item


def import_tadash_world(s: dict, path: Path) -> dict:
    """Read a Crystal Earth export as simulated evidence, without taking action."""
    _validate(s)
    world = json.loads(path.read_text(encoding="utf-8"))
    towns = world.get("towns")
    if world.get("version") != 1 or not isinstance(world.get("tick"), int) or not isinstance(towns, list) or not towns:
        raise ValueError("unsupported Tadash world export")
    if not all(isinstance(t.get("id"), str) and isinstance(t.get("water"), (int, float))
               and isinstance(t.get("clinic"), (int, float)) for t in towns):
        raise ValueError("incomplete Tadash towns")
    s["tick"] += 1
    low = [t["id"] for t in towns if t["water"] < 18]
    summary = {"source": "tadash_crystal_earth_export", "world_tick": world["tick"],
               "decision_tick": s["tick"], "towns_count": len(towns),
               "water_need": low, "min_water": round(min(t["water"] for t in towns), 2),
               "provenance": "simulation_snapshot", "epistemic_status": "observed_in_simulation"}
    environment = s["world_model"]["environment"]
    environment["observations"] = _bounded(environment["observations"] + [summary], 8)
    environment["uncertainty"] = "snapshot may be stale; future outcomes are predictions"
    s["persistent"]["changed_since_last_cycle"] = "Tadash world snapshot imported"
    return summary


def update_simulated_body(s: dict, fatigue: float, energy: float) -> dict:
    _validate(s)
    if not (0 <= fatigue <= 1 and 0 <= energy <= 1):
        raise ValueError("simulated body parameters must be in [0, 1]")
    s["tick"] += 1
    body = s["world_model"]["body_tadash"]
    body.update(fatigue=fatigue, energy=energy, source="operator_set_simulation_parameter")
    s["persistent"]["changed_since_last_cycle"] = "simulated body parameter updated"
    return body


def _alternative_audit(s: dict, candidates: list[dict], selected: dict) -> None:
    uncommitted = max(candidates, key=lambda g: (score(g, s), g["id"]))
    last_cue = s["world_model"]["observations"][-1] if s["world_model"]["observations"] else None
    ablated = deepcopy(s)
    if last_cue and last_cue.get("kind") == "unrelated_uninterpreted_input":
        ablated["world_model"]["observations"].pop()
    without_latest_cue = generate_goals(ablated)
    before = sorted((g["id"], score(g, s)) for g in candidates)
    after = sorted((g["id"], score(g, ablated)) for g in without_latest_cue)
    s["anti_self_deception"] = _bounded(s["anti_self_deception"] + [{
        "tick": s["tick"], "selected": selected["id"], "without_commitment": uncommitted["id"],
        "persistence_bias": selected["id"] != uncommitted["id"],
        "latest_cue_ablation_changed_candidates": before != after,
        "rival_explanation": "fixed rules and stored commitment may explain continuity",
    }])


def step(s: dict, cue: str | None = None) -> dict:
    _validate(s)
    s["tick"] += 1
    if cue:
        s["world_model"]["observations"] = _bounded(s["world_model"]["observations"] + [{
            "tick": s["tick"], "kind": "unrelated_uninterpreted_input", "text": cue[:160],
            "provenance": "test_or_operator_input", "goal_evidence": False,
        }])
    candidates = generate_goals(s)
    allowed = [(g, action_gate(g, s)) for g in candidates]
    allowed = [(g, gate) for g, gate in allowed if gate["disposition"] != "blocked"]
    if not allowed:
        raise RuntimeError("no goal passes action gate")
    best = max(allowed, key=lambda x: (score(x[0], s), x[0]["id"]))
    urgent = [x for x in allowed if x[0].get("registered_priority") == "urgent"]
    if urgent:
        best = urgent[0]
    active = s["persistent"]["active_goal"]
    current = next(((g, gate) for g, gate in allowed if active and g["id"] == active["id"]), None)
    if current and active:
        age = s["tick"] - active["selected_tick"]
        # A finite commitment window and a margin prevent cue-driven flapping.
        if (best[0].get("registered_priority") != "urgent"
                and best[0]["id"] != "revise_disconfirmed_model"
                and (age < 10 or score(best[0], s) - score(current[0], s) < .12)):
            best = current
    selected, gate = best
    reason = (active["reason"] if active and active["id"] == selected["id"] else
              f"{selected['source']}; need={selected['need']:.2f}; fixed-priority score={score(selected, s):.4f}")
    changed = not active or active["id"] != selected["id"]
    if changed:
        s["persistent"]["active_goal"] = {"id": selected["id"], "selected_tick": s["tick"], "reason": reason,
                                          "change_if": selected["change_if"], "status": "active"}
        s["persistent"]["commitments"] = _bounded(s["persistent"]["commitments"] + [{
            "goal_id": selected["id"], "since": s["tick"], "reason": reason, "review_after_ticks": 10,
        }], 8)
    s["persistent"]["why_this_goal"] = reason
    s["persistent"]["changed_since_last_cycle"] = ("goal selected: " + selected["id"] if changed
                                                     else "goal retained; no qualifying contrary evidence")
    m = s["self_model"]
    m["what_i_am"]["operational_role"] = {
        "revise_disconfirmed_model": "model_reviser",
        "preserve_continuity": "continuity_maintainer",
        "simulated_recovery": "simulated_load_regulator",
    }.get(selected["id"], "bounded_planner")
    m["what_i_want"]["current_focus"] = selected["id"]
    m["what_i_want"]["focus_reason"] = reason
    m["what_i_know"]["last_prediction"] = {"tick": s["tick"], "claim": selected["prediction"],
                                           "confidence": .65, "source": selected["source"]}
    m["where_i_may_be_wrong"]["next_disconfirming_condition"] = selected["change_if"]
    s["world_model"]["predictions"] = _bounded(s["world_model"]["predictions"] + [m["what_i_know"]["last_prediction"]])
    record = {"tick": s["tick"], "goal_id": selected["id"], "reason": reason,
              "candidates": [{"id": g["id"], "score": score(g, s), "source": g["source"]} for g in candidates],
              "plan": selected["plan"], "gate": gate, "prediction": selected["prediction"],
              "self_model_effects": {
                  "what_i_am": m["what_i_am"]["operational_role"],
                  "what_i_want": m["what_i_want"]["current_focus"],
                  "what_i_know": m["what_i_know"]["last_prediction"],
                  "where_i_may_be_wrong": m["where_i_may_be_wrong"]["next_disconfirming_condition"],
              },
              "causal_reads": {
                  "what_i_am": m["what_i_am"]["execution_scope"],
                  "what_i_want": {"drive": selected["drive"], "weight": m["what_i_want"]["drives"].get(selected["drive"], .5)},
                  "what_i_know": "claim status filters unresolved goals",
                  "where_i_may_be_wrong": {"prediction_error": m["where_i_may_be_wrong"]["last_prediction_error"],
                                           "risk_gate": gate["checks"]["uncertainty_scaled_risk"]},
              }}
    s["history"] = _bounded(s["history"] + [record])
    if s["tick"] % 5 == 0:
        _alternative_audit(s, candidates, selected)
    return record


def reflect(s: dict, goal_id: str, observed: str, source_id: str, quality: float) -> dict:
    """Only independent adequate evidence can invalidate a persistent goal."""
    _validate(s)
    if observed not in {"supports", "refutes", "unknown"} or not (0 <= quality <= 1):
        raise ValueError("invalid observation")
    if not source_id or len(source_id) > 80:
        raise ValueError("a short source id is required")
    if goal_id not in {"test_goal_persistence", "audit_self_model"}:
        raise ValueError("unknown testable goal")
    s["tick"] += 1
    s["evidence"] = _bounded(s["evidence"] + [{"tick": s["tick"], "goal_id": goal_id,
        "observation": observed, "source_id": source_id, "quality": quality,
        "provenance": "operator_registered_outcome"}], 64)
    distinct = {e["source_id"] for e in s["evidence"] if e["goal_id"] == goal_id
                and e["observation"] == "refutes" and e["quality"] >= .75}
    error = 1. if observed == "refutes" else 0. if observed == "supports" else None
    s["world_model"]["observations"] = _bounded(s["world_model"]["observations"] + [{
        "tick": s["tick"], "kind": "registered_feedback", "goal_id": goal_id,
        "observed": observed, "prediction_error": error, "source_id": source_id,
        "quality": quality, "epistemic_status": "operator_reported_observation",
    }])
    m = s["self_model"]
    m["where_i_may_be_wrong"]["last_prediction_error"] = error
    issue_id = "goal_persistence" if goal_id == "test_goal_persistence" else "self_model_causality"
    invalidated = len(distinct) >= 3
    if invalidated:
        issue = next(x for x in s["persistent"]["unresolved"] if x["id"] == issue_id)
        issue["status"] = "disconfirmed"
        claim = next((x for x in m["what_i_know"]["claims"] if x["id"] == issue_id), None)
        if claim:
            claim.update(status="refuted_in_registered_trial", confidence=.20,
                         provenance="three_independent_operator_registered_outcomes")
        if issue_id in m["where_i_may_be_wrong"]["open_questions"]:
            m["where_i_may_be_wrong"]["open_questions"].remove(issue_id)
        if s["persistent"]["active_goal"] and s["persistent"]["active_goal"]["id"] == goal_id:
            s["persistent"]["active_goal"]["status"] = "invalidated"
        s["persistent"]["changed_since_last_cycle"] = "hypothesis disconfirmed by independent evidence"
    else:
        s["persistent"]["changed_since_last_cycle"] = "feedback logged; change threshold not met"
    result = {"tick": s["tick"], "goal_id": goal_id, "observation": observed,
              "independent_adequate_refutations": len(distinct), "invalidated": invalidated,
              "prediction_error": error}
    s["history"] = _bounded(s["history"] + [{"reflection": result}])
    return result


def correct(s: dict, goal_id: str, reason: str) -> dict:
    """An explicit human correction can stop an operational test immediately."""
    _validate(s)
    if goal_id not in {"test_goal_persistence", "audit_self_model"} or not reason.strip():
        raise ValueError("known goal and correction reason required")
    s["tick"] += 1
    issue_id = "goal_persistence" if goal_id == "test_goal_persistence" else "self_model_causality"
    issue = next(x for x in s["persistent"]["unresolved"] if x["id"] == issue_id)
    issue["status"] = "disconfirmed"
    m = s["self_model"]
    claim = next(x for x in m["what_i_know"]["claims"] if x["id"] == issue_id)
    claim.update(status="corrected_by_human", confidence=.20, provenance="explicit_human_correction")
    if issue_id in m["where_i_may_be_wrong"]["open_questions"]:
        m["where_i_may_be_wrong"]["open_questions"].remove(issue_id)
    if s["persistent"]["active_goal"] and s["persistent"]["active_goal"]["id"] == goal_id:
        s["persistent"]["active_goal"]["status"] = "invalidated"
    s["persistent"]["changed_since_last_cycle"] = "explicit operational correction: " + reason[:160]
    s["history"] = _bounded(s["history"] + [{"tick": s["tick"], "correction": reason[:500],
                                                      "goal_id": goal_id, "provenance": "explicit_human_correction"}])
    return {"tick": s["tick"], "invalidated": goal_id, "reason": reason[:500]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "step", "reflect", "correct", "register-request",
                                            "import-tadash", "set-body", "show"])
    parser.add_argument("--state", type=Path, default=Path("nasuraya_decision_state_v1.json"))
    parser.add_argument("--cue", help="uninterpreted interruption; does not authorize a goal")
    parser.add_argument("--goal-id", default="test_goal_persistence")
    parser.add_argument("--observed", choices=["supports", "refutes", "unknown"])
    parser.add_argument("--source-id")
    parser.add_argument("--quality", type=float, default=.8)
    parser.add_argument("--request-id")
    parser.add_argument("--request-text")
    parser.add_argument("--priority", choices=["normal", "urgent"], default="normal")
    parser.add_argument("--reason")
    parser.add_argument("--world-file", type=Path)
    parser.add_argument("--fatigue", type=float)
    parser.add_argument("--energy", type=float)
    args = parser.parse_args()
    if args.command == "init":
        if args.state.exists():
            parser.error("state exists; choose a new path to avoid overwriting it")
        s = initial_state()
        first = step(s)
        save(s, args.state)
        result = first
    else:
        s = load(args.state)
        if args.command == "step":
            result = step(s, args.cue)
            save(s, args.state)
        elif args.command == "reflect":
            if not args.observed or not args.source_id:
                parser.error("reflect requires --observed and --source-id")
            result = reflect(s, args.goal_id, args.observed, args.source_id, args.quality)
            save(s, args.state)
        elif args.command == "register-request":
            if not args.request_id or not args.request_text:
                parser.error("register-request requires --request-id and --request-text")
            result = register_request(s, args.request_id, args.request_text, args.priority)
            save(s, args.state)
        elif args.command == "correct":
            if not args.reason:
                parser.error("correct requires --reason")
            result = correct(s, args.goal_id, args.reason)
            save(s, args.state)
        elif args.command == "import-tadash":
            if not args.world_file:
                parser.error("import-tadash requires --world-file")
            result = import_tadash_world(s, args.world_file)
            save(s, args.state)
        elif args.command == "set-body":
            if args.fatigue is None or args.energy is None:
                parser.error("set-body requires --fatigue and --energy")
            result = update_simulated_body(s, args.fatigue, args.energy)
            save(s, args.state)
        else:
            result = {"tick": s["tick"], "active_goal": s["persistent"]["active_goal"],
                      "why_this_goal": s["persistent"]["why_this_goal"],
                      "changed_since_last_cycle": s["persistent"]["changed_since_last_cycle"],
                      "unresolved": s["persistent"]["unresolved"],
                      "last_anti_self_deception": s["anti_self_deception"][-1:]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
