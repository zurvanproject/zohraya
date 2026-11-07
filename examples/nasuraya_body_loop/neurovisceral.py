"""Opt-in source-pinned neurovisceral coordination for fictional Tadash.

Anatomical pathways are declared design hypotheses. A sample is read from an
actual native software-body checkpoint, then a small numerical counterfactual
is projected. It never changes vital signs, energies, motor neurons, nerves,
pelvic muscles, or the stored native body. No calibrated physiology, biological
sexual response, felt desire, consciousness or real-world actuation is claimed.
"""
from copy import deepcopy
import math

SCHEMA = "tadash-neurovisceral-coordination/1"
SOURCE = "verified_native_software_body_checkpoint"
MAX_RECEIPTS = 32
ACTIONS = ("walk", "observe", "protect", "other")

# Explicit distinctions: afferent, efferent and slow monitoring are not
# interchangeable pathways. These are NOT reconstructed biological nerves.
PATHWAYS = (
    ("vagal_cardiopulmonary", "brainstem", "vagus", "heart_lungs", "parasympathetic"),
    ("thoracic_sympathetic", "spinal_autonomic", "sympathetic_chain", "heart_vessels", "sympathetic"),
    ("respiratory_drive", "brainstem", "phrenic_motor", "diaphragm", "co2_ventilation"),
    ("sacral_visceral", "sacral_spinal", "pelvic_splanchnic", "bladder_pelvic_viscera", "visceral"),
    ("sacral_somatic", "sacral_spinal", "pudendal", "pelvic_floor", "somatic"),
    ("caudal_motor", "caudal_spinal", "caudal_motor_roots", "tail_balance", "proprioceptive"),
    ("hindlimb_proprioception", "digitigrade_feet", "spinal_sensory", "postural_controller", "afferent"),
    ("resonan_sensory", "paired_horn_root_sensors", "trigeminal_like", "attention", "fictional_low_energy"),
    ("spandar_monitor", "thymic_capsule", "slow_monitor_only", "error_awareness", "fictional_no_veto"),
    ("azarine_thermal", "left_flank_reserve", "temperature_monitor", "energy_safety", "fictional_no_new_stock"),
)
VALUES = (
    "heart_bpm", "breaths_per_min", "sympathetic", "parasympathetic",
    "arousal", "pain", "fatigue", "sleep_pressure", "balance", "energy",
    "muscle_tone", "co2_drive", "oxygenation", "temperature_c",
    "neural_attention_hz", "neural_regulation_hz", "optional_motor_fraction",
    "resonan_attention", "resonan_shutter", "spandar_error",
    "azarine_budget_j", "native_reserve_j",
)
NORMALIZED = (
    "sympathetic", "parasympathetic", "arousal", "pain", "fatigue",
    "sleep_pressure", "balance", "energy", "muscle_tone", "co2_drive",
    "oxygenation", "optional_motor_fraction", "resonan_attention",
    "resonan_shutter",
)


