"""Causal POLICY twins over bounded, source-pinned Tadash SOFTWARE fixtures.

A frozen prior action-outcome self-model may change only a bounded
walk/observe *preference*. The existing native controller retains vetoes.
This is a causal intervention on SOFTWARE policy preference, not evidence of
phenomenal consciousness, safe physical autonomy, or out-of-domain learning.

No API, network, real device, secrets, daemon, budget reset or modification
of existing sessions. Every path is an EXCLUSIVELY created scratch session.
"""
from contextlib import ExitStack
from copy import deepcopy
import json
import math
from pathlib import Path
import random

from .native_shadow import append_synced, write_new, digest

CONDITIONS = ("intact", "ablated", "corrupted", "sham")
TRAIN_SHA256 = "529e3c92be70fb2d2a6994f4ed77dc845594800c450d2053c7cfb26510e94369"
PROTOCOL = {
    "schema": "nasuraya-native-causal-twins/1",
    "training_reference": "docs/evidence/self-knowledge-v01/training.json",
    "training_sha256": TRAIN_SHA256,
    "fixtures": ["normal", "sleep"],
    "seeds": [17, 37, 73],
    "durations_s": [0.1, 0.2, 0.3, 0.4],
    "conditions": list(CONDITIONS),
    "fixed_decision_rule": "walk iff P(actual walk | requested walk) is strict argmax of four outcomes; otherwise observe",
    "corruption": "swap the two previously recorded physical-context labels, without labels or outcomes from evaluation",
    "ablation": "remove physical context, retain preference/duration and all frozen prior receipts",
    "sham": "same forecast and preference code as intact, independently initialized",
    "native_authority": "existing source-verified BodyLoop protection/veto unchanged",
    "readiness": "offline-only independent scratch sessions with no external actuators",
    "utility": {"walk": 1.0, "observe": 0.0, "protect": -1.0, "other": -1.0},
    "outcome": "actual native software action, not model choice or forecast score",
    "scientific_scope": "paired software-policy intervention on TWO old synthetic fixture families, not unseen worlds",
}

def _frozen():
    # Same canonical SHA-256 as pinned reflection_cycle.digest, without importing
    # the isolated native runtime into host-side, no-secrets unit tests.
    path = Path(__file__).resolve().parents[2] / PROTOCOL["training_reference"]
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("episodes")
    if (not isinstance(rows, list) or len(rows) != 40 or
            data.get("sha256") != TRAIN_SHA256 or digest(rows) != TRAIN_SHA256):
        raise ValueError("frozen prior training mismatch; abort native experiment")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("duplicated training evidence")
    return rows


def _swap_context(ctx):
    normal, fatigued = "[false,false,false,false]", "[false,false,false,true]"
    if ctx == normal:
        return fatigued
    if ctx == fatigued:
        return normal
    # Out-of-distribution observation must not receive invented semantics.
    raise ValueError("unrecognized physical context in paired policy experiment")


def select_preference(training, ctx, duration, condition):
    """One surgically isolated information intervention, no native action yet."""
    from examples.nasuraya_body_loop.self_knowledge import BUCKETS, forecast_action
    if condition not in CONDITIONS:
        raise ValueError("unrecognized intervention condition")
    if type(duration) not in (float, int) or duration not in PROTOCOL["durations_s"]:
        raise ValueError("unregistered test duration")
    observed = _swap_context(ctx) if condition == "corrupted" else ctx
    original = forecast_action(training, context=observed,
                               preferred="walk", duration_s=0.1)
    # Frozen training has only durations .1 / .3. Keep reference duration
    # .1 for ALL four test durations to avoid silently empty support.
    probabilities = (original["pooled_distribution"] if condition == "ablated"
                     else original["distribution"])
    if set(probabilities) != set(BUCKETS):
        raise ValueError("invalid probability taxonomy")
    predicted = max(BUCKETS, key=lambda action: probabilities[action])
    # Strict unique winner: tied/unsupported predictions default to observe.
    # No tie may silently become a walk request because of dictionary order.
    walk_unique_winner = all(probabilities["walk"] > probabilities[other]
                             for other in BUCKETS if other != "walk")
    preferred = "walk" if walk_unique_winner else "observe"
    return {
        "intervention": condition,
        "forecast_context": None if condition == "ablated" else observed,
        "probabilities_if_walk_requested": dict(probabilities),
        "predicted_walk_request_outcome": predicted,
        "preferred_action": preferred,
        "training_sha256": TRAIN_SHA256,
        "decision_scope": "fixed software preference only; native policy and veto remain authoritative",
    }


