"""Paired, finite ablation of the REAL Tadash software-body working-memory option.

30 native software cycles (15 matched decisions, baseline vs opt-in workspace).
Native receipts are generated ONLY by BodyLoop; no fabricated training samples,
live API, physical actuation, background worker, or consciousness claims.
Run through the verified source-pinned nasuraya_body_loop worker.
"""
import json
from pathlib import Path

from .experience import ExperienceController
from .host import BodyLoop

SCHEMA = "tadash-native-workspace-ablation/1"
# Predeclared sequence. Repeated deterministic fixtures are NOT independent
# real-world environments, so findings remain limited to these authored cases.
FIXTURES = ("normal", "sleep", "normal", "sleep", "sleep")
ARMS = ("baseline", "workspace")
STEPS = 3


def _decision(result):
    native = result["native_receipt"]
    if native["status"] != "complete" or native["actual_action"] not in (
            "walk", "observe", "protect"):
        raise AssertionError("only successful native software-body receipts count")
    if result["replayed"] or result["this_call_native_cycles"] != 1:
        raise AssertionError("fresh software-body cycle required")
    plan = result["plan"]
    detail = plan.get("workspace")
    if detail is not None and (
            detail["preferred"] == "walk" and detail["base_preferred"] == "observe"):
        raise AssertionError("workspace may not promote observe into walk")
    return {
        "requested": plan["preferred"],
        "actual": native["actual_action"],
        "workspace_reason": detail["reason"] if detail else None,
        "workspace_receipt": detail is not None,
    }


def _arm(output, fixture, pair_index, arm):
    path = output / ("pair-%02d-%s.sqlite" % (pair_index, arm))
    with BodyLoop.start(path, fixture=fixture, max_actions=STEPS) as loop:
        controller = ExperienceController.enable(loop)
        if arm == "workspace":
            controller.enable_workspace()
        rows = [_decision(controller.step("trial-1"))]
        if loop.status()["completed_cycles"] != 1:
            raise AssertionError("first native step did not complete")
        saved_workspace = controller.status()["state"].get("workspace")
    # A fresh process can reopen this same ledger. No cycle is replayed.
    with BodyLoop(path) as loop:
        controller = ExperienceController(loop)
        current = controller.status()
        if current["state"].get("workspace") != saved_workspace:
            raise AssertionError("working memory changed across cold reopen")
        replay = controller.step("trial-1")
        if not replay["replayed"] or replay["this_call_native_cycles"] != 0:
            raise AssertionError("replay unexpectedly executed an action")
        if loop.status()["completed_cycles"] != 1:
            raise AssertionError("replay changed native completed-cycle count")
        for i in range(2, STEPS + 1):
            rows.append(_decision(controller.step("trial-%d" % i)))
        native = loop.status()
        state = controller.status()
        if (native["completed_cycles"] != STEPS or
                native["actions_remaining"] != 0 or native["failed_cycles"] or
                native["unresolved_running"]):
            raise AssertionError("unexpected native body budget or failure")
        workspace = state["integrated_workspace"]
        if arm == "workspace":
            if not workspace or workspace["learned_native_cycles"] != STEPS:
                raise AssertionError("workspace did not learn only from native cycles")
        elif workspace is not None:
            raise AssertionError("baseline unexpectedly enabled new workspace")
        if native["external_model_api_used"]:
            raise AssertionError("unexpected model API")
    return {"fixture": fixture, "arm": arm, "steps": rows,
            "native_cycles": STEPS, "replay_extra_cycles": 0,
            "cold_reopen_verified": True,
            "persisted_workspace_receipts": STEPS if arm == "workspace" else 0}


def _tally(pairs, arm):
    rows = [step for p in pairs for step in p[arm]["steps"]]
    return {
        "native_cycles": len(rows),
        "requested_walk": sum(r["requested"] == "walk" for r in rows),
        "requested_observe": sum(r["requested"] == "observe" for r in rows),
        "actual_walk": sum(r["actual"] == "walk" for r in rows),
        "actual_observe": sum(r["actual"] == "observe" for r in rows),
        "native_protect_vetoes": sum(r["actual"] == "protect" for r in rows),
        "recorded_workspace_receipts": sum(r["workspace_receipt"] for r in rows),
    }


def run(output_dir):
    """Create ten fresh native sessions, 30 cycles total, no external tools."""
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    pairs = []
    for i, fixture in enumerate(FIXTURES, 1):
        pair = {"pair": i, "fixture": fixture}
        for arm in ARMS:
            pair[arm] = _arm(output, fixture, i, arm)
        pairs.append(pair)

    baseline, enabled = (_tally(pairs, arm) for arm in ARMS)
    if baseline["native_cycles"] != 15 or enabled["native_cycles"] != 15:
        raise AssertionError("comparison must complete all 30 native cycles")
    if baseline["recorded_workspace_receipts"] != 0 or (
            enabled["recorded_workspace_receipts"] != 15):
        raise AssertionError("workspace opt-in boundary not respected")

    report = {
        "schema": SCHEMA,
        "source": "source-pinned Tadash software BodyLoop, actual decision receipts",
        "scope": "five matched pairs of authored normal/sleep synthetic fixtures",
        "total_native_cycles": 30,
        "matched_preference_comparisons": 15,
        "fresh_native_software_sessions": 10,
        "sessions_cold_reopened": 10,
        "extra_cycles_on_idempotent_replay": 0,
        "fixture_sequence": list(FIXTURES),
        "baseline": baseline,
        "workspace": enabled,
        "protect_veto_difference_baseline_minus_workspace": (
            baseline["native_protect_vetoes"] - enabled["native_protect_vetoes"]),
        "pairs": pairs,
        "api_calls": 0,
        "physical_actuation": False,
        "subjective_experience_inferred": False,
        "statistical_generalization_claim": False,
        "limitations": ("Repeated authored fixtures and a deterministic native policy "
                        "test functional safety behavior, not open-world learning."),
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return report