def unit(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("finite normalized " + label + " required")
    return float(value)


def nonnegative(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative " + label + " required")
    return float(value)


def clip(value, low=0., high=1.):
    return min(high, max(low, value))


def anatomy():
    return {
        "schema": "tadash-neurovisceral-anatomy/1",
        "type": "declared_functional_connectivity_not_validated_anatomical_tractography",
        "pathways": [dict(id=n, origin=o, nerve=p, target=t, modality=m)
                     for n, o, p, t, m in PATHWAYS],
        "special_organs": {
            "resonan": "paired fictional horn-root sensors; one shared native attenuation proxy",
            "spandar": "thymic-capsule monitor of prediction error; not a second consciousness store",
            "azarine": "left-flank fictional reserve monitor; budget is a label in native reserve_J",
        },
        "separate_caudad_motor_and_pudendal": True,
        "native_organ_solvers_modified": False,
    }


def capture(native_body):
    """Read complete values from ONE native UnifiedBody checkpoint, no mutation."""
    if native_body is None or not hasattr(native_body, "checkpoint"):
        raise ValueError("native UnifiedBody instance required")
    before = native_body.checkpoint()["sha256"]
    core = native_body.owner.body()
    m, p = core["minimum_state"], core["physiological"]
    n = native_body.modules["neural"]
    s = native_body.modules["special"]
    reserve = native_body.owner.owner.body.state.reserve_J
    values = dict(
        heart_bpm=m["HR"], breaths_per_min=m["RR"],
        sympathetic=m["sympathetic"], parasympathetic=m["parasympathetic"],
        arousal=m["arousal"], pain=m["pain"], fatigue=m["fatigue"],
        sleep_pressure=m["sleep_pressure"], balance=m["balance"],
        energy=m["energy"], muscle_tone=m["muscle_tone"],
        co2_drive=p["CO2_drive"], oxygenation=p["oxygenation_proxy"],
        temperature_c=m["temperature"], neural_attention_hz=n["attention_hz"],
        neural_regulation_hz=n["regulation_hz"],
        optional_motor_fraction=n["optional_motor_fraction"],
        resonan_attention=s["resonan_attention"],
        resonan_shutter=s["shutter"], spandar_error=s["spandar_last_error"],
        azarine_budget_j=s["azarine_budget_J"], native_reserve_j=reserve,
    )
    for key in NORMALIZED:
        unit(values[key], key)
    for key in set(VALUES) - set(NORMALIZED):
        nonnegative(values[key], key)
    if (values["azarine_budget_j"] > min(7200., reserve) + 1e-6):
        raise ValueError("azarine budget exceeds native reserve ceiling")
    if native_body.checkpoint()["sha256"] != before:
        raise ValueError("neurovisceral sample crossed a native checkpoint change")
    sample = dict(source=SOURCE, native_checkpoint_sha256=before,
                  native_revision=native_body.revision, values=values)
    validate_sample(sample)
    return sample


def validate_sample(sample):
    if not isinstance(sample, dict) or set(sample) != {
            "source", "native_checkpoint_sha256", "native_revision", "values"}:
        raise ValueError("malformed native neurovisceral sample")
    h = sample["native_checkpoint_sha256"]
    if sample["source"] != SOURCE or type(h) is not str or len(h) != 64 or any(
            c not in "0123456789abcdef" for c in h):
        raise ValueError("unverified native source")
    if type(sample["native_revision"]) is not int or sample["native_revision"] < 0:
        raise ValueError("bad native revision")
    v = sample["values"]
    if not isinstance(v, dict) or set(v) != set(VALUES):
        raise ValueError("incomplete physiological/special-organ sample")
    for key in NORMALIZED:
        unit(v[key], key)
    for key in set(VALUES) - set(NORMALIZED):
        nonnegative(v[key], key)
    if v["azarine_budget_j"] > min(7200., v["native_reserve_j"]) + 1e-6:
        raise ValueError("azarine conservation contract")
    return sample


def initial(sample):
    validate_sample(sample)
    return dict(schema=SCHEMA, source=SOURCE,
                initial_native_checkpoint_sha256=sample["native_checkpoint_sha256"],
                completed_cycles=0, receipts=[], last_recommendation=None)


def validate(state):
    if not isinstance(state, dict) or set(state) != set(initial_dummy()):
        raise ValueError("invalid neurovisceral state")
    if state["schema"] != SCHEMA or state["source"] != SOURCE:
        raise ValueError("neurovisceral schema mismatch")
    h = state["initial_native_checkpoint_sha256"]
    if type(h) is not str or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("invalid initial native checkpoint")
    if type(state["completed_cycles"]) is not int or state["completed_cycles"] < 0:
        raise ValueError("invalid native cycle count")
    rs = state["receipts"]
    if not isinstance(rs, list) or len(rs) > MAX_RECEIPTS or len(rs) > state["completed_cycles"]:
        raise ValueError("neurovisceral receipts exceed native cycles")
    ids = []
    for item in rs:
        if not isinstance(item, dict) or set(item) != {
                "id", "source", "before_sha256", "after_sha256", "actual", "recommendation"}:
            raise ValueError("malformed neurovisceral receipt")
        if (type(item["id"]) is not str or not item["id"] or
                type(item["source"]) is not str or not item["source"].startswith("native-decision://") or
                item["actual"] not in ACTIONS or item["recommendation"] not in ("walk", "observe")):
            raise ValueError("untrusted neurovisceral receipt")
        for k in ("before_sha256", "after_sha256"):
            h = item[k]
            if type(h) is not str or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
                raise ValueError("invalid native receipt checkpoint")
        ids.append(item["id"])
    if len(ids) != len(set(ids)) or state["last_recommendation"] not in (None, "walk", "observe"):
        raise ValueError("duplicate receipt or bad recommendation")
    return state


def initial_dummy():
    return dict(schema=None, source=None, initial_native_checkpoint_sha256=None,
                completed_cycles=None, receipts=None, last_recommendation=None)


def preview(state, sample, *, desire_proxy, autonomic=None):
    """Counterfactual physiology, not actual changed vital signs."""
    validate(state)
    validate_sample(sample)
    desire = unit(desire_proxy, "authored desire")
    wave = 0.
    phase = None
    if autonomic is not None:
        from . import autonomic_bridge
        autonomic_bridge.validate_preview(autonomic)
        phase = autonomic["sample"]["phase"]
        wave = unit(autonomic["sample"]["activation_envelope"], "authored wave")
        # Wave and neurovisceral graph must use the same initial native source.
        if (autonomic["initial_native_checkpoint_sha256"]
                != state["initial_native_checkpoint_sha256"]):
            raise ValueError("wave and neurovisceral initial checkpoint differ")
    v = sample["values"]
    distress = max(v["pain"], v["fatigue"], v["sleep_pressure"])
    drive = clip(desire * (0.18 + 0.65 * wave) * (1.0 - distress))
    # A tiny authored response envelope. No native-state mutation or clinical fit.
    hr = round(clip(v["heart_bpm"] + 7.0*drive, 35., 160.), 5)
    rr = round(clip(v["breaths_per_min"] + 2.4*drive, 4., 50.), 5)
    tone = round(clip(v["muscle_tone"] + 0.09*drive), 6)
    pelvic = round(clip(0.25*v["muscle_tone"] + 0.3*drive), 6)
    vagal = round(clip(v["parasympathetic"]*(1.-v["sympathetic"])), 6)
    caudal = round(clip(0.5*(1.-v["balance"]) + 0.25*v["fatigue"]), 6)
    heat_guard = v["temperature_c"] > 37.4
    resonan_limited = v["resonan_shutter"] < 0.1 or v["resonan_attention"] > 0.95
    reserve_guard = v["azarine_budget_j"] < 100. and v["native_reserve_j"] < 100.
    # Spandar feeds a slow error monitor, not a second decisive nervous system.
    spandar_guard = v["spandar_error"] > 0.15
    unsafe = (distress >= .55 or v["energy"] < .5 or v["balance"] < .2 or
              heat_guard or reserve_guard or spandar_guard)
    recommendation = "observe" if unsafe else "walk"
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "native_checkpoint_sha256": sample["native_checkpoint_sha256"],
        "native_revision": sample["native_revision"],
        "desired_input_is_authored": desire,
        "wave_phase": phase,
        "wave_activation_is_authored": wave,
        "actual_before": deepcopy(v),
        "functional_routes": {
            "vagal_regulation_proxy": vagal,
            "sympathetic": v["sympathetic"],
            "phrenic_respiration_drive_proxy": round(clip(.6*v["co2_drive"]+.3*wave), 6),
            "sacral_visceral_proxy": round(clip(0.2*desire + 0.1*wave), 6),
            "pudendal_motor_command_proxy_not_executed": pelvic,
            "caudal_tail_stabilization_proxy": caudal,
            "resonan_attention": v["resonan_attention"],
            "spandar_prediction_error": v["spandar_error"],
            "azarine_budget_j_existing_reserve_only": v["azarine_budget_j"],
        },
        "predicted_if_actuated_not_actuated": {
            "heart_bpm": hr, "breaths_per_min": rr,
            "muscle_tone": tone, "pelvic_tone_proxy": pelvic,
        },
        "constraints": {
            "pain_fatigue_sleep_load": round(distress, 6),
            "thermal_guard": heat_guard, "resonan_attenuated": resonan_limited,
            "spandar_slow_error_guard": spandar_guard,
            "azarine_reserve_guard": reserve_guard,
            "native_action_veto_preserved": True,
        },
        "recommendation": recommendation,
        "pure_observation_only": True,
        "actual_native_physiology_changed": False,
        "actual_pelvic_contractions": 0,
        "lived_sensation_or_consciousness_inferred": False,
        "paid_api_calls": 0,
    }


def record(state, request_id, frozen, source, actual, after_sha256):
    """Update only after an authoritative completed native software receipt."""
    validate(state)
    if (type(request_id) is not str or not request_id or
            any(r["id"] == request_id for r in state["receipts"])):
        raise ValueError("duplicate or invalid neurovisceral request id")
    if (not isinstance(frozen, dict) or frozen.get("schema") != SCHEMA or
            frozen.get("source") != SOURCE or frozen.get("pure_observation_only") is not True or
            frozen.get("actual_native_physiology_changed") is not False or
            frozen.get("recommendation") not in ("walk", "observe")):
        raise ValueError("neurovisceral predecision not source-pinned")
    if type(source) is not str or not source.startswith("native-decision://") or actual not in ACTIONS:
        raise ValueError("authoritative native action receipt required")
    if type(after_sha256) is not str or len(after_sha256) != 64 or any(
            x not in "0123456789abcdef" for x in after_sha256):
        raise ValueError("native after-checkpoint required")
    next_state = deepcopy(state)
    next_state["completed_cycles"] += 1
    next_state["last_recommendation"] = frozen["recommendation"]
    next_state["receipts"].append({
        "id": request_id, "source": source,
        "before_sha256": frozen["native_checkpoint_sha256"],
        "after_sha256": after_sha256,
        "actual": actual, "recommendation": frozen["recommendation"],
    })
    next_state["receipts"] = next_state["receipts"][-MAX_RECEIPTS:]
    validate(next_state)
    return next_state


def summary(state):
    validate(state)
    return dict(enabled=True, completed_native_cycles=state["completed_cycles"],
                native_receipt_count=len(state["receipts"]),
                last_recommendation=state["last_recommendation"],
                functional_pathways=len(PATHWAYS),
                special_organs=("resonan", "spandar", "azarine"),
                new_energy_stocks=0, biological_calibration=False,
                actual_native_physiology_changed=False,
                neural_weights_changed=False, physical_actuation=False,
                model_consciousness_or_desire_claimed=False, api_calls=0)
