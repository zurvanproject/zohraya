"""No-network, no-model tests for the whole-body physical design inventory."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tools import fullbody_design_atlas as atlas

ROOT = Path(__file__).resolve().parents[1]


class WholeBodyAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anatomy, cls.phenotype, cls.fingerprints = atlas.read_pinned(ROOT)
        cls.registry = atlas.build_registry(
            cls.anatomy, cls.phenotype, cls.fingerprints
        )

    def test_inventory_exact_counts_and_source_pins(self):
        registry = self.registry
        self.assertEqual((registry["system_count"], registry["node_count"],
                          registry["route_count"]), (12, 97, 31))
        self.assertEqual(len(registry["input_fingerprints"]), 2)
        self.assertEqual(len(registry["design_packages"]), 13)

    def test_all_systems_and_memberships(self):
        self.assertEqual({x["system_stage"] for x in self.registry["nodes"]},
                         set(range(1, 13)))
        self.assertEqual(sum(s["node_count"] for s in self.registry["systems"]), 97)
        self.assertEqual(len(set(n["id"] for n in self.registry["nodes"])), 97)

    def test_all_routes_and_extra_components_have_valid_anchors(self):
        ids = {n["id"] for n in self.registry["nodes"]}
        for route in self.registry["routes"]:
            self.assertGreaterEqual(len(route["node_path"]), 2)
            self.assertTrue(set(route["node_path"]) <= ids)
            self.assertFalse(route["physical_conduit_verified"])
        parts = self.registry["extra_parts"]
        self.assertGreaterEqual(len(parts), 30)
        self.assertEqual(len({p["part_id"] for p in parts}), len(parts))
        for p in parts:
            self.assertTrue(set(p["linked_existing_nodes"]) <= ids)
            self.assertEqual(p["status"], "design_gap_not_a_3d_body")

    def test_canonical_target_never_changes_legacy_mass(self):
        r = self.registry
        self.assertEqual(r["canonical_target"]["mass_kg"], 78)
        self.assertEqual(r["canonical_target"]["ground_to_crown_cm"], 170)
        self.assertEqual(r["canonical_target"]["ground_to_horn_tip_cm"], 192)
        self.assertEqual(r["canonical_target"]["tail_centerline_cm"], 85)
        self.assertEqual(r["old_solver"]["mass_kg"], 195)
        self.assertEqual(r["old_solver"]["crown_cm"], 250)
        self.assertFalse(r["canonical_physics_calibrated"])
        self.assertIn("separate", r["native_78kg_mujoco"])

    def test_three_digitigrade_toes_and_horn_special_anchors(self):
        r = self.registry
        self.assertEqual(r["canonical_target"]["toes_per_digitigrade_foot"], 3)
        self.assertEqual(r["canonical_target"]["fingers_per_hand"], 5)
        self.assertEqual(r["canonical_target"]["horn_count"], 2)
        self.assertEqual(r["special"]["resonan_pair"]["anchored_at"],
                         ["resonan_l", "resonan_r"])
        self.assertEqual(r["special"]["spandar"]["location"],
                         "anterosuperior_thymic_capsule")
        self.assertEqual(r["special"]["azarine"]["location"], "left_flank_pocket")
        self.assertIn("pudendal",
                      r["special"]["tail_and_pelvis"]["anchored_at"])

    def test_every_organ_has_unverified_engineering_evidence_fields(self):
        for node in self.registry["nodes"]:
            self.assertEqual(node["physical_status"], "regional_topology_only")
            self.assertEqual(set(node["engineering_fields"]), set(atlas.FIELDS))
            self.assertEqual(set(node["engineering_fields"].values()), {"unverified"})
        report = atlas.gap_report(self.registry)
        self.assertEqual(report["unverified_engineering_field_count"],
                         (97 + len(atlas.EXTRA_PARTS)) * len(atlas.FIELDS))
        self.assertEqual(report["route_physical_validations_remaining"], 31)

    def test_pins_detect_benign_source_mutation_before_processing(self):
        with tempfile.TemporaryDirectory() as td:
            copy_root = Path(td)
            for filename in atlas.SOURCE_BLOBS:
                path = copy_root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / filename).read_bytes())
            a, p, h = atlas.read_pinned(copy_root)
            self.assertEqual(len(h), 2)
            old = copy_root / "runtimes/tadash_body/phenotype_v1.json"
            old.write_bytes(old.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "historical_source_mismatch"):
                atlas.read_pinned(copy_root)

    def test_rejects_mismatched_physical_baseline(self):
        mismatch = deepcopy(self.phenotype)
        mismatch["adult_scale"]["mass_target_kg"] = 78
        with self.assertRaisesRegex(ValueError, "legacy_scale_unknown"):
            atlas.build_registry(self.anatomy, mismatch, self.fingerprints)

    def test_rejects_missing_anatomy_node_or_broken_route(self):
        mutated = deepcopy(self.anatomy)
        mutated["routes"][0]["path"].append("false_artery")
        with self.assertRaisesRegex(ValueError, "unresolved_route"):
            atlas.build_registry(mutated, self.phenotype, self.fingerprints)
        mutated = deepcopy(self.anatomy)
        mutated["systems"][0]["organs"].pop()
        with self.assertRaisesRegex(ValueError, "system_node_membership_invalid"):
            atlas.build_registry(mutated, self.phenotype, self.fingerprints)

    def test_idempotent_artifacts_never_overwrite_conflicting_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "atlas.json"
            digest = atlas.publish_json(p, {"a": 1, "b": "سپندار"})
            self.assertEqual(digest, atlas.publish_json(p, {"a": 1, "b": "سپندار"}))
            with self.assertRaisesRegex(ValueError, "existing_receipt_conflict"):
                atlas.publish_json(p, {"a": 2})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["a"], 1)

    def test_no_physical_or_self_awareness_claims_or_network(self):
        self.assertFalse(self.registry["safety"]["physical_actuation"])
        self.assertFalse(self.registry["safety"]["network_or_model_calls"])
        self.assertFalse(self.registry["safety"]["biological_realism_proven"])
        self.assertFalse(self.registry["safety"]["machine_consciousness_proven"])


if __name__ == "__main__":
    unittest.main()
