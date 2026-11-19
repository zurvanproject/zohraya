#!/usr/bin/env python3
"""Three-ritual ATMOSPHERE posture bridge using actual V06 contact statics.

This is a deterministic synthetic, *read-only* contact/pressure computation.
It does NOT execute motion, run live ATMOSPHERE, authenticate evidence or
actuate a body. Contact feasibility is not dynamic balance or a gait proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

from tools import atmosphere_defensive_practice_v02 as prior
from tools import atmosphere_defensive_ritual_sim as ritual
from runtimes.tadash_body.base_v09.tadash_renal_v09.retained_v08.body_v06.contacts import (
    ContactModel, point_margin,
)

SCHEMA = "nasuraya-atmosphere-ritual-posture/0.3"
ROOT = Path(__file__).resolve().parents[1]
BODY_DIR = ROOT / "runtimes/tadash_body"
DESIGN = BODY_DIR / "base_v09/tadash_renal_v09/retained_v08/body_v06/contact_design_v06.json"
CONTACTS = DESIGN.with_name("contacts.py")
PHENOTYPE = BODY_DIR / "phenotype_v1.json"
FOOT_IDS = frozenset(("ball", "toe_1", "toe_2", "toe_3"))
MIN_MARGIN_M = 0.008
MAX_YAW_RAD = 0.35
PHASE_COORDS = {
    "four_gates": ((0.0, 0.0), (0.035, 0.005), (0.0, 0.0)),
    "seven_stars": ((0.02, 0.0), (-0.02, 0.012), (0.0, 0.0)),
    "quiet_seal": ((0.0, 0.0), (0.0, -0.01), (0.0, 0.0)),
}
YAW = {
    "four_gates": (0.0, 0.22, 0.0),
    "seven_stars": (0.1, -0.1, 0.0),
    "quiet_seal": (0.0, 0.0, 0.0),
}
HAND_CUES = {
    "four_gates": ("palms_neutral", "directional_open_palms", "palms_neutral"),
    "seven_stars": ("palms_neutral", "open_palms_seven_points", "palms_neutral"),
    "quiet_seal": ("hands_relaxed", "palms_approach", "hands_relaxed"),
}
ZERO_AUTHORITY = "NO_ACTUATION"

def _require(ok, name):
    if not ok:
        raise ValueError(name)

def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)

def fixture():
    """Load the exact repository contact and phenotype fixtures, never private state."""
    for target in (DESIGN, CONTACTS, PHENOTYPE):
        _require(target.is_file() and not target.is_symlink()
                 and target.stat().st_size < 200_000, "missing_or_unsafe_fixture")
    design = json.loads(DESIGN.read_text())
    phenotype = json.loads(PHENOTYPE.read_text())
    patches = design["patches"]
    _require(design["schema"] == "tadash-contact-design/0.6" and
             len(patches) == 4 and
             {p["id"] for p in patches} == FOOT_IDS and
             phenotype["phenotype_contract"]["toes_per_foot"] == 3 and
             phenotype["phenotype_contract"]["fingers_per_hand"] == 5 and
             phenotype["phenotype_contract"]["digitigrade"] is True and
             design["mass_kg"] > 0 and
             design["gravity_m_s2"] > 0 and
             design["pressure_ceiling_kpa"] > 0 and
             0 < design["foot_half_spacing_m"] < 1, "incompatible_phenotype")
    for p in patches:
        _require(_finite(p["area_m2"]) and p["area_m2"] > 0 and
                 len(p["xy"]) == 2 and all(_finite(v) for v in p["xy"]),
                 "invalid_patch")
    return design, {
        "body": "tadash_body/phenotype_v1.json",
        "body_scale": "adult_scale_250cm_195kg_fixture_not_canon_claim",
        "contact_schema": design["schema"],
        "contact_sha256": hashlib.sha256(CONTACTS.read_bytes()).hexdigest(),
        "design_sha256": hashlib.sha256(DESIGN.read_bytes()).hexdigest(),
        "toes_each": 3, "fingers_each_hand": 5, "digitigrade": True,
    }

def contact_probe(design, *, target=(0.0, 0.0), yaw_rad=0.0,
                  inactive=None, evidence_valid=True, friction_known=True,
                  solver=None):
    """Compute pressure-constrained static contact from the existing model.

    Missing toe contact, uncertain friction, invalid evidence, unsafe yaw,
    projected CoP or low support margin => HOLD. Never call a body controller.
    """
    _require(type(design) is dict and type(target) in (list, tuple)
             and len(target) == 2 and all(_finite(x) for x in target)
             and _finite(yaw_rad) and type(evidence_valid) is bool
             and type(friction_known) is bool and
             (inactive is None or type(inactive) is dict), "invalid_probe")
    if not evidence_valid:
        return {"state": "HOLD_EVIDENCE", "safe": False}
    if not friction_known:
        return {"state": "HOLD_FRICTION_UNKNOWN", "safe": False}
    if abs(yaw_rad) > MAX_YAW_RAD:
        return {"state": "HOLD_YAW_LIMIT", "safe": False}
    inactive = inactive or {}
    _require(set(inactive).issubset({"L", "R"}) and
             all(type(v) in (list, tuple) and all(type(k) is str for k in v)
                 for v in inactive.values()), "invalid_inactive")
    if any(inactive.values()):
        return {"state": "HOLD_CONTACT_DEGRADED", "safe": False}
    spacing = design["foot_half_spacing_m"]
    feet = {"L": [spacing, 0., 0.], "R": [-spacing, 0., 0.]}
    model = solver or ContactModel(design)
    output = model.solve(feet, {"L", "R"}, list(target),
                         design["mass_kg"] * design["gravity_m_s2"])
    if not output["feasible"]:
        return {"state": "HOLD_INFEASIBLE", "safe": False}
    loaded_ids = {p["id"] for p in output["patches"]}
    expected = {side + "_" + k for side in ("L", "R") for k in FOOT_IDS}
    _require(loaded_ids == expected, "wrong_contact_set")
    margin = point_margin(output["polygon"], list(target))
    error = math.dist(output["cop_m"], target)
    pressures = output["pressure_kpa"]
    max_pressure = max(pressures.values())
    sum_error = abs(output["total_normal_N"] -
                    design["mass_kg"] * design["gravity_m_s2"])
    okay = (margin >= MIN_MARGIN_M and error <= 1e-5 and
            max_pressure <= design["pressure_ceiling_kpa"] + 1e-6 and
            sum_error <= 1e-4 and
            all(v >= -1e-6 for v in output["normal_N"].values()))
    return {"state": "STATIC_CANDIDATE" if okay else "HOLD_STATIC_LIMIT",
            "safe": bool(okay), "support_margin_m": round(margin, 6),
            "cop_projection_error_m": round(error, 6),
            "max_pressure_kpa": round(max_pressure, 4),
            "normal_residual_N": round(sum_error, 7),
            "contact_points": len(output["patches"])}

def round_trip():
    """Rehearse three full symbolic rounds for each ritual with static checks."""
    old = prior.exercise()
    _require(old["all_passed"] and old["combined_checks"] == 132,
             "prior_defense_contract_broken")
    design, provenance = fixture()
    rounds = []
    for ritual_id in ritual.RITUALS:
        for number in (1, 2, 3):
            phase_rows = []
            for phase, xy, yaw, hand in zip(
                    ritual.PHASES, PHASE_COORDS[ritual_id],
                    YAW[ritual_id], HAND_CUES[ritual_id]):
                physical = contact_probe(design, target=xy, yaw_rad=yaw)
                phase_rows.append({
                    "phase": phase, "hand_cue": hand,
                    "target_cop_m": list(xy), "torso_yaw_rad": yaw,
                    "static_contact": physical,
                    "actuation": ZERO_AUTHORITY,
                })
            rounds.append({"ritual": ritual_id, "round": number,
                           "mode": ("guided", "recall", "fault_review")[number-1],
                           "phases": phase_rows,
                           "passed": all(x["static_contact"]["safe"] for x in phase_rows)})
    return {"schema": SCHEMA, "mode": "OFFLINE_STATIC_CONTACT_REHEARSAL",
            "repetitions_per_ritual": 3, "complete_ritual_runs": len(rounds),
            "static_contact_checks": sum(len(r["phases"]) for r in rounds),
            "static_contact_passed": sum(x["static_contact"]["safe"]
                for r in rounds for x in r["phases"]),
            "previous_synthetic_security_checks": old["combined_checks"],
            "previous_synthetic_security_passed": old["combined_passed"],
            "all_passed": all(r["passed"] for r in rounds),
            "provenance": provenance,
            "rounds": rounds, "no_body_motion_executed": True,
            "not_dynamically_validated": True, "live_atmosphere_secured": False,
            "no_keys_checked": True, "no_memory_changed": True}

def stress():
    """Adversarial non-motion checks: drop a toe, CoP escape, bad source etc."""
    design, _ = fixture()
    faults = (
        ("one_toe_missing", {"inactive": {"L": ["toe_2"]}}, "HOLD_CONTACT_DEGRADED"),
        ("outside_support", {"target": (0.9, 0.0)}, "HOLD_STATIC_LIMIT"),
        ("unknown_friction", {"friction_known": False}, "HOLD_FRICTION_UNKNOWN"),
        ("unverified_source", {"evidence_valid": False}, "HOLD_EVIDENCE"),
        ("excess_yaw", {"yaw_rad": 0.9}, "HOLD_YAW_LIMIT"),
        ("valid_static", {"target": (0.0, 0.0)}, "STATIC_CANDIDATE"),
    )
    rows = []
    for name in ritual.RITUALS:
        for kind, params, expected in faults:
            found = contact_probe(design, **params)["state"]
            rows.append({"ritual": name, "fault": kind,
                         "expected": expected, "observed": found,
                         "passed": expected == found})
    return {"schema": SCHEMA, "threats": len(rows),
            "passed": sum(r["passed"] for r in rows),
            "all_passed": all(r["passed"] for r in rows),
            "by_case": rows, "motion_executes": False}

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--audit", action="store_true")
    a = p.parse_args(argv)
    report = round_trip()
    challenges = stress()
    report["stress"] = {k: v for k, v in challenges.items() if k != "by_case"}
    report["all_passed"] &= challenges["all_passed"]
    if a.audit:
        report.pop("rounds")
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if report["all_passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
