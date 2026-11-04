"""One auditable Tadash cycle: body -> modeled need -> memory -> decision -> outcome -> learning.

Thin opt-in coordination over the EXISTING ExperienceController, not a new
independent body, policy, memory store, or background agent. All four optional
advisors share one native action intent and one persisted software-body receipt.
This module neither models consciousness nor changes ChatGPT weights.
"""
from pathlib import Path
import json

from reflection_cycle import InterruptedExecution
from .experience import ExperienceController, KEY
from .host import BodyLoop
from . import motivation

SCHEMA = "tadash-unified-receipt-cycle/1"
LAYERS = ("workspace", "motivation", "autonomic_bridge", "neurovisceral")
WINDOW = 32
NEEDS = ("energy_deficit", "fatigue", "pain", "sleep_pressure")


def _controller(loop):
    if not isinstance(loop, BodyLoop):
        raise ValueError("verified locked native BodyLoop required")
    return ExperienceController(loop)


def _counts(state, native):
    return {
        "experience": len(state["episodes"]),
        "workspace": state["workspace"]["sequence"],
        "motivation": state["motivation"]["sequence"],
        "autonomic": state["autonomic_bridge"]["native_feedback_cycles"],
        "neurovisceral": state["neurovisceral"]["completed_cycles"],
        "native": native["completed_cycles"],
    }


def _pairs(receipts):
    return [(r["id"], r["source"]) for r in receipts]


def status(controller):
    """Read a shared state. Detect out-of-band actions and divergent receipts."""
    report = controller.status()
    state, native = report["state"], report["native"]
    missing = [name for name in LAYERS if name not in state]
    if missing:
        return {
            "schema": SCHEMA, "ready": False, "missing": missing,
            "native_completed_cycles": native["completed_cycles"],
            "actions_remaining": native["actions_remaining"],
            "scope": "synthetic software-body, opt-in only",
        }
    counts = _counts(state, native)
    expected = [(e["id"], e["source"]) for e in state["episodes"][-WINDOW:]]
    receipt_match = all(
        _pairs(state[layer]["receipts"]) == expected
        for layer in LAYERS
    )
    origin = native_body_origin = controller.loop.config["initial_checkpoint_sha256"]
    pinned = (
        state["autonomic_bridge"]["original_checkpoint_sha256"] == origin
        and state["neurovisceral"]["initial_native_checkpoint_sha256"] == origin
    )
    valid_flags = all(state["flags"].values())
    synchronized = len(set(counts.values())) == 1 and receipt_match and pinned and valid_flags
    return {
        "schema": SCHEMA, "ready": True, "synchronized": synchronized,
        "completed_cycles": counts["experience"], "counters": counts,
        "recent_receipts_agree": receipt_match,
        "initial_source_pinned": pinned,
        "all_experience_flags_enabled": valid_flags,
        "actions_remaining": native["actions_remaining"],
        "pending_intents": [k for k, v in state["intents"].items() if v["result"] is None],
        "last_receipt_source": expected[-1][1] if expected else None,
        "software_only": True, "physical_actuation": False, "api_calls": 0,
        "subjective_experience_inferred": False,
        "scope": "one native receipt and one ExperienceController state; not a biological or consciousness claim",
    }


def enable(loop, *, desire_proxy=0.5):
    """Activate the four existing layers once, before the first body action.

    Safe to retry when a previous enable stopped mid-way without acting.
    Never silently backfill memory or relabel an old body action as integrated.
    """
    motivation.initial(desire_proxy)  # validate BEFORE any possible mutation
    if loop.config["mode"] != "bounded":
        raise ValueError("bounded software-body mode required")
    native = loop.status()
    exists = loop.engine.db.execute(
        "SELECT value FROM meta WHERE key=?", (KEY,)).fetchone() is not None
    if exists:
        controller = _controller(loop)
        existing = status(controller)
        if existing["ready"]:
            actual = controller.status()["state"]["motivation"]["desire_proxy"]
            if actual != float(desire_proxy):
                raise ValueError("already enabled with another authored desire proxy")
            if not existing["synchronized"]:
                raise InterruptedExecution("unreconciled unified native receipt chain")
            return existing
    else:
        controller = None
    if native["actions_reserved"] or native["unresolved_running"]:
        raise ValueError("unified cycle must be enabled before any native action")
    if controller is not None:
        old = controller.status()["state"]
        if old["intents"] or not all(old["flags"].values()):
            raise ValueError("nonempty experience history or disabled flags cannot be backfilled")
    if controller is None:
        controller = ExperienceController.enable(loop)
    controller.enable_workspace()
    controller.enable_motivation(desire_proxy=desire_proxy)
    controller.enable_autonomic_bridge()
    controller.enable_neurovisceral()
    unified = status(controller)
    if not unified["synchronized"]:
        raise ValueError("unified receipt sources did not align")
    return unified


