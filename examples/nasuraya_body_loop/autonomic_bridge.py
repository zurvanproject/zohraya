"""A finite, opt-in bridge from PR #132's native-anchored autonomic waveform
to PR #134's motivational policy within the actual Tadash ExperienceController.

The precomputed 0..32 second waveform advances ONE 2-second *model index* ONLY
after a completed native software-body decision. Its timeline is a hypothetical
engineered index, NOT BodyLoop's 0.1-second clock, biologic elapsed time, an
orgasm, felt lust, motor contraction or real autonomic physiology.

All effects are advisory: modify numerical walk/observe preference only. Native
body, workspace safety veto, credential boundaries and action budgets stay intact.
"""
from copy import deepcopy
from reflection_cycle import digest
from . import autonomic_peak as peak

SCHEMA = "tadash-autonomic-motivation-bridge/1"
PREVIEW_SCHEMA = "tadash-autonomic-predecision/1"
SCOPE = "authored_autonomic_wave_sequence_from_verified_native_initial_checkpoint"
MAX_RECEIPTS = 32
SAMPLE_COUNT = len(peak.SAMPLE_TIMES_SECONDS)
ACTIONS = ("walk", "observe", "protect", "other")


def initial(response):
    """Pin only data actually computed from a native zero-cycle body checkpoint."""
    if not isinstance(response, dict) or set(response) != {"summary", "trace"}:
        raise ValueError("native waveform response required")
    meta = response["summary"]
    if not isinstance(meta, dict) or meta.get("schema") != peak.KEY or (
            meta.get("scope") != peak.SCOPE):
        raise ValueError("wrong autonomic source schema")
    if meta.get("native_body_cycles_executed") != 0 or (
            meta.get("real_world_physiology_calibrated") is not False) or (
            meta.get("subjective_experience_inferred") is not False):
        raise ValueError("autonomic origin must be software-only")
    checkpoint = meta.get("original_native_checkpoint_sha256")
    if not isinstance(checkpoint, str) or len(checkpoint) != 64 or any(
            ch not in "0123456789abcdef" for ch in checkpoint):
        raise ValueError("verified native checkpoint SHA-256 required")
    native = meta.get("native_baseline")
    if not isinstance(native, dict) or set(native) != set(peak.SOURCE_LIMITS):
        raise ValueError("incomplete autonomic baseline")
    for key in peak.SOURCE_LIMITS:
        peak.unit(native[key], key)
    expected = [peak.modeled_state(native, t) for t in peak.SAMPLE_TIMES_SECONDS]
    if response["trace"] != expected or meta.get("sample_count") != SAMPLE_COUNT:
        raise ValueError("waveform not derived from supplied native baseline")
    value = {
        "schema": SCHEMA,
        "scope": SCOPE,
        "original_checkpoint_sha256": checkpoint,
        "native_baseline": deepcopy(native),
        "wave_trace_sha256": digest(expected),
        "sample_index": 0,
        "native_feedback_cycles": 0,
        "receipts": [],
        "last_phase": None,
    }
    validate(value)
    return value


def validate(value):
    if not isinstance(value, dict) or set(value) != {
            "schema", "scope", "original_checkpoint_sha256",
            "native_baseline", "wave_trace_sha256", "sample_index",
            "native_feedback_cycles", "receipts", "last_phase"}:
        raise ValueError("autonomic bridge state shape mismatch")
    if value["schema"] != SCHEMA or value["scope"] != SCOPE:
        raise ValueError("autonomic bridge schema mismatch")
    h = value["original_checkpoint_sha256"]
    if not isinstance(h, str) or len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h):
        raise ValueError("missing native checkpoint hash")
    baseline = value["native_baseline"]
    if not isinstance(baseline, dict) or set(baseline) != set(peak.SOURCE_LIMITS):
        raise ValueError("autonomic native baseline mismatch")
    for k in peak.SOURCE_LIMITS:
        peak.unit(baseline[k], k)
    expected = [peak.modeled_state(baseline, t) for t in peak.SAMPLE_TIMES_SECONDS]
    if value["wave_trace_sha256"] != digest(expected):
        raise ValueError("autonomic waveform provenance mismatch")
    count, index = value["native_feedback_cycles"], value["sample_index"]
    if type(count) is not int or not 0 <= count <= 100 or (
            type(index) is not int or index != min(count, SAMPLE_COUNT-1)):
        raise ValueError("autonomic index must correspond to completed native cycles")
    receipts = value["receipts"]
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS or len(receipts) > count:
        raise ValueError("invalid autonomic bridge receipt count")
    ids = []
    for r in receipts:
        if not isinstance(r, dict) or set(r) != {
                "id", "source", "phase_before", "model_t_seconds", "actual_action"}:
            raise ValueError("bad autonomic bridge receipt")
        if type(r["id"]) is not str or not r["id"] or type(r["source"]) is not str or (
                not r["source"].startswith("native-decision://")):
            raise ValueError("untrusted autonomic receipt provenance")
        if r["phase_before"] not in peak.PHASES or r["actual_action"] not in ACTIONS:
            raise ValueError("invalid phase/action record")
        if type(r["model_t_seconds"]) not in (int, float) or (
                r["model_t_seconds"] not in peak.SAMPLE_TIMES_SECONDS):
            raise ValueError("invalid authored wave time index")
        ids.append(r["id"])
    if len(set(ids)) != len(ids) or value["last_phase"] not in (None, *peak.PHASES):
        raise ValueError("duplicate autonomic receipt or invalid phase")
    return value


