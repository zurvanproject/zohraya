"""Opt-in fictional embodied peak/regulation/learning bridge for Tadash.

A peak here is a label on PR #132's AUTHORED waveform, never orgasm,
felt pleasure, sexuality, pelvic contraction, subjective experience, or a
change to the physical/native body. The only learned signal is a bounded
regulation score from COMPLETED native software-body receipts. All actions
remain under the existing workspace, spinal, and native protection vetoes.
"""
from copy import deepcopy
import math

from . import autonomic_bridge, motivation, neurovisceral

SCHEMA = "tadash-embodied-peak-reward-memory/1"
SCOPE = "authored_wave_peak_plus_native_regulation_receipts_no_felt_experience"
MAX_RECEIPTS = 32
ACTIONS = ("walk", "observe", "protect", "other")
BODY_FIELDS = ("energy", "fatigue", "pain", "sleep_pressure")
PHASES = ("baseline", "rise", "peak", "recovery")


def unit(x, label):
    if type(x) not in (int, float) or not math.isfinite(x) or not 0. <= x <= 1.:
        raise ValueError("finite normalized " + label + " required")
    return float(x)


def clip(x):
    return max(0., min(1., x))


def body_metrics(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("minimum_state"), dict):
        raise ValueError("native software-body observation required")
    return {k: unit(snapshot["minimum_state"].get(k), k) for k in BODY_FIELDS}