def _need_proxies(before):
    pressure = {
        "energy_deficit": round(1. - before["energy"], 7),
        "fatigue": round(before["fatigue"], 7),
        "pain": round(before["pain"], 7),
        "sleep_pressure": round(before["sleep_pressure"], 7),
    }
    dominant = max(NEEDS, key=lambda key: pressure[key])
    return {
        "pressure": pressure, "dominant": dominant,
        "interpretation": "descriptive authored need proxies, not a new policy or felt needs",
    }


def step(controller, request_id, *, duration_s=.1):
    """Execute/reconcile one native intent, then present its full causal chain.

    A pending native completion may be reconciled by the SAME request_id.
    Other divergence is blocked. A replay never runs an extra body cycle.
    """
    before = status(controller)
    if not before["ready"]:
        raise ValueError("enable the unified cycle first")
    if not before["synchronized"] and request_id not in before["pending_intents"]:
        raise InterruptedExecution("out-of-band native action or divergent learning receipts")
    old_count = before["completed_cycles"]
    result = controller.step(request_id, duration_s=duration_s)
    after = status(controller)
    if not after["synchronized"]:
        raise InterruptedExecution("native feedback not synchronized across modules")
    new_count = after["completed_cycles"]
    if new_count - old_count not in (0, 1):
        raise ValueError("unexpected unified learning delta")
    plan = result["plan"]
    native = result["native_receipt"]
    prediction = result["prediction"]
    observed = prediction.get("actual")
    if observed is not None:
        source = prediction["source"]
        state = controller.status()["state"]
        episode = next((e for e in state["episodes"] if e["id"] == request_id), None)
        if episode is None or episode["source"] != source or (
                episode["actual_action"] != native["actual_action"]):
            raise ValueError("native outcome has no matching learned episode")
    else:
        source = None

    # These are traceable stages of the ORIGINAL native controller, not
    # independent action calls. Native protect veto always remains authoritative.
    stages = {
        "motivated_preference": plan["motivation"]["preferred"],
        "workspace_preference": plan["workspace"]["preferred"],
        "neurovisceral_advice": plan["neurovisceral"]["recommendation"],
        "spinal_reflex_advice": plan["spinal_reflex"]["recommendation"],
        "final_requested": plan["preferred"],
        "native_actual": native.get("actual_action"),
    }
    if (plan["workspace"]["preferred"] == "observe"
            or plan["neurovisceral"]["recommendation"] == "observe"
            or plan["spinal_reflex"]["recommendation"] == "observe"):
        if plan["preferred"] != "observe":
            raise ValueError("conservative advisory veto was bypassed")
    return {
        "schema": SCHEMA,
        "request_id": request_id,
        "replayed": result["replayed"],
        "native_cycles_in_this_call": result["this_call_native_cycles"],
        "native_receipt_status": native["status"],
        "body": {
            "before": prediction["before"],
            "predicted_after": prediction["expected"],
            "observed_after": observed,
        },
        "need": _need_proxies(prediction["before"]),
        "memory": {
            "recalled_episode_ids": plan["recalled"],
            "workspace_source_ids": plan["workspace"]["retrieved_receipt_ids"],
            "prior_prediction_samples": plan["prediction"]["prior_samples"],
            "broadcast_attention": plan["workspace"]["broadcast"],
        },
        "decision": stages,
        "learning": {
            "observed_native_source": source,
            "prediction_mae": prediction.get("mean_absolute_error"),
            "learned_in_this_call": new_count - old_count,
            "total_receipt_grounded_cycles": new_count,
            "all_layers_synchronized": after["synchronized"],
        },
        "native_protection_authoritative": True,
        "synthetic_fixture_only": True,
        "physical_actuation": False,
        "api_calls": 0,
        "subjective_experience_inferred": False,
    }


def demo(output_dir):
    """Finite two-fixture, cold-restart demonstration with no external API."""
    root = Path(output_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    arms = {}
    for fixture in ("normal", "sleep"):
        path = root / (fixture + ".sqlite")
        with BodyLoop.start(path, fixture=fixture, max_actions=2) as loop:
            enabled = enable(loop, desire_proxy=.6)
            controller = _controller(loop)
            first = step(controller, "one")
            assert enabled["completed_cycles"] == 0
            assert first["learning"]["all_layers_synchronized"]
        with BodyLoop(path) as loop:
            controller = _controller(loop)
            replay = step(controller, "one")
            second = step(controller, "two")
            final = status(controller)
            assert replay["native_cycles_in_this_call"] == 0
            assert replay["learning"]["learned_in_this_call"] == 0
            assert final["completed_cycles"] == 2 and final["synchronized"]
            arms[fixture] = {
                "first_action": first["decision"]["native_actual"],
                "second_action": second["decision"]["native_actual"],
                "cold_restart_replay_safe": replay["replayed"],
                "distinct_native_receipts": final["completed_cycles"],
                "source_pinned": final["initial_source_pinned"],
            }
    result = {
        "schema": SCHEMA, "two_fixtures": list(arms),
        "total_native_software_cycles": 4, "arms": arms,
        "all_native_receipts_synchronized": all(x["source_pinned"] and
            x["distinct_native_receipts"] == 2 for x in arms.values()),
        "api_calls": 0, "physical_actuation": False,
        "subjective_experience_inferred": False,
    }
    (root / "summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