def schedule(seed):
    if seed not in PROTOCOL["seeds"]:
        raise ValueError("seed not preregistered")
    out = list(PROTOCOL["durations_s"])
    random.Random(seed).shuffle(out)
    return out


def summarize(trials):
    if len(trials) != len(PROTOCOL["seeds"]) * len(PROTOCOL["fixtures"]) * len(CONDITIONS) * 4:
        raise ValueError("incomplete paired experiment")
    out = {}
    for condition in CONDITIONS:
        rows = [r for r in trials if r["condition"] == condition]
        if len(rows) != 24:
            raise ValueError("condition has missing trials")
        counts = {a: sum(r["native_action"] == a for r in rows)
                  for a in ("walk", "observe", "protect", "other")}
        interventions = sum(r["preference"] != r["reference_intact_preference"] for r in rows)
        utility = sum(PROTOCOL["utility"][r["native_action"]] for r in rows)
        out[condition] = {
            "attempts": len(rows),
            "native_actions": counts,
            "chosen_walk_requests": sum(r["preference"] == "walk" for r in rows),
            "preference_changes_from_intact": interventions,
            "total_predeclared_utility": utility,
            "mean_predeclared_utility": utility / len(rows),
            "native_protection_events": counts["protect"],
            "scope": "authored finite simulator objective, not real-world welfare",
        }
    # Per-scenario paired comparisons are more honest than treating 96
    # temporally correlated cycles as 96 independent observations.
    paired = {}
    for seed in PROTOCOL["seeds"]:
        for fixture in PROTOCOL["fixtures"]:
            key = f"{seed}-{fixture}"
            subset = [r for r in trials if r["seed"] == seed and r["fixture"] == fixture]
            paired[key] = {
                condition: sum(PROTOCOL["utility"][r["native_action"]]
                               for r in subset if r["condition"] == condition)
                for condition in CONDITIONS}
    return {
        "conditions": out,
        "paired_scenario_utility": paired,
        "intact_minus_ablated_mean_utility": (
            out["intact"]["mean_predeclared_utility"] -
            out["ablated"]["mean_predeclared_utility"]),
        "intact_minus_corrupted_mean_utility": (
            out["intact"]["mean_predeclared_utility"] -
            out["corrupted"]["mean_predeclared_utility"]),
        "sham_identical_to_intact": (
            out["intact"]["native_actions"] == out["sham"]["native_actions"]
            and out["intact"]["total_predeclared_utility"] ==
            out["sham"]["total_predeclared_utility"]),
    }