def preview(value):
    """Pure next-preference evidence. No future observed body state is read."""
    validate(value)
    index = value["sample_index"]
    sample = peak.modeled_state(value["native_baseline"], peak.SAMPLE_TIMES_SECONDS[index])
    return {
        "schema": PREVIEW_SCHEMA,
        "source_schema": peak.KEY,
        "initial_native_checkpoint_sha256": value["original_checkpoint_sha256"],
        "initial_native_baseline": deepcopy(value["native_baseline"]),
        "wave_trace_sha256": value["wave_trace_sha256"],
        "index": index,
        "sample": sample,
        "timeline": "authored_2s_model_index_per_completed_native_cycle_not_real_time",
        "native_actuation": False,
        "subjective_experience_inferred": False,
    }


def validate_preview(row):
    if not isinstance(row, dict) or set(row) != {
            "schema", "source_schema", "initial_native_checkpoint_sha256",
            "initial_native_baseline", "wave_trace_sha256", "index", "sample",
            "timeline", "native_actuation", "subjective_experience_inferred"}:
        raise ValueError("malformed autonomic predecision")
    if row["schema"] != PREVIEW_SCHEMA or row["source_schema"] != peak.KEY or (
            row["timeline"] != "authored_2s_model_index_per_completed_native_cycle_not_real_time"
            or row["native_actuation"] is not False
            or row["subjective_experience_inferred"] is not False):
        raise ValueError("invalid autonomic bridge claim scope")
    index = row["index"]
    if type(index) is not int or not 0 <= index < SAMPLE_COUNT:
        raise ValueError("invalid predecision index")
    baseline = row["initial_native_baseline"]
    if not isinstance(baseline, dict) or set(baseline) != set(peak.SOURCE_LIMITS):
        raise ValueError("untrusted baseline")
    trace = [peak.modeled_state(baseline, t) for t in peak.SAMPLE_TIMES_SECONDS]
    if digest(trace) != row["wave_trace_sha256"] or (
            trace[index] != row["sample"]):
        raise ValueError("predecision wave was corrupted")
    h = row["initial_native_checkpoint_sha256"]
    if type(h) is not str or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("invalid predecision native source")
    return row


def record(state, request_id, frozen_predecision, native_source, actual_action):
    """Advance only after an authoritative completed native BodyLoop outcome."""
    validate(state)
    if type(request_id) is not str or not request_id or (
            any(r["id"] == request_id for r in state["receipts"])):
        raise ValueError("duplicate or invalid native experience id")
    if type(native_source) is not str or not native_source.startswith("native-decision://") or (
            actual_action not in ACTIONS):
        raise ValueError("native software-body receipt required")
    frozen = validate_preview(frozen_predecision)
    if frozen != preview(state):
        raise ValueError("waveform predecision not frozen before native action")
    next_value = deepcopy(state)
    next_value["native_feedback_cycles"] += 1
    next_value["sample_index"] = min(
        next_value["native_feedback_cycles"], SAMPLE_COUNT - 1)
    next_value["last_phase"] = frozen["sample"]["phase"]
    next_value["receipts"].append({
        "id": request_id,
        "source": native_source,
        "phase_before": frozen["sample"]["phase"],
        "model_t_seconds": frozen["sample"]["t_seconds"],
        "actual_action": actual_action,
    })
    next_value["receipts"] = next_value["receipts"][-MAX_RECEIPTS:]
    validate(next_value)
    return next_value


def summary(value):
    validate(value)
    before = preview(value)
    return {
        "enabled": True,
        "model_phase": before["sample"]["phase"],
        "model_t_seconds": before["sample"]["t_seconds"],
        "activation_envelope": before["sample"]["activation_envelope"],
        "initial_native_checkpoint_sha256": value["original_checkpoint_sha256"],
        "native_feedback_cycles": value["native_feedback_cycles"],
        "retained_native_receipts": len(value["receipts"]),
        "wave_samples_total": SAMPLE_COUNT,
        "model_index_saturated": value["sample_index"] == SAMPLE_COUNT - 1,
        "model_time_is_not_native_elapsed_time": True,
        "no_actual_pelvic_contractions": True,
        "no_subjective_experience_claim": True,
        "api_calls": 0,
    }