def valid_sha(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def initial(motive_state, wave_state, neuro_state):
    """One-time source pin before native actions; no state/physics mutation."""
    motivation.validate(motive_state)
    autonomic_bridge.validate(wave_state)
    neurovisceral.validate(neuro_state)
    source = wave_state["original_checkpoint_sha256"]
    if source != neuro_state["initial_native_checkpoint_sha256"]:
        raise ValueError("wave and neural source checkpoint mismatch")
    value = {
        "schema": SCHEMA, "scope": SCOPE,
        "original_checkpoint_sha256": source,
        "wave_trace_sha256": wave_state["wave_trace_sha256"],
        "desire_parameter": motive_state["desire_proxy"],
        "native_feedback_cycles": 0, "modeled_peak_count": 0,
        "refractory_remaining": 0, "regulation_ema": 0.,
        "receipts": [],
    }
    validate(value)
    return value


def validate(state):
    if not isinstance(state, dict) or set(state) != {
            "schema", "scope", "original_checkpoint_sha256", "wave_trace_sha256",
            "desire_parameter", "native_feedback_cycles", "modeled_peak_count",
            "refractory_remaining", "regulation_ema", "receipts"}:
        raise ValueError("embodied memory schema mismatch")
    if state["schema"] != SCHEMA or state["scope"] != SCOPE or not valid_sha(
            state["original_checkpoint_sha256"]) or not valid_sha(state["wave_trace_sha256"]):
        raise ValueError("invalid embodied provenance")
    unit(state["desire_parameter"], "authored desire")
    unit(state["regulation_ema"], "regulation EMA")
    cycles = state["native_feedback_cycles"]
    peaks = state["modeled_peak_count"]
    refractory = state["refractory_remaining"]
    if (type(cycles) is not int or cycles < 0 or cycles > 100 or
            type(peaks) is not int or not 0 <= peaks <= cycles or
            type(refractory) is not int or not 0 <= refractory <= 3):
        raise ValueError("invalid memory/cycle counters")
    receipts = state["receipts"]
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS or len(receipts) > cycles:
        raise ValueError("unbounded embodied receipts")
    ids = []
    for r in receipts:
        if not isinstance(r, dict) or set(r) != {
                "id", "source", "before_sha256", "after_sha256", "phase",
                "modeled_peak", "actual_action", "regulation_delta", "safe_reward_proxy"}:
            raise ValueError("malformed embodied memory receipt")
        if (type(r["id"]) is not str or not r["id"] or type(r["source"]) is not str
                or not r["source"].startswith("native-decision://")
                or not valid_sha(r["before_sha256"]) or not valid_sha(r["after_sha256"])
                or r["phase"] not in PHASES or type(r["modeled_peak"]) is not bool
                or r["actual_action"] not in ACTIONS):
            raise ValueError("invalid embodied native provenance")
        d = r["regulation_delta"]
        if type(d) not in (int, float) or not math.isfinite(d) or not -1. <= d <= 1.:
            raise ValueError("invalid observed regulation delta")
        unit(r["safe_reward_proxy"], "receipt reward")
        ids.append(r["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate native receipt")
    return state


def preview(state, snapshot, motivated, wave, neuro):
    """Freeze cross-system inputs BEFORE action; never infer an inner experience."""
    validate(state)
    autonomic_bridge.validate_preview(wave)
    if not isinstance(motivated, dict) or motivated.get("schema") != motivation.SCHEMA or (
            motivated.get("desire_source") != "explicit_authored_simulation_parameter" or
            unit(motivated.get("desire_proxy"), "motive desire") != state["desire_parameter"]):
        raise ValueError("verified authored motivation required")
    if not isinstance(neuro, dict) or neuro.get("schema") != neurovisceral.SCHEMA or (
            neuro.get("pure_observation_only") is not True or
            neuro.get("actual_native_physiology_changed") is not False):
        raise ValueError("read-only neurovisceral predecision required")
    checkpoint = snapshot.get("checkpoint_sha256")
    if (not valid_sha(checkpoint) or neuro.get("native_checkpoint_sha256") != checkpoint
            or wave["initial_native_checkpoint_sha256"] != state["original_checkpoint_sha256"]
            or wave["wave_trace_sha256"] != state["wave_trace_sha256"]
            or neuro.get("desired_input_is_authored") != state["desire_parameter"]):
        raise ValueError("embodied source checkpoint or authored input mismatch")
    phase = wave["sample"]["phase"]
    activation = unit(wave["sample"]["activation_envelope"], "model activation")
    if (neuro.get("wave_phase") != phase or
            neuro.get("wave_activation_is_authored") != activation):
        raise ValueError("neural/wave phase disagreement")
    routes = neuro.get("functional_routes")
    if not isinstance(routes, dict):
        raise ValueError("functional neurovisceral routes required")
    pelvic = unit(routes.get("pudendal_motor_command_proxy_not_executed"), "unactuated motor")
    before = body_metrics(snapshot)
    distress = max(before["fatigue"], before["pain"], before["sleep_pressure"])
    modeled_peak = phase == "peak" and activation >= 0.95
    regulate = (modeled_peak or state["refractory_remaining"] > 0 or
                distress >= 0.55 or before["energy"] < 0.5)
    return {
        "schema": SCHEMA, "source_checkpoint_sha256": checkpoint,
        "wave_trace_sha256": state["wave_trace_sha256"],
        "source_state_cycle": state["native_feedback_cycles"],
        "phase": phase, "modeled_activation": activation,
        "authored_desire": state["desire_parameter"],
        "pelvic_motor_command_proxy_not_executed": pelvic,
        "modeled_peak_not_orgasm": modeled_peak,
        "refractory_remaining_before": state["refractory_remaining"],
        "regulation_ema_before": state["regulation_ema"],
        "native_body_before": before,
        "recommendation": "observe" if regulate else "no_change",
        "actual_somatic_contractions": 0,
        "felt_pleasure_or_orgasm_claimed": False,
        "native_safety_authoritative": True,
    }


def record(state, request_id, frozen, native_source, actual_action,
           before_snapshot, after_snapshot, harm):
    """Write ONLY authoritative completed native outcome to the same SQLite state."""
    validate(state)
    if (type(request_id) is not str or not request_id or
            any(r["id"] == request_id for r in state["receipts"]) or
            type(native_source) is not str or
            not native_source.startswith("native-decision://") or
            actual_action not in ACTIONS):
        raise ValueError("authoritative distinct native receipt required")
    if (not isinstance(frozen, dict) or frozen.get("schema") != SCHEMA or
            frozen.get("source_state_cycle") != state["native_feedback_cycles"] or
            frozen.get("wave_trace_sha256") != state["wave_trace_sha256"] or
            frozen.get("authored_desire") != state["desire_parameter"] or
            frozen.get("regulation_ema_before") != state["regulation_ema"] or
            frozen.get("refractory_remaining_before") != state["refractory_remaining"] or
            frozen.get("phase") not in PHASES or
            type(frozen.get("modeled_peak_not_orgasm")) is not bool or
            frozen.get("felt_pleasure_or_orgasm_claimed") is not False or
            frozen.get("actual_somatic_contractions") != 0 or
            frozen.get("native_safety_authoritative") is not True):
        raise ValueError("unfrozen or invalid embodied predecision")
    if (frozen["modeled_peak_not_orgasm"] !=
            (frozen["phase"] == "peak" and frozen.get("modeled_activation") == 1.)):
        raise ValueError("modeled peak predecision mismatch")
    if (frozen["source_checkpoint_sha256"] != before_snapshot.get("checkpoint_sha256")
            or frozen["native_body_before"] != body_metrics(before_snapshot)):
        raise ValueError("native before source mismatch")
    after_sha = after_snapshot.get("checkpoint_sha256")
    if not valid_sha(after_sha):
        raise ValueError("native after checkpoint required")
    b, a = body_metrics(before_snapshot), body_metrics(after_snapshot)
    harm = unit(harm, "actual native harm")
    delta = ((a["energy"] - b["energy"]) +
             (b["fatigue"] - a["fatigue"]) +
             (b["pain"] - a["pain"]) +
             (b["sleep_pressure"] - a["sleep_pressure"])) / 4.
    delta = max(-1., min(1., delta))
    reward = clip(max(0., delta) - harm)
    updated = deepcopy(state)
    updated["native_feedback_cycles"] += 1
    updated["modeled_peak_count"] += int(frozen["modeled_peak_not_orgasm"])
    updated["refractory_remaining"] = (3 if frozen["modeled_peak_not_orgasm"]
                                      else max(0, updated["refractory_remaining"] - 1))
    # A tiny bounded regulation score, NEVER positive reinforcement from a
    # fictional orgasm/peak label, only from actual simulated body outcomes.
    updated["regulation_ema"] = round(clip(0.85*updated["regulation_ema"] + 0.15*reward), 8)
    updated["receipts"].append({
        "id": request_id, "source": native_source,
        "before_sha256": frozen["source_checkpoint_sha256"],
        "after_sha256": after_sha, "phase": frozen["phase"],
        "modeled_peak": frozen["modeled_peak_not_orgasm"],
        "actual_action": actual_action,
        "regulation_delta": round(delta, 8),
        "safe_reward_proxy": round(reward, 8),
    })
    updated["receipts"] = updated["receipts"][-MAX_RECEIPTS:]
    validate(updated)
    return updated


def summary(state):
    validate(state)
    return {
        "enabled": True, "native_feedback_cycles": state["native_feedback_cycles"],
        "modeled_peak_count": state["modeled_peak_count"],
        "refractory_remaining": state["refractory_remaining"],
        "regulation_memory_ema": state["regulation_ema"],
        "retained_receipts": len(state["receipts"]),
        "model_peak_is_not_felt_orgasm": True,
        "reward_is_from_native_software_state_not_pleasure": True,
        "physical_actuation": False, "api_calls": 0,
    }
