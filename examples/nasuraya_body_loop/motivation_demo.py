"""Finite native software-body demonstration of the opt-in motivational drive."""
import json
from pathlib import Path

from .experience import ExperienceController
from .host import BodyLoop

FIXTURES = ("normal", "sleep")
ARMS = ("baseline", "motivated")
STEPS = 3


def demo(output_dir):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    sessions = {}
    for fixture in FIXTURES:
        for arm in ARMS:
            key = fixture + "_" + arm
            path = output / (key + ".sqlite")
            with BodyLoop.start(path, fixture=fixture, max_actions=STEPS) as loop:
                c = ExperienceController.enable(loop)
                c.enable_workspace()
                if arm == "motivated":
                    c.enable_motivation(desire_proxy=.9)
                first = c.step("first")
                saved_motivation = c.status()["state"].get("motivation")
            with BodyLoop(path) as loop:
                c = ExperienceController(loop)
                if c.status()["state"].get("motivation") != saved_motivation:
                    raise AssertionError("motivation persistence mismatch")
                replay = c.step("first")
                if not replay["replayed"] or replay["this_call_native_cycles"] != 0:
                    raise AssertionError("motivation replay caused another action")
                other = [c.step("second"), c.step("third")]
                rows = [first, *other]
                if any(x["native_receipt"]["status"] != "complete" or
                       x["this_call_native_cycles"] != 1 for x in rows):
                    raise AssertionError("native software-body completion required")
                status = c.status()
                if status["native"]["completed_cycles"] != STEPS or status["native"]["actions_remaining"] != 0:
                    raise AssertionError("native cycle budget mismatch")
                motive = status["motivational_drive"]
                if arm == "motivated" and (not motive or motive["native_feedback_cycles"] != STEPS):
                    raise AssertionError("missing native motivation receipts")
                if arm == "baseline" and motive is not None:
                    raise AssertionError("motivation unexpectedly enabled in baseline")
                if status["integrated_workspace"]["learned_native_cycles"] != STEPS:
                    raise AssertionError("shared workspace unexpectedly inactive")
                sessions[key] = {
                    "native_cycles": STEPS,
                    "preferences": [x["plan"]["preferred"] for x in rows],
                    "actual_actions": [x["native_receipt"]["actual_action"] for x in rows],
                    "motivation_reasons": [
                        x["plan"]["motivation"]["reason"] if "motivation" in x["plan"] else None
                        for x in rows],
                    "motivation_receipts": motive["native_feedback_cycles"] if motive else 0,
                    "workspace_receipts": status["integrated_workspace"]["learned_native_cycles"],
                    "cold_reopen_ok": True,
                    "extra_native_cycles_on_replay": 0,
                }
    total = sum(x["native_cycles"] for x in sessions.values())
    if total != 12:
        raise AssertionError("expected exactly 12 ordinary native cycles")
    # A deliberately AUTHORED internal-affect perturbation is applied
    # identically to three fresh sessions to isolate the desire coefficient.
    # This is NOT a naturally occurring feeling or observed biological state.
    challenge = {}
    for arm, desire in (("baseline", None), ("low", 0.0), ("high", 0.95)):
        path = output / ("affect-challenge-" + arm + ".sqlite")
        with BodyLoop.start(path, fixture="normal", max_actions=1) as loop:
            c = ExperienceController.enable(loop)
            c.enable_workspace()
            if desire is not None:
                c.enable_motivation(desire_proxy=desire)
            state = c._load()
            state["affect"] = {"valence": 0.0, "arousal": 0.72}
            c._save(state)
            result_one = c.step("controlled-challenge")
            if result_one["this_call_native_cycles"] != 1 or (
                    result_one["native_receipt"]["status"] != "complete"):
                raise AssertionError("challenge must consume a genuine native body cycle")
            challenge[arm] = {
                "desire_proxy": desire,
                "preference": result_one["plan"]["preferred"],
                "actual_action": result_one["native_receipt"]["actual_action"],
                "motivation_reason": (
                    result_one["plan"]["motivation"]["reason"]
                    if desire is not None else None),
                "native_cycles": loop.status()["completed_cycles"],
                "workspace_receipts": c.status()["integrated_workspace"]["learned_native_cycles"],
                "authored_affect": {"valence": 0.0, "arousal": 0.72},
            }
    if ([challenge[a]["actual_action"] for a in ("baseline", "low", "high")]
            != ["observe", "observe", "walk"]):
        raise AssertionError("controlled desire contrast did not produce genuine native action difference")
    result = {
        "schema": "tadash-native-motivational-drive-demo/1",
        "source": "source-pinned native Tadash software body, synthetic normal/sleep fixtures",
        "total_native_software_cycles": total + 3,
        "ordinary_native_software_cycles": total,
        "authored_challenge_native_software_cycles": 3,
        "challenge": challenge,
        "sessions": sessions,
        "baseline_native_protect_vetoes": sum(
            x["actual_actions"].count("protect")
            for k, x in sessions.items() if k.endswith("_baseline")),
        "motivated_native_protect_vetoes": sum(
            x["actual_actions"].count("protect")
            for k, x in sessions.items() if k.endswith("_motivated")),
        "native_replays_created_extra_cycles": 0,
        "authored_desire_proxy": .9,
        "api_calls": 0,
        "physical_actuation": False,
        "subjective_desire_or_pleasure_measured": False,
        "generalization_claim": False,
    }
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return result
