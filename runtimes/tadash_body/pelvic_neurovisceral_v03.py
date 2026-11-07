"""Tadash synthetic pelvis: independent somatic/autonomic/visceral channels.

Opt-in read-only analytical overlay. No nervous-system stimulation, sexual-state
inference, biology, clinical prediction, or native Tadash state mutation.
All numerical gains and thresholds are explicitly UNCALIBRATED proxies.
"""
from copy import deepcopy
from math import isfinite

from .pelvis_v01 import FIXTURES, evaluate_pelvis
from .pelvis_observer_v02 import observe_pelvis

SCHEMA = "tadash-neurovisceral-pelvis/0.3"
PATHWAYS = {
    "pudendal_somatic_S2_S4": {
        "class": "somatic_sensory_motor",
        "targets": ["perineum", "external_urethral_sphincter", "external_anal_sphincter", "distal_genital_sensation"],
        "note": "Paired left/right pudendal pathways; not the sacral parasympathetic nerve",
    },
    "pelvic_splanchnic_S2_S4": {
        "class": "parasympathetic_visceral",
        "relay": "inferior_hypogastric_plexus",
        "targets": ["bladder_detrusor", "pelvic_viscera", "uterovaginal_visceral_network"],
    },
    "hypogastric_T10_L2": {
        "class": "sympathetic_visceral",
        "relay": "inferior_hypogastric_plexus",
        "targets": ["bladder_neck", "pelvic_vasculature", "uterine_visceral_network"],
    },
    "vagus_CN_X": {
        "class": "cranial_autonomic",
        "pelvic_connection": "human_mapping_uncertain_not_assumed_as_efferent",
        "effect_in_this_model": "none",
    },
    "fictional_tail_root": {
        "class": "fictional_separate_mechanical_path",
        "targets": ["sacral_tail_anchor"],
        "physical_clearance_status": "unvalidated",
    },
}
ORGAN_TOPOLOGY = {
    "uterus": {"between": ["bladder", "rectum"], "outlet": "cervix_to_vagina"},
    "vagina": {"adjacent_to": ["bladder_urethra", "rectum"], "proximal_to": "cervix"},
    "bladder": {"outlet": "urethra", "control": "autonomic_detrusor_plus_somatic_external_sphincter"},
    "rectum": {"outlet": "anal_canal", "control": "visceral_motor_plus_somatic_external_sphincter"},
}


def _unit(x, name):
    if type(x) not in (int, float) or not isfinite(x) or not 0. <= x <= 1.:
        raise ValueError(f"{name}: finite numeric fraction from 0 to 1 required")
    return float(x)


