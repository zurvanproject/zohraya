"""Two matched, finite 17-cycle native Tadash software-body experiments.

Wave source is the exact PR #132 numerical waveform, pinned to a source
checkpoint at opt-in and connected to the PR #134 motivational policy.
The 2-second wave increments are MODEL indices and never alter native clock.
"""
import json
from pathlib import Path

from .experience import ExperienceController
from .host import BodyLoop

STEPS = 17
ARMS = ("baseline", "wave")


def _step_report(result):
    p = result["plan"]
    native = result["native_receipt"]
    if result["replayed"] or result["this_call_native_cycles"] != 1 or (
            native["status"] != "complete"):
        raise AssertionError("only fresh native BodyLoop completed cycles count")
    wave = p.get("autonomic_wave")
    motive = p["motivation"]
    return {
        "requested": p["preferred"],
        "actual": native["actual_action"],
        "model_phase": wave["sample"]["phase"] if wave else None,
        "model_t_seconds": wave["sample"]["t_seconds"] if wave else None,
        "activation_envelope": wave["sample"]["activation_envelope"] if wave else None,
        "model_sympathetic_proxy": wave["sample"]["sympathetic_proxy"] if wave else None,
        "model_parasympathetic_proxy": wave["sample"]["parasympathetic_proxy"] if wave else None,
        "model_resp_drive_proxy": wave["sample"]["respiratory_drive_proxy"] if wave else None,
        "model_pelvic_command_proxy_unactuated": (
            wave["sample"]["pelvic_motor_command_proxy"] if wave else None),
        "exploration_boost_from_wave": motive["wave_exploration_boost"],
        "regulation_pressure_from_wave": motive["wave_regulation_pressure"],
        "native_protection_preserved": motive["native_safety_still_authoritative"],
        "subjective_experience_inferred": False,
    }


def _run_arm(output, arm):
    path = output / ("native-" + arm + ".sqlite")
    with BodyLoop.start(path, fixture="normal", max_actions=STEPS) as loop:
        c = ExperienceController.enable(loop)
        c.enable_workspace()
        c.enable_motivation(desire_proxy=.95)
        if arm == "wave":
            c.enable_autonomic_bridge()
        original_checkpoint = loop.body().checkpoint()["sha256"]
        first = c.step("cycle-01")
        if first["this_call_native_cycles"] != 1:
            raise AssertionError("first native software cycle required")
    with BodyLoop(path) as loop:
        c = ExperienceController(loop)
        before = c.status()
        if before["native"]["completed_cycles"] != 1:
            raise AssertionError("native session cold restart changed cycles")
        replay = c.step("cycle-01")
        if not replay["replayed"] or replay["this_call_native_cycles"] != 0:
            raise AssertionError("native completed cycle replayed")
        collected = [first]
        for i in range(2, STEPS + 1):
            collected.append(c.step("cycle-%02d" % i))
        rows = [_step_report(r) for r in collected]
        status = c.status()
        if status["native"]["completed_cycles"] != STEPS or (
                status["native"]["actions_remaining"] != 0) or (
                status["native"]["failed_cycles"]) or (
                status["native"]["unresolved_running"]):
            raise AssertionError("native software-body budget/protection failed")
        if status["motivational_drive"]["native_feedback_cycles"] != STEPS or (
                status["integrated_workspace"]["learned_native_cycles"] != STEPS):
            raise AssertionError("native feedback was not persisted in both modules")
        wave_state = status["autonomic_motivation_bridge"]
        if arm == "wave":
            if not wave_state or wave_state["native_feedback_cycles"] != STEPS or (
                    wave_state["model_t_seconds"] != 32.) or (
                    not wave_state["model_index_saturated"]):
                raise AssertionError("autonomic wave did not run through modeled recovery")
            if wave_state["initial_native_checkpoint_sha256"] != original_checkpoint:
                raise AssertionError("bridge source changed after body cycles")
            phases = [r["model_phase"] for r in rows]
            if (phases.count("baseline") != 1 or phases.count("rise") != 5 or
                    phases.count("peak") != 3 or phases.count("recovery") != 8):
                raise AssertionError("PR132 model phases missing or reordered")
            if not any(r["regulation_pressure_from_wave"] > 0 for r in rows):
                raise AssertionError("PR132 wave never influenced motivation scores")
            if not any(r["exploration_boost_from_wave"] > 0 for r in rows):
                raise AssertionError("wave rise never influenced the motivational scores")
        elif wave_state is not None or any(r["model_phase"] for r in rows):
            raise AssertionError("wave module affected unselected baseline")
    return {
        "arm": arm,
        "initial_native_body_checkpoint_sha256": original_checkpoint,
        "native_cycles": STEPS,
        "native_protect_vetoes": sum(r["actual"] == "protect" for r in rows),
        "native_walks": sum(r["actual"] == "walk" for r in rows),
        "native_observes": sum(r["actual"] == "observe" for r in rows),
        "model_wave_active": arm == "wave",
        "cold_reopen_verified": True,
        "native_replay_extra_cycles": 0,
        "rows": rows,
    }


def demo(output_dir):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    arms = {arm: _run_arm(output, arm) for arm in ARMS}
    if arms["wave"]["initial_native_body_checkpoint_sha256"] != (
            arms["baseline"]["initial_native_body_checkpoint_sha256"]):
        raise AssertionError("not a matched native starting checkpoint")
    result = {
        "schema": "tadash-autonomic-motivation-native-demo/1",
        "source": "PR132 native-checkpoint autonomic wave + PR134 motivation + PR130 workspace",
        "body_fixture": "normal",
        "total_native_software_cycles": 34,
        "wave_model_samples": 17,
        "wave_model_duration_seconds_not_body_elapsed_time": 32,
        "arms": arms,
        "wave_model_native_source_verified": True,
        "wave_model_is_reversible_authoring": True,
        "native_veto_preserved": True,
        "api_calls": 0,
        "physical_actuation": False,
        "actual_pelvic_contractions": 0,
        "subjective_orgasm_or_lust_inferred": False,
        "clinical_calibration": False,
        "generalization_claim": False,
    }
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return result
