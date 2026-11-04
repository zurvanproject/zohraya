"""Matched finite standing/observation scenario for the native Tadash body.

Native BodyLoop runs in bounded mode. Both arms explicitly request observe.
The optional neurovisceral overlay is read-only: it cannot alter a pose, gait,
vital sign, neural weights, checkpoint, energy balance or actuator command.
This is an engineering check of source provenance and comparison, not
validated standing biomechanics or an observed subjective sensation.
"""
from pathlib import Path
import json

from .host import BodyLoop
from . import neurovisceral


def measure(body):
    """Use executed software body outputs, not invented physiological values."""
    native = body.owner.body()
    m = native["minimum_state"]
    pose = native["pose"]
    proprio = native["proprioception"]
    feet = {k: {
        "load_N": proprio[k]["load"],
        "contact": proprio[k]["contact"],
        "velocity_m_s": proprio[k]["velocity"],
    } for k in ("foot_L", "foot_R")}
    return {
        "native_checkpoint_sha256": body.checkpoint()["sha256"],
        "native_revision": body.revision,
        "posture_phase": pose["posture_phase"],
        "center_of_mass_xy_m": list(body.owner.physical.state.com_m),
        "balance_proxy": m["balance"],
        "hr_bpm": m["HR"],
        "rr_per_min": m["RR"],
        "muscle_tone_proxy": m["muscle_tone"],
        "sympathetic_proxy": m["sympathetic"],
        "parasympathetic_proxy": m["parasympathetic"],
        "feet": feet,
        "tail_orientation_rad": pose["tail_orientation_rad"],
        "walk_steps": body.owner.physical.state.walk_steps,
        "full_collision_validation": pose["full_collision_and_multibody_dynamics_validated"],
    }


def run_arm(output, active):
    path = output / ("standing-neuro.sqlite" if active else "standing-baseline.sqlite")
    with BodyLoop.start(path, fixture="normal", mode="bounded", max_actions=3) as loop:
        initial_body = loop.body()
        start = measure(initial_body)
        source = neurovisceral.capture(initial_body)
        state = neurovisceral.initial(source) if active else None
        snapshots = [start]
        previews = []
        receipts = []
        for i in range(1, 4):
            pre_body = loop.body()
            sample = neurovisceral.capture(pre_body)
            if active:
                forecast = neurovisceral.preview(
                    state, sample, desire_proxy=.8)
                previews.append({
                    "source_checkpoint": sample["native_checkpoint_sha256"],
                    "predicted_if_actuated_not_actuated": forecast["predicted_if_actuated_not_actuated"],
                    "recommendation": forecast["recommendation"],
                    "constraints": forecast["constraints"],
                })
                # This is an observation-only advisory; standing command is
                # explicit and identical in the baseline and overlay arms.
            loop.observe()
            receipt = loop.step(
                decision_id="standing-%02d" % i,
                duration_s=.1,
                preferred_action="observe")
            if receipt["status"] != "complete":
                raise AssertionError("native standing scenario not completed")
            if receipt["actual_action"] not in ("observe", "protect"):
                raise AssertionError("standing scenario unexpectedly commanded locomotion")
            if active:
                state = neurovisceral.record(
                    state, "standing-%02d" % i, forecast,
                    "native-decision://standing-%02d/observed" % i,
                    receipt["actual_action"],
                    receipt["self_model_after"]["checkpoint_sha256"])
            receipts.append({
                "requested": receipt["requested_action"],
                "actual": receipt["actual_action"],
                "body_audit": receipt["body_audit"],
            })
            snapshots.append(measure(loop.body()))
        final_status = loop.status()
    with BodyLoop(path) as loop:
        before = loop.body().checkpoint()["sha256"]
        repeated = loop.step(
            decision_id="standing-01", duration_s=.1, preferred_action="observe")
        if not repeated["replayed"] or loop.body().checkpoint()["sha256"] != before:
            raise AssertionError("native standing replay changed body")
        restored = measure(loop.body())
    if snapshots[-1] != restored:
        raise AssertionError("standing body changed across cold restart")
    if final_status["completed_cycles"] != 3 or final_status["actions_remaining"] != 0:
        raise AssertionError("standing native cycle accounting failed")
    return {
        "active_neurovisceral_overlay": active,
        "source_native_checkpoint": source["native_checkpoint_sha256"],
        "snapshots": snapshots,
        "overlay_counterfactuals": previews,
        "native_receipts": receipts,
        "native_cycles": final_status["completed_cycles"],
        "replay_extra_cycles": 0,
        "cold_reopen_matches": True,
        "overlay_receipts": state["completed_cycles"] if active else 0,
    }


def demo(output_dir):
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    baseline = run_arm(output, False)
    enhanced = run_arm(output, True)
    if baseline["source_native_checkpoint"] != enhanced["source_native_checkpoint"]:
        raise AssertionError("standing arms do not share initial native state")
    # A read-only model should NOT claim to improve the native biomechanical result.
    for x, y in zip(baseline["snapshots"], enhanced["snapshots"]):
        if x != y:
            raise AssertionError("read-only neurovisceral overlay changed native standing")
    report = {
        "schema": "tadash-standing-neurovisceral-ablation/1",
        "scenario": "requested_observe_with_native_foot_contact_and_balance_receipts",
        "arms": {"baseline": baseline, "neurovisceral": enhanced},
        "total_native_cycles": 6,
        "total_simulated_seconds": .6,
        "legacy_warmup_per_arm_seconds": 7,
        "matched_native_standing_behavior": True,
        "native_action_modes": [r["actual"] for r in enhanced["native_receipts"]],
        "native_neural_weights_modified": False,
        "actual_native_physiology_changed_by_overlay": False,
        "model_counterfactual_only": True,
        "actual_pelvic_contractions": 0,
        "real_biological_measurements": False,
        "biomechanics_calibrated_for_170cm_78kg_body": False,
        "api_calls": 0,
        "physical_actuation": False,
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return report
