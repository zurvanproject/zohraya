"""Read-only shadow instrumentation on VERIFIED, finite native Tadash fixtures.

This module runs only from the existing verified BodyLoop worker, on freshly
created synthetic fixture sessions. It never replaces the native controller's
policy or safety veto, modifies canonical Tadash, uses an API, or calls a real
actuator. All shadow forecasts are durably written BEFORE the native step.

The three cases compare contextual forecast, context-ablated pooled forecast
and a predeclared shuffled-context control. Cognitive-mechanism *prototypes*
also observe reduced body metrics with no authority over movement.

An improvement is NOT proof of consciousness or subjective experience.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

from .mechanisms import PrototypeCycle, RecurrentBinder, Workspace, PredictiveCoder

ACTIONS = ("walk", "observe", "protect", "other")
CONDITIONS = ("intact", "ablated", "corrupted")
PROTOCOL = {
    "schema": "nasuraya-native-shadow-eval/1",
    "fixtures": ["normal", "sleep"],
    "preferences": ["walk", "observe"],
    "durations_s": [0.1, 0.3],
    "train_rounds": 5,
    "holdout_rounds": 3,
    "context_shuffle_seed": 20261029,
    "scope": "finite constructed native Tadash software-body fixtures only",
    "actions_authored_by": "existing native BodyLoop, not shadow observers",
    "observer_permissions": "read_only_after_observe; no motor policy output",
    "predeclared_forecast_modes": {
        "intact": "same 40 receipts, conditioned on true observed physical context",
        "ablated": "same 40 receipts but uses only preferred action and duration",
        "corrupted": "same 40 receipts/outcomes, deterministic within-group permutation of contexts",
    },
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def append_synced(path, payload):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(canonical(payload) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_new(path, payload):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(payload) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def body_signals(snapshot):
    """Engineering proxies only: energy is NOT vision, fatigue is NOT audio."""
    from examples.nasuraya_body_loop.experience import metrics
    m = metrics(snapshot)
    return {
        "visual_proxy_energy": float(m["energy"]),
        "audio_proxy_inv_fatigue": float(1 - m["fatigue"]),
        "danger_proxy": float(max(m["pain"], m["sleep_pressure"])),
        "goal_proxy_inv_fatigue": float(1 - m["fatigue"]),
        "noise_proxy": float(abs(m["pain"] - m["sleep_pressure"])),
        "sensory_proxy_sleep_pressure": float(m["sleep_pressure"]),
    }


def _new_prototype(condition):
    if condition == "ablated":
        return PrototypeCycle(perception=RecurrentBinder(recurrent=False),
            workspace=Workspace(broadcast_enabled=False),
            prediction=PredictiveCoder(learning=False))
    return PrototypeCycle()


def shadow_observe(model, signals, *, corrupted=False):
    """A separate cognitive trace. It is NEVER returned to the actuator."""
    if set(signals) != {
        "visual_proxy_energy", "audio_proxy_inv_fatigue", "danger_proxy",
        "goal_proxy_inv_fatigue", "noise_proxy", "sensory_proxy_sleep_pressure"
    }:
        raise ValueError("unexpected body signal schema")
    danger = 1 - signals["danger_proxy"] if corrupted else signals["danger_proxy"]
    result = model.step(
        visual=signals["visual_proxy_energy"],
        audio=signals["audio_proxy_inv_fatigue"],
        danger=danger, goal=signals["goal_proxy_inv_fatigue"],
        noise=signals["noise_proxy"],
        sensory=signals["sensory_proxy_sleep_pressure"])
    return {
        "workspace_selected": result["workspace_selected"],
        "broadcast_inboxes": result["inboxes"],
        "attention_prediction": result["attention_prediction"],
        "prediction_error": result["prediction_error"],
        "reliability": result["reliability"],
        "belief": result["belief"],
        "quality_code": result["quality_code"],
        "query_plan": result["query_plan"],
        "scope": "read-only toy mechanism trace on native synthetic-body proxies",
    }


def vectors(episodes, *, ctx, preferred, duration_s, seed=20261029):
    """Three matched forecasts using EXACTLY the same training outcomes."""
    from examples.nasuraya_body_loop.self_knowledge import forecast_action
    from examples.nasuraya_body_loop.self_knowledge_eval import shuffled_contexts
    original = forecast_action(episodes, context=ctx,
                               preferred=preferred, duration_s=duration_s)
    shifted = forecast_action(shuffled_contexts(episodes, seed), context=ctx,
                              preferred=preferred, duration_s=duration_s)
    return {
        "intact": deepcopy(original["distribution"]),
        "ablated": deepcopy(original["pooled_distribution"]),
        "corrupted": deepcopy(shifted["distribution"]),
    }


def _valid_probability_vector(vector):
    if not isinstance(vector, dict) or set(vector) != set(ACTIONS):
        raise ValueError("exact four-action vector required")
    if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1
           for v in vector.values()):
        raise ValueError("nonfinite or impossible probability")
    if not math.isclose(sum(vector.values()), 1., rel_tol=0., abs_tol=1e-12):
        raise ValueError("probabilities must sum to one")


def score(vector, actual):
    _valid_probability_vector(vector)
    if actual not in ACTIONS:
        raise ValueError("native action outside allowed taxonomy")
    return sum((vector[action] - float(action == actual)) ** 2 for action in ACTIONS)


def grade(rows):
    if not rows:
        raise ValueError("nonempty holdout required")
    report = {}
    for condition in CONDITIONS:
        scores = []
        accuracy = []
        bins = {i: [] for i in range(4)}
        for row in rows:
            vector = row["pre"]["forecasts"][condition]
            actual = row["actual_action"]
            scores.append(score(vector, actual))
            action = max(ACTIONS, key=lambda key: vector[key])
            hit = int(action == actual)
            conf = vector[action]
            accuracy.append(hit)
            bins[min(int(conf * 4), 3)].append((conf, hit))
        ece = sum(len(items) / len(rows) *
                  abs(sum(c for c, _ in items) / len(items) -
                      sum(hit for _, hit in items) / len(items))
                  for items in bins.values() if items)
        report[condition] = {
            "mean_brier": sum(scores) / len(scores),
            "top_action_accuracy": sum(accuracy) / len(accuracy),
            "top_label_ece_four_bins": ece,
        }
    report["intact_minus_ablated_brier"] = (
        report["intact"]["mean_brier"] - report["ablated"]["mean_brier"])
    report["intact_minus_corrupted_brier"] = (
        report["intact"]["mean_brier"] - report["corrupted"]["mean_brier"])
    return report


def validate_saved(output_dir):
    """Recheck saved pre-outcome forecasts against original frozen training.

    Native outcomes cannot enter any prediction. This check never modifies files.
    It proves consistency, not that a repository actor cannot rewrite all logs.
    """
    output = Path(output_dir)
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    if protocol != PROTOCOL:
        raise ValueError("protocol changed")
    t = json.loads((output / "training.json").read_text(encoding="utf-8"))
    frozen = t["episodes"]
    if len(frozen) != 40 or digest(frozen) != t["sha256"]:
        raise ValueError("training commitment mismatch")
    predictions = [json.loads(line) for line in
                   (output / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    trials = [json.loads(line) for line in
              (output / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(predictions) != 64 or len(trials) != 64:
        raise ValueError("incomplete native cycle count")
    if len({row["id"] for row in trials}) != 64:
        raise ValueError("duplicate native IDs")
    holdout = []
    for p, row in zip(predictions, trials):
        if digest(p) != row.get("pre_sha256") or p["id"] != row["id"]:
            raise ValueError("forecast log/receipt mismatch")
        if p["snapshot_sha256"] != row["before_checkpoint_sha256"]:
            raise ValueError("source checkpoint mismatch")
        if row["actual_action"] not in ACTIONS or row["native_completed"] is not True:
            raise ValueError("unresolved or unrecognized native body action")
        if p["phase"] == "holdout":
            if p["training_sha256"] != t["sha256"] or p["training_count"] != 40:
                raise ValueError("training not held frozen")
            expected = vectors(frozen, ctx=p["context"], preferred=p["preferred"],
                               duration_s=p["duration_s"], seed=PROTOCOL["context_shuffle_seed"])
            if p["forecasts"] != expected:
                raise ValueError("forecasts do not replay from training")
            holdout.append({"pre": p, "actual_action": row["actual_action"]})
        elif p["phase"] != "warmup" or p["forecasts"] is not None:
            raise ValueError("unexpected warmup prediction")
    if len(holdout) != 24:
        raise ValueError("incorrect holdout size")
    if {r["id"] for r in frozen} & {r["pre"]["id"] for r in holdout}:
        raise ValueError("label leakage from holdout into training")
    return {
        "protocol_sha256": digest(PROTOCOL),
        "training_sha256": t["sha256"],
        "prediction_receipts": len(predictions),
        "native_trials": len(trials),
        "holdout": len(holdout),
        "metrics": grade(holdout),
    }


def run_evaluation(output_dir):
    """Execute 64 bounded NATIVE SOFTWARE fixture cycles with shadow A/B/C.

    Deliberately creates only new temporary fixture sessions; never accepts a
    path to an existing session or a live API key. Native action selection is
    independent of the read-only shadow observer for all three conditions.
    """
    from examples.nasuraya_body_loop.experience import context, metrics
    from examples.nasuraya_body_loop.host import BodyLoop, executed_body

    output = Path(output_dir)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_new(output / "protocol.json", PROTOCOL)
    sessions = []
    training = []
    frozen = None
    with ExitStack() as stack:
        for fixture in PROTOCOL["fixtures"]:
            for preferred in PROTOCOL["preferences"]:
                for duration in PROTOCOL["durations_s"]:
                    name = fixture + "-" + preferred + "-" + str(int(duration * 10))
                    loop = stack.enter_context(BodyLoop.start(
                        output / (name + ".sqlite"), fixture=fixture, max_actions=8))
                    observers = {condition: _new_prototype(condition)
                                 for condition in CONDITIONS}
                    sessions.append((name, fixture, preferred, duration, loop, observers))
        for index in range(PROTOCOL["train_rounds"] + PROTOCOL["holdout_rounds"]):
            is_holdout = index >= PROTOCOL["train_rounds"]
            if is_holdout and frozen is None:
                frozen = deepcopy(training)
                write_new(output / "training.json", {
                    "episodes": frozen, "sha256": digest(frozen)})
            for name, fixture, preferred, duration, loop, observers in sessions:
                case_id = name + "-round-" + str(index)
                snapshot = loop.observe()
                ctx = context(metrics(snapshot))
                signals = body_signals(snapshot)
                traces = {condition: shadow_observe(
                    observers[condition], signals, corrupted=(condition == "corrupted"))
                    for condition in CONDITIONS}
                predictions = vectors(
                    frozen, ctx=ctx, preferred=preferred, duration_s=duration,
                    seed=PROTOCOL["context_shuffle_seed"]) if is_holdout else None
                pre = {
                    "id": case_id, "phase": "holdout" if is_holdout else "warmup",
                    "round": index, "fixture": fixture,
                    "preferred": preferred, "duration_s": duration,
                    "context": ctx, "snapshot_sha256": snapshot["checkpoint_sha256"],
                    "training_sha256": digest(frozen) if is_holdout else None,
                    "training_count": len(frozen) if is_holdout else None,
                    "body_proxies": signals, "shadow_traces": traces,
                    "forecasts": predictions,
                    "shadow_did_not_choose_action": True,
                }
                # The scored predictions and cognitive traces now exist on disk.
                append_synced(output / "predictions.jsonl", pre)
                receipt = loop.step(decision_id=case_id,
                                    duration_s=duration, preferred_action=preferred)
                record = loop.engine.get(case_id)
                if not executed_body(record) or receipt["status"] != "complete":
                    raise ValueError("native body cycle failed or unresolved")
                actual = receipt["actual_action"]
                if actual not in ACTIONS:
                    raise ValueError("unknown native action")
                row = {
                    "id": case_id, "pre_sha256": digest(pre),
                    "before_checkpoint_sha256": snapshot["checkpoint_sha256"],
                    "after_checkpoint_sha256": receipt["self_model_after"]["checkpoint_sha256"],
                    "native_completed": True, "actual_action": actual,
                    "shadow_selected_native_action": False,
                }
                append_synced(output / "trials.jsonl", row)
                if not is_holdout:
                    from reflection_cycle import digest as native_digest
                    training.append({
                        "id": case_id, "kind": "observed_software_outcome",
                        "context": ctx, "preferred": preferred, "duration_s": duration,
                        "actual_action": actual,
                        "source": "native-decision://" + case_id + "/" + native_digest(record),
                    })
                elif digest(frozen) != pre["training_sha256"]:
                    raise AssertionError("frozen training mutated")
        native_cycles = sum(loop.status()["completed_cycles"]
                            for _, _, _, _, loop, _ in sessions)
        budgets = {name: loop.status()["actions_remaining"]
                   for name, _, _, _, loop, _ in sessions}
    result = validate_saved(output)
    if native_cycles != 64 or any(budgets.values()):
        raise AssertionError("native cycle count or reserved budget invalid")
    result.update({
        "schema": PROTOCOL["schema"],
        "actual_native_software_cycles": native_cycles,
        "simulator_fixture_families": 2,
        "training_trials": 40, "holdout_trials": 24,
        "heldout_outcomes_used_to_fit_forecasts": False,
        "real_world_actuation": False, "production_tadash_modified": False,
        "paid_api_calls": 0, "shadow_could_control_native_action": False,
        "cognitive_indicator_attainment_in_deployed_tadash": "not_assessed",
        "consciousness_verdict": None,
        "limitations": [
            "The software-body fixtures are authored and correlated, not independently new worlds.",
            "The interventions change only shadow forecasts/traces; all native actions are unchanged by the shadow.",
            "Consequently this is NOT a causal test of what a live self-model would do to body behavior.",
            "A low Brier or a positive ablation gap does not establish phenomenal consciousness.",
        ],
    })
    write_new(output / "summary.json", result)
    return result