def assess_neurovisceral_pelvis(*, profile="portrait_170_78",
                                posture_snapshot=None,
                                intra_abdominal_pressure_kpa=2.,
                                floor_activation=.3,
                                pudendal_left=.5, pudendal_right=.5,
                                sacral_parasympathetic=.5,
                                hypogastric_sympathetic=.5,
                                bladder_fill=.4, rectal_fill=.25,
                                vaginal_wall_load=.2,
                                uterine_activity=.2,
                                tail_root_load=.1,
                                vagus_direct_to_pelvis=None):
    """Evaluate one supplied or default fixture; no integration with runtime actuators.

    posture_snapshot is only supported for 250/195 V06, as in observer v0.2.
    It may be a caller-asserted source, never cryptographic proof.
    Vagal control is intentionally absent pending stronger human anatomy data.
    """
    if type(profile) is not str or profile not in FIXTURES:
        raise ValueError("unknown profile")
    if vagus_direct_to_pelvis is not None:
        raise ValueError("vagus-to-pelvis coupling unvalidated; only None is supported")
    args = {
        "floor_activation": floor_activation,
        "pudendal_left": pudendal_left, "pudendal_right": pudendal_right,
        "sacral_parasympathetic": sacral_parasympathetic,
        "hypogastric_sympathetic": hypogastric_sympathetic,
        "bladder_fill": bladder_fill, "rectal_fill": rectal_fill,
        "vaginal_wall_load": vaginal_wall_load,
        "uterine_activity": uterine_activity,
        "tail_root_load": tail_root_load,
    }
    v = {name: _unit(value, name) for name, value in args.items()}
    if type(intra_abdominal_pressure_kpa) not in (int, float) or (
        not isfinite(intra_abdominal_pressure_kpa) or not 0 <= intra_abdominal_pressure_kpa <= 25
    ):
        raise ValueError("invalid synthetic intra-abdominal pressure")
    if posture_snapshot is None:
        m = evaluate_pelvis(profile=profile,
                            intra_abdominal_pressure_kpa=float(intra_abdominal_pressure_kpa),
                            floor_activation=v["floor_activation"])
        floor = {"deflection_m": m["floor_deflection_m"],
                 "residual_load_n": m["floor_residual_load_n"],
                 "synthetic_capacity_exceeded": m["floor_saturated"]}
        provenance = "synthetic_pelvis_fixture_no_posture_observation"
        phase = None
    else:
        if profile != "runtime_250_195":
            raise ValueError("posture snapshots cannot be rescaled to portrait profile")
        if type(posture_snapshot) is not dict:
            raise ValueError("posture snapshot must be a mapping")
        m = observe_pelvis(posture_snapshot, profile=profile,
                           intra_abdominal_pressure_kpa=float(intra_abdominal_pressure_kpa),
                           floor_activation=v["floor_activation"])
        floor = dict(m["pelvic_floor"])
        provenance = "caller_asserted_V06_source_not_authenticated"
        phase = m["gait_phase"]

    # Separable test signals, NOT human quantitative physiology.
    pudendal_avg = (v["pudendal_left"] + v["pudendal_right"]) / 2.
    external_sphincter_proxy = round(.7 * pudendal_avg + .3 * v["floor_activation"], 6)
    detrusor_drive_proxy = round(v["sacral_parasympathetic"] * v["bladder_fill"], 6)
    sympathetic_vasomotor_proxy = round(v["hypogastric_sympathetic"], 6)
    floor_ratio = floor["deflection_m"] / FIXTURES[profile].max_deflection_m
    reasons = []
    if floor["synthetic_capacity_exceeded"]:
        reasons.append("synthetic_floor_load_limit")
    if v["bladder_fill"] >= .85 and external_sphincter_proxy < .3:
        reasons.append("low_synthetic_somatic_control_reserve_at_high_fill")
    if abs(v["pudendal_left"] - v["pudendal_right"]) > .65:
        reasons.append("marked_paired_somatic_asymmetry")
    if v["tail_root_load"] > .7 and floor_ratio > .6:
        reasons.append("tail_load_and_floor_strain_compete_clearance_unverified")
    if posture_snapshot is not None and m["guard"] == "review_required":
        for original_reason in m.get("guard_reasons", []):
            if original_reason not in reasons:
                reasons.append(original_reason)
    return {
        "schema": SCHEMA, "scope": "uncalibrated_synthetic_readonly_neural_compartments",
        "profile": profile,
        "mass_kg": FIXTURES[profile].mass_kg,
        "stature_m": FIXTURES[profile].stature_m,
        "posture_source": provenance, "posture_phase": phase,
        "pathways": deepcopy(PATHWAYS), "organ_topology": deepcopy(ORGAN_TOPOLOGY),
        "pelvic_floor": floor,
        "somatic": {"pudendal_left_proxy": v["pudendal_left"],
                    "pudendal_right_proxy": v["pudendal_right"],
                    "external_sphincter_support_proxy": external_sphincter_proxy},
        "autonomic": {"sacral_parasympathetic_proxy": v["sacral_parasympathetic"],
                      "detrusor_drive_proxy": detrusor_drive_proxy,
                      "hypogastric_sympathetic_proxy": v["hypogastric_sympathetic"],
                      "pelvic_vasomotor_proxy": sympathetic_vasomotor_proxy,
                      "vagal_direct_transfer": None},
        "viscera": {"bladder_fill_proxy": v["bladder_fill"],
                   "rectal_fill_proxy": v["rectal_fill"],
                   "vaginal_wall_load_proxy": v["vaginal_wall_load"],
                   "uterine_activity_proxy": v["uterine_activity"]},
        "tail_root_load_proxy": v["tail_root_load"],
        "guard": "review_required" if reasons else "within_synthetic_fixture",
        "guard_reasons": reasons,
        "anatomical_clearance_validated": False,
        "native_cycles_caused": 0, "actuation_authorized": False,
        "clinical_validity": False, "sexual_state_inferred": False,
        "subjective_sensation_inferred": False,
        "reproductive_function_verified": False,
    }