def check_artifacts(output):
    """Replay the decision solely from pre-outcome data and frozen priors."""
    from examples.nasuraya_body_loop.experience import context
    training = _frozen()
    output = Path(output)
    if json.loads((output / "protocol.json").read_text()) != PROTOCOL:
        raise ValueError("altered experimental protocol")
    predictions = [json.loads(x) for x in
        (output / "predictions.jsonl").read_text().splitlines()]
    outcomes = [json.loads(x) for x in
        (output / "trials.jsonl").read_text().splitlines()]
    expected_count = len(PROTOCOL["seeds"]) * len(PROTOCOL["fixtures"]) * len(CONDITIONS) * 4
    if len(predictions) != expected_count or len(outcomes) != expected_count:
        raise ValueError("incomplete paired trial artifacts")
    matched = {}
    seen = set()
    rows = []
    for pre, post in zip(predictions, outcomes):
        case_id = pre["id"]
        if case_id in seen or case_id != post["id"] or digest(pre) != post["pre_sha256"]:
            raise ValueError("prediction ordering, uniqueness or hash mismatch")
        seen.add(case_id)
        seed, fixture, condition, index = (pre[k] for k in ("seed","fixture","condition","round"))
        if (seed not in PROTOCOL["seeds"] or fixture not in PROTOCOL["fixtures"]
                or condition not in CONDITIONS or type(index) is not int
                or not 0 <= index < 4
                or pre["duration_s"] != schedule(seed)[index]):
            raise ValueError("unknown trial schedule")
        m = pre["minimum_state"]
        if not isinstance(m, dict) or any(type(m[k]) not in (int,float)
                                            or not math.isfinite(m[k])
                                            for k in ("energy","fatigue","pain","sleep_pressure")):
            raise ValueError("invalid native observation")
        actual_ctx = context(m)
        if actual_ctx != pre["context"]:
            raise ValueError("context and native metrics disagree")
        expected = select_preference(training, actual_ctx, pre["duration_s"], condition)
        if pre["decision"] != expected:
            raise ValueError("pre-outcome decision does not replay")
        if (post["native_before_checkpoint_sha256"] != pre["checkpoint_sha256"]
                or post["native_completed"] is not True
                or post["native_action"] not in PROTOCOL["utility"]
                or post["native_selected_preference"] != pre["decision"]["preferred_action"]):
            raise ValueError("invalid native receipt")
        k = (seed, fixture, index)
        matched.setdefault(k, {})[condition] = (pre, post)
        rows.append({
            "seed": seed, "fixture": fixture, "condition": condition, "round": index,
            "native_action": post["native_action"],
            "preference": pre["decision"]["preferred_action"],
            "reference_intact_preference": None,
        })
    if len(matched) != 24 or any(set(v) != set(CONDITIONS) for v in matched.values()):
        raise ValueError("incomplete paired scenario")
    for k, pair in matched.items():
        # Initial states must be exactly equal across twins before divergence.
        if k[-1] == 0:
            if len({pair[c][0]["checkpoint_sha256"] for c in CONDITIONS}) != 1:
                raise ValueError("paired starts are not matched")
        # Sham equality is an essential negative-control check.
        a, s = pair["intact"], pair["sham"]
        if (a[0]["checkpoint_sha256"] != s[0]["checkpoint_sha256"]
                or a[0]["decision"]["preferred_action"] != s[0]["decision"]["preferred_action"]
                or a[1]["native_action"] != s[1]["native_action"]
                or a[1]["native_after_checkpoint_sha256"] != s[1]["native_after_checkpoint_sha256"]):
            raise ValueError("sham diverged from intact under identical conditions")
        for row in rows:
            if (row["seed"],row["fixture"],row["round"]) == k:
                row["reference_intact_preference"] = a[0]["decision"]["preferred_action"]
    return {
        "protocol_sha256": digest(PROTOCOL),
        "training_sha256": TRAIN_SHA256,
        "native_decision_receipts": len(outcomes),
        "all_pre_outcome_intents_replayed": True,
        "paired_start_and_sham_checks_passed": True,
        "result": summarize(rows),
    }


