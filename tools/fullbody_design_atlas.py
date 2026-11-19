"""Reproducible whole-body design registry for fictional Tadash/Nasuraya.

Inventory and GAPS only. Does not create physiology, a viable biological body,
live neural functions, 3D collision geometry or physical actuators. Windows-safe.
No network, credentials, API calls, model changes or modification of native ledgers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

SCHEMA = "nasuraya.whole_body_design.v1"
SOURCE_BLOBS = {
    "runtimes/tadash_body/anatomy_systems_v01.json": "0c3bd45e78d430b2ac91ddb80a5ba8987f73a397",
    "runtimes/tadash_body/phenotype_v1.json": "61f61176c50379041ccbebf7a2f5d36824aa3a5a",
}
CANONICAL_TARGET = {
    "ground_to_crown_cm": 170,
    "ground_to_horn_tip_cm": 192,
    "mass_kg": 78,
    "tail_centerline_cm": 85,
    "tail_vertebrae_design_count_unvalidated": 18,
    "horn_count": 2,
    "hands": 2,
    "fingers_per_hand": 5,
    "feet": 2,
    "toes_per_digitigrade_foot": 3,
    "aesthetic_contract": "feminine silhouette; strength bounded by internal load paths",
}
# Every field must be backed by a separate geometric/mechanical measurement,
# model with declared assumptions, or test receipt before it can be promoted.
FIELDS = (
    "volumetric_geometry", "tissue_layers", "skeletal_and_fascial_mount",
    "arterial_supply", "venous_return", "lymphatic_drainage",
    "afferent_innervation", "efferent_innervation", "autonomic_regulation",
    "mechanical_load_or_compliance", "heat_water_energy_budget",
    "sensor_and_control_loop", "clearance_and_collision", "validation",
)
# Anatomical / physical components absent as separately modelled nodes in the
# historical 97-node topology. These are needed before a full physical atlas.
EXTRA_PARTS = (
    ("cranium_and_foramina", "head", ("cortex", "brainstem")),
    ("horn_bony_core_l", "left horn", ("resonan_l",)),
    ("horn_bony_core_r", "right horn", ("resonan_r",)),
    ("horn_innervated_root_l", "left horn root", ("resonan_l", "cortex")),
    ("horn_innervated_root_r", "right horn root", ("resonan_r", "cortex")),
    ("horn_keratin_sheaths", "horn exteriors", ("resonan_l", "resonan_r")),
    ("cervical_spine_and_fascia", "neck", ("spinal_cord", "brachial")),
    ("cranial_vessels_and_airway_clearance", "head and neck", ("aorta", "trachea")),
    ("costal_and_sternal_frames", "thorax", ("ra", "rv", "thymus")),
    ("coronaries_valves_myocardium", "heart", ("ra", "rv", "la", "lv")),
    ("breathing_parenchyma_and_pleura", "thorax", ("alveoli", "diaphragm")),
    ("brachiocephalic_vein_clearance", "upper mediastinum", ("spandar", "svc", "thymus")),
    ("bilateral_brachial_plexus_tracks", "shoulder to hands", ("brachial", "hand_contacts")),
    ("shoulder_elbow_wrist_joint_chains", "upper extremities", ("bone", "muscle", "tendon")),
    ("ten_individual_hand_digits", "hands", ("hand_contacts",)),
    ("palm_pad_receptor_networks", "hands", ("hand_contacts", "brachial")),
    ("skin_fur_mosaic_and_sweat", "skin", ("skin_barrier", "sweat_glands")),
    ("whole_body_microcirculation", "all tissue", ("vascular_endothelium", "aorta", "ivc")),
    ("lymphatic_repair_routes", "all tissue", ("lymph_nodes", "lymph_collectors")),
    ("spine_vertebrae_and_discs", "axial skeleton", ("bone", "spinal_cord")),
    ("sacral_caudo_pelvic_mount", "tail root", ("sacrum", "tail_root", "pelvic_floor")),
    ("caudal_vertebral_chain", "tail", ("tail", "tail_root", "caudal_nerve")),
    ("caudal_muscle_tendon_fascia", "tail", ("tail", "muscle", "tendon")),
    ("caudal_vascular_plexus", "tail", ("tail", "aorta", "ivc")),
    ("caudal_sensory_motor_plexus", "tail", ("tail", "caudal_nerve", "pudendal")),
    ("pelvis_abdominal_nerve_clearances", "pelvis", ("pudendal", "pelvic_floor", "sacrum")),
    ("reproductive_pelvic_compartment_geometry", "pelvis", ("uterus", "vagina", "bladder", "rectum")),
    ("hip_knee_hock_joint_chains", "lower limbs", ("bone", "muscle", "foot_contacts")),
    ("three_toe_foot_pad_l", "left foot", ("foot_contacts", "sciatic")),
    ("three_toe_foot_pad_r", "right foot", ("foot_contacts", "sciatic")),
    ("achilles_and_digitigrade_tendon_load", "hindlimbs", ("tendon", "foot_contacts")),
    ("regional_sensory_nociceptor_mesh", "whole body", ("spinal_cord", "skin_barrier")),
    ("spandar_thymic_capsule_footprint", "anterior thymic capsule", ("spandar", "thymus", "trachea")),
    ("azarine_fascial_heat_perfusion_bed", "left flank", ("azarine", "kidney_l", "spleen")),
    ("resonan_crossmodal_signal_guard", "horn roots", ("resonan_l", "resonan_r", "vestibular")),
)
PACKAGES = (
    ("01", "Craniofacial, skull, horns, sight and hearing", (7, 8, 11, 12)),
    ("02", "Axial skeleton, costal frame, tissue and dermal envelope", (4, 10)),
    ("03", "Bilateral hands and upper-limb force/sensation", (10, 11, 7)),
    ("04", "Sacrum, 18-segment caudal design and tail load", (10, 11)),
    ("05", "Digitigrade legs, hocks, three-toe pads and gait", (10, 11)),
    ("06", "Arterial, venous, capillary, blood and lymph", (2, 4, 5)),
    ("07", "Brain, spinal cord, peripheral and autonomic pathways", (11, 7)),
    ("08", "Heart, lungs, respiration and circulation", (5,)),
    ("09", "Gastrointestinal, hepatic, pancreatic and renal", (3, 6)),
    ("10", "Endocrine, immunity, metabolism and tissue repair", (1, 2, 4)),
    ("11", "Pelvic, urinary and reproductive compartments", (3, 9, 11)),
    ("12", "Resonan, Spandar and Azarine: supports and limits", (12, 4, 5)),
    ("13", "Integrated contact, heat, mass, energy and fail-safes", tuple(range(1, 13))),
)


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def read_pinned(repo_root: Path) -> tuple[dict, dict, dict]:
    parsed = {}
    fingerprints = {}
    for filename, expected in SOURCE_BLOBS.items():
        raw = (repo_root / filename).read_bytes()
        found = git_blob_sha(raw)
        if found != expected:
            raise ValueError("historical_source_mismatch:" + filename)
        parsed[filename] = json.loads(raw.decode("utf-8"))
        fingerprints[filename] = {
            "git_blob_sha1": found,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return (parsed["runtimes/tadash_body/anatomy_systems_v01.json"],
            parsed["runtimes/tadash_body/phenotype_v1.json"],
            fingerprints)


def source_contract(anatomy: dict, phenotype: dict) -> None:
    if anatomy.get("schema") != "tadash-twelve-system-anatomy/0.1":
        raise ValueError("anatomy_schema_changed")
    historical = phenotype["adult_scale"]
    baseline = anatomy["baseline_contract"]
    if (historical["ground_to_crown_cm"] != 250 or
            historical["mass_target_kg"] != 195 or
            baseline["adult_scale"]["ground_to_crown_cm"] != 250 or
            baseline["adult_scale"]["mass_target_kg"] != 195):
        raise ValueError("legacy_scale_unknown")
    fp = phenotype["phenotype_contract"]
    if (fp["fingers_per_hand"] != 5 or fp["toes_per_foot"] != 3 or
            fp["horns"] != 2 or not fp["digitigrade"] or
            not fp["sacral_tail"] or
            not fp["resonan_sensor_at_horn_roots"] or
            not fp["azarine_left_flank"] or
            not fp["spandar_on_thymic_capsule"]):
        raise ValueError("legacy_structure_contract_changed")


def build_registry(anatomy: dict, phenotype: dict, fingerprints: dict) -> dict:
    source_contract(anatomy, phenotype)
    systems = anatomy["systems"]
    nodes = anatomy["nodes"]
    routes = anatomy["routes"]
    if len(systems) != 12 or len(nodes) != 97 or len(routes) != 31:
        raise ValueError("baseline_inventory_count_changed")
    stages = [s.get("stage") for s in systems]
    if stages != list(range(1, 13)):
        raise ValueError("system_stages_invalid")
    seen = {}
    for node in nodes:
        key, stage = node.get("id"), node.get("system_stage")
        if not isinstance(key, str) or not key.isidentifier() or key in seen:
            raise ValueError("node_identity_invalid")
        if stage not in stages or not isinstance(node.get("region"), str):
            raise ValueError("node_stage_or_region_invalid")
        seen[key] = node
    for system in systems:
        actual = {n["id"] for n in nodes if n["system_stage"] == system["stage"]}
        declared = system.get("organs")
        if not isinstance(declared, list) or set(declared) != actual or len(declared) != len(actual):
            raise ValueError("system_node_membership_invalid")
    for route in routes:
        if (not isinstance(route.get("path"), list) or
                len(route["path"]) < 2 or
                any(entry not in seen for entry in route["path"])):
            raise ValueError("unresolved_route")
    new_parts = []
    for key, region, anchors in EXTRA_PARTS:
        if any(anchor not in seen for anchor in anchors):
            raise ValueError("missing_extra_part_anchor:" + key)
        new_parts.append({
            "part_id": key,
            "region": region,
            "linked_existing_nodes": list(anchors),
            "status": "design_gap_not_a_3d_body",
            "needs_evidence_for": list(FIELDS),
        })
    registered_nodes = [
        {
            "id": n["id"], "system_stage": n["system_stage"],
            "region": n["region"], "name_fa": n.get("name_fa", ""),
            "source_role_fa": n.get("role_fa", ""),
            "source_geometry_status": n.get("geometry_status"),
            "physical_status": "regional_topology_only",
            "engineering_fields": {name: "unverified" for name in FIELDS},
        }
        for n in nodes
    ]
    packages = [
        {
            "workstream": ident, "name": name,
            "covered_systems": list(stages),
            "node_count": sum(n["system_stage"] in stages for n in nodes),
            "status": "needs_physical_design",
        }
        for ident, name, stages in PACKAGES
    ]
    # Strong exclusions: never pretend the legacy 195kg plant and the new
    # 78kg articulated v03 are a single calibrated 12-system physiology.
    return {
        "schema": SCHEMA,
        "input_fingerprints": fingerprints,
        "old_solver": {
            "crown_cm": 250, "mass_kg": 195, "tail_cm": 120,
            "status": "retained_legacy_not_modified",
        },
        "canonical_target": dict(CANONICAL_TARGET),
        "canonical_physics_calibrated": False,
        "native_78kg_mujoco": "separate_mechanical_lineage; not imported_or_run",
        "system_count": len(systems),
        "node_count": len(registered_nodes),
        "route_count": len(routes),
        "systems": [{"stage": s["stage"], "name_fa": s["name_fa"],
                     "source_status": s.get("status"),
                     "node_count": len(s["organs"]),
                     "source_unresolved": s.get("unresolved", [])}
                    for s in systems],
        "nodes": registered_nodes,
        "routes": [
            {"kind": x["kind"], "node_path": x["path"],
             "source_scope": x.get("scope"), "physical_conduit_verified": False}
            for x in routes
        ],
        "extra_part_count": len(new_parts), "extra_parts": new_parts,
        "design_packages": packages,
        "special": {
            "resonan_pair": {
                "anchored_at": ["resonan_l", "resonan_r"],
                "location": "paired_horn_roots",
                "constraints": ["cranial_heat_guard", "separate_blood_supply",
                                "no_high_energy_cranial_reactor"],
            },
            "spandar": {
                "anchored_at": ["spandar", "thymus"],
                "location": "anterosuperior_thymic_capsule",
                "constraints": ["no_thymic_compression", "tracheal_and_venous_clearance",
                                "slow_monitor_not_consciousness_transfer"],
            },
            "azarine": {
                "anchored_at": ["azarine", "kidney_l", "spleen"],
                "location": "left_flank_pocket",
                "constraints": ["no_extra_energy_pool", "heat_budget",
                                "no_spleen_or_kidney_collision"],
            },
            "tail_and_pelvis": {
                "anchored_at": ["tail", "tail_root", "sacrum", "pudendal", "caudal_nerve"],
                "constraints": ["independent_caudal_innervation",
                                "no_pelvic_organ_impingement",
                                "load_to_sacral_skeletal_mount"],
            },
        },
        "evidence_tiers": {
            "regional_topology_only": "historical source describes region/role",
            "design_gap_not_a_3d_body": "new named component needs modeling",
            "physical": "not established",
            "native_78kg": "separate lineage; no integration proven",
        },
        "safety": {
            "clinical_use": False,
            "biological_realism_proven": False,
            "machine_consciousness_proven": False,
            "physical_actuation": False,
            "network_or_model_calls": False,
            "secrets_or_user_checkpoint_access": False,
        },
    }


def gap_report(registry: dict) -> dict:
    nodes = registry["nodes"]
    missing = len(nodes) * len(FIELDS) + len(registry["extra_parts"]) * len(FIELDS)
    return {
        "schema": "nasuraya.whole_body_design.gaps.v1",
        "node_count": registry["node_count"],
        "route_count": registry["route_count"],
        "system_count": registry["system_count"],
        "extra_part_count": registry["extra_part_count"],
        "unverified_engineering_field_count": missing,
        "route_physical_validations_remaining": registry["route_count"],
        "unverified_fields": list(FIELDS),
        "prioritized_packages": registry["design_packages"],
        "interpretation": "Coverage inventory, not physical completion or biological proof.",
        "blocking": [
            "Legacy physiology 195kg is not 78kg-canonical.",
            "Regional node topology is not organ mesh, innervation or perfusion.",
            "Separate 78kg native mechanics do not imply internal-organ validation.",
            "Horn, tail and special-structure collisions and clearances unverified.",
        ],
    }


def publish_json(target: Path, payload: dict) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    new = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
           + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() != new:
            raise ValueError("existing_receipt_conflict_no_overwrite")
    else:
        tmp = target.with_suffix(".tmp")
        with tmp.open("xb") as fh:
            fh.write(new)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    return hashlib.sha256(new).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    anatomy, phenotype, fingerprints = read_pinned(args.repo_root)
    registry = build_registry(anatomy, phenotype, fingerprints)
    gaps = gap_report(registry)
    if args.output_dir is not None:
        digest1 = publish_json(args.output_dir / "registry.json", registry)
        digest2 = publish_json(args.output_dir / "gaps.json", gaps)
        print(json.dumps({"status": "ok", "summary":
                          "ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;"
                          "EXTRA=" + str(registry["extra_part_count"]) +
                          ";PHYSICS=UNVERIFIED;REG=" + digest1[:12] +
                          ";GAPS=" + digest2[:12]}, separators=(",", ":")))
    else:
        print(json.dumps({"status": "ok", "summary":
                          "ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;"
                          "EXTRA=" + str(registry["extra_part_count"]) +
                          ";PHYSICS=UNVERIFIED"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
