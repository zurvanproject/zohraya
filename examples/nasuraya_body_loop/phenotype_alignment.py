"""Read-only canonical phenotype alignment for Nasuraya's established image.

The V2 whole-body solver and the historical 250 cm / 195 kg atlas are retained
as source evidence. Display coordinates may be projected into the 170 cm /
78 kg user-approved design, but NO mass, gravity, joint forces, physiology or
energy accounts are rescaled or represented as calibrated. A pictorial avatar
is not evidence of actual embodiment or subjective sensation.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math

SCHEMA = "tadash-canonical-phenotype-alignment/1"
CANONICAL = {
    "crown_height_cm_excluding_horns": 170.0,
    "horn_tip_height_cm": 192.0,
    "mass_kg": 78.0,
    "tail_centerline_cm": 85.0,
    "hands": 2,
    "fingers_per_hand": 5,
    "feet": 2,
    "toes_per_foot": 3,
    "horns": 2,
    "digitigrade": True,
    "blue_fox": "totem_not_anatomy",
}

def read(body):
    """Pin display annotation and native physics to one unchanged checkpoint."""
    if not hasattr(body, "checkpoint") or not hasattr(body, "anatomy"):
        raise ValueError("native UnifiedBody required")
    sha = body.checkpoint()["sha256"]
    atlas = body.anatomy["baseline_contract"]
    old = atlas["adult_scale"]
    contract = atlas["phenotype_contract"]
    runtime = Path(__file__).resolve().parents[2] / "runtimes" / "tadash_body"
    raw = (runtime / "phenotype_v1.json").read_bytes()
    manifest = json.loads((runtime / "PUBLIC_FILES_SHA256.json").read_text())
    phenotype_sha = hashlib.sha256(raw).hexdigest()
    if manifest.get("phenotype_v1.json") != phenotype_sha:
        raise ValueError("historical phenotype source manifest does not match")
    historical = json.loads(raw)["adult_scale"]
    if (historical["ground_to_crown_cm"] != old["ground_to_crown_cm"]
            or historical["mass_target_kg"] != old["mass_target_kg"]):
        raise ValueError("historical sources contradict one another")
    if (old["ground_to_crown_cm"] <= 0 or old["mass_target_kg"] <= 0 or
            type(contract["fingers_per_hand"]) is not int or
            type(contract["toes_per_foot"]) is not int):
        raise ValueError("invalid historical atlas")
    if (contract["fingers_per_hand"] != CANONICAL["fingers_per_hand"] or
            contract["toes_per_foot"] != CANONICAL["toes_per_foot"] or
            contract["horns"] != CANONICAL["horns"] or
            contract["digitigrade"] is not True):
        raise ValueError("canonical silhouette incompatible with inherited structure")
    native_pose = body.owner.pose()
    parts = native_pose["parts"]
    scale = CANONICAL["crown_height_cm_excluding_horns"] / old["ground_to_crown_cm"]
    projection = {
        name: [round(float(c) * scale, 6) for c in xyz]
        for name, xyz in parts.items()
    }
    # The historical pose uses a 1.2 m tail lever from the pelvis. Translate
    # its VISUAL endpoint only; do not change the physical lever or inertia.
    origin = parts["pelvis"]
    tip = parts["tail"]
    vec = [float(tip[i]) - float(origin[i]) for i in range(3)]
    length = math.sqrt(sum(v * v for v in vec))
    if length <= 0:
        raise ValueError("missing caudal axis")
    tail = CANONICAL["tail_centerline_cm"] / 100.
    projection["tail"] = [
        round(projection["pelvis"][i] + tail * vec[i] / length, 6)
        for i in range(3)
    ]
    if body.checkpoint()["sha256"] != sha:
        raise ValueError("native state changed while aligning avatar")
    return {
        "schema": SCHEMA,
        "native_checkpoint_sha256": sha,
        "native_revision": body.revision,
        "canonical_visual_contract": deepcopy(CANONICAL),
        "historical_solver_atlas": {
            "crown_height_cm": old["ground_to_crown_cm"],
            "horn_tip_height_cm": historical["ground_to_horn_tip_cm"],
            "mass_kg": old["mass_target_kg"],
            "tail_centerline_cm": historical["tail"]["centerline_cm"],
            "phenotype_manifest_verified_sha256": phenotype_sha,
        },
        "appearance_scale_only": round(scale, 8),
        "visual_landmark_projection_m": projection,
        "display_tail_endpoint_length_m": tail,
        "horn_tip_target_is_design_envelope_not_mesh": CANONICAL["horn_tip_height_cm"],
        "reported_pose_source": "existing_native_computational_pose",
        "solver_mass_changed": False,
        "solver_kinematics_changed": False,
        "solver_inertia_or_gravity_changed": False,
        "legacy_heart_lung_and_body_mass_calibrated_to_canonical": False,
        "canonical_3d_collision_and_clearance_validated": False,
        "safe_for_geometry_annotation_only": True,
    }