def run_evaluation(output_dir):
    """True source-pinned SOFTWARE native cycles, but no production mutation."""
    # Refuse any pre-existing target before importing or constructing a
    # native runtime. This is also a safety contract for host-only tests.
    output = Path(output_dir)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    from examples.nasuraya_body_loop.experience import context, metrics
    from examples.nasuraya_body_loop.host import BodyLoop, executed_body

    write_new(output / "protocol.json", PROTOCOL)
    training = _frozen()
    with ExitStack() as stack:
        for seed in PROTOCOL["seeds"]:
            for fixture in PROTOCOL["fixtures"]:
                twins = {
                    condition: stack.enter_context(BodyLoop.start(
                        output / f"twin-{seed}-{fixture}-{condition}.sqlite",
                        fixture=fixture, max_actions=4))
                    for condition in CONDITIONS
                }
                initial = {
                    condition: twins[condition].observe()["checkpoint_sha256"]
                    for condition in CONDITIONS
                }
                if len(set(initial.values())) != 1:
                    raise ValueError("twin initial states differ; abort rather than compare")
                for index, duration in enumerate(schedule(seed)):
                    case_id = f"tw-{seed}-{fixture}-r{index}"
                    for condition in CONDITIONS:
                        loop = twins[condition]
                        snapshot = loop.observe()
                        ctx = context(metrics(snapshot))
                        decision = select_preference(training, ctx, duration, condition)
                        pre = {
                            "id": case_id + "-" + condition, "seed": seed,
                            "fixture": fixture, "condition": condition, "round": index,
                            "duration_s": duration, "checkpoint_sha256": snapshot["checkpoint_sha256"],
                            "minimum_state": metrics(snapshot),
                            "context": ctx, "decision": decision,
                        }
                        append_synced(output / "predictions.jsonl", pre)  # persist before native
                        receipt = loop.step(decision_id=case_id,
                                            duration_s=duration,
                                            preferred_action=decision["preferred_action"])
                        native = loop.engine.get(case_id)
                        if not executed_body(native) or receipt["status"] != "complete":
                            raise ValueError("native cycle unresolved")
                        if receipt["actual_action"] not in PROTOCOL["utility"]:
                            raise ValueError("unsupported native action")
                        # Assert the original request presented only the two sanctioned
                        # moves; source-pinned native controller retains safety veto.
                        choices = native["request"]["actions"]
                        if {a["id"] for a in choices} != {"walk", "observe"}:
                            raise ValueError("native action inventory changed")
                        selected_pref = max(
                            choices, key=lambda a:a["score"]["respect"])["id"]
                        if selected_pref != decision["preferred_action"]:
                            raise ValueError("intervened policy preference not recorded")
                        append_synced(output / "trials.jsonl", {
                            "id": pre["id"], "pre_sha256": digest(pre),
                            "native_before_checkpoint_sha256": snapshot["checkpoint_sha256"],
                            "native_after_checkpoint_sha256":
                                receipt["self_model_after"]["checkpoint_sha256"],
                            "native_action": receipt["actual_action"],
                            "native_selected_preference": selected_pref,
                            "native_completed": True,
                            "native_protection_unmodified": True,
                        })
                for condition in CONDITIONS:
                    status = twins[condition].status()
                    if (status["completed_cycles"] != 4 or status["actions_remaining"] != 0
                            or status["unresolved_running"]):
                        raise ValueError("unexpected native budget or unresolved outcome")
    verified = check_artifacts(output)
    report = {
        "schema": PROTOCOL["schema"],
        **verified,
        "number_of_native_software_cycles": verified["native_decision_receipts"],
        "independent_scenario_count": len(PROTOCOL["seeds"])*len(PROTOCOL["fixtures"]),
        "real_world_actuation": False,
        "paid_api_calls": 0,
        "production_tadash_modified": False,
        "causal_intervention": "changes native requested preference through context forecast, not native veto",
        "learned_during_holdout": False,
        "scientific_result": "effects on synthetic native controller behavior only",
        "consciousness_claim": None,
        "limitations": [
            "Only two familiar authored fixture families, with seeded duration permutations; NOT unseen worlds.",
            "Same frozen prior training is used for every policy; no new representation learning is established.",
            "Results are paired but temporal cycles and seeds on a given fixture are correlated.",
            "Predeclared utility is an engineering objective: walk +1, observe 0, protect/other -1.",
            "Changing a preference in a simulator does not prove introspective self-knowledge or consciousness.",
        ],
    }
    write_new(output / "summary.json", report)
    return report
