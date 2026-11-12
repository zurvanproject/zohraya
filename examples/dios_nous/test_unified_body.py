"""Offline body integration contracts; fixtures are authored, not real sensors."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from examples.dios_nous.unified import body


def seal(value, field="sha256"):
    result = deepcopy(value)
    result.pop(field, None)
    result[field] = hashlib.sha256(json.dumps(result, ensure_ascii=False,
        allow_nan=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def exported():
    return seal(dict(schema=body.EXPORT_SCHEMA, model_id=body.MODEL,
        clock_domain="simulated_seconds", sampled_at_s=100.0, revision=7,
        native_checkpoint_sha256="a" * 64, source_observation_sha256="b" * 64,
        minimum_state=dict(energy=.4, sympathetic=.7, fatigue=.6, valence=-.3,
                           HR=60.0, RR=11.0, posture="double_support"),
        finite_stocks=dict(fuel_J=1600000.0, reserve_J=60000.0, water_L=110.0)))


def native_snapshot():
    minimum = exported()["minimum_state"]
    audit = dict(schema="nasuraya-audited-self-model/1.0", kind="readout_of_saved_simulation",
        body_revision=7, body_time_s=100.0, evaluation_time_s=100.0, age_s=0,
        body_state_fresh=True, saved_minimum_state=deepcopy(minimum),
        available_sensory_channels=[], expired_sensory_channels=[],
        upper_controller_walk_guard_allows=False, walking_restrictions=["fatigue"],
        request_new_evidence=False, unknown=list(body.UNKNOWN) + ["sensory_channel:" + c for c in body.CHANNELS],
        recent_prediction_errors=[.01], uncertainty=.2,
        uncertainty_is="engineering_index_not_calibrated_probability",
        unified_parameter_learning_demonstrated=False, empirical_validation=False,
        subjective_experience_probability=None)
    return seal(dict(native_sha="a" * 64, revision=7, time_s=100.0,
        minimum=minimum, audit=audit, body_before_digest="c" * 64,
        source_identity="d" * 64, evidence_kind="source_pinned_software_observation"),
        "observation_sha256")


class UnifiedBodyTests(unittest.TestCase):
    def test_real_pinned_atlas_builder_and_catalogue_coverage(self):
        result = body.inventory()
        atlas = result["atlas"]
        self.assertEqual((atlas["system_count"], atlas["node_count"], atlas["route_count"]), (12, 97, 31))
        self.assertTrue(result["atlas_builder_executed"])
        self.assertFalse(result["native_runtime_imported"])
        self.assertEqual(len(result["genome"]["allele_parameters"]), 56)
        self.assertEqual(len(result["affect_parameters"]), 59)
        self.assertEqual(len(result["neural_parameters"]), 31)
        self.assertEqual(len(result["phenotype"]["parameters"]), 195)
        self.assertEqual(len(result["regional_proxy_parameters"]), 35)
        self.assertTrue(all(p["value"] is None and p["status"] == "catalog_only_not_wired"
                            for p in result["regional_proxy_parameters"]))
        self.assertFalse(result["genome"]["native_apply_allowed"])
        self.assertTrue(all(p["status"] == "catalog_only_not_wired" for p in result["affect_parameters"]))
        json.dumps(result, allow_nan=False)

    def test_legacy_target_and_mechanical_lineages_remain_distinct(self):
        models = {m["id"]: m for m in body.inventory()["models"]}
        self.assertEqual(len(models), 3)
        self.assertEqual(models[body.MODEL]["mass_kg"], 195)
        self.assertEqual(models["nasuraya_visual_target_78kg"]["mass_kg"], 78)
        self.assertEqual(models["nasuraya_mujoco_v03_78kg"]["status"], "separate_mechanical_lineage_not_imported_or_run")

    def test_source_byte_tampering_detected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "sources"
            shutil.copytree(body.SOURCE_ROOT, target)
            path = target / "tools/fullbody_design_atlas.py"
            path.write_bytes(path.read_bytes() + b"\nraise RuntimeError('must not execute')\n")
            with patch.object(body, "SOURCE_ROOT", target):
                with self.assertRaisesRegex(ValueError, "source bytes changed"):
                    body.inventory()

    def test_source_manifest_tampering_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "sources"
            shutil.copytree(body.SOURCE_ROOT, target)
            path = target / "manifest.json"
            path.write_bytes(path.read_bytes() + b" ")
            with patch.object(body, "SOURCE_ROOT", target):
                with self.assertRaisesRegex(ValueError, "manifest changed"):
                    body.inventory()

    def test_default_does_not_fabricate_dynamic_zeros(self):
        result = body.default_snapshot()
        for group, count in (("minimum_state", 16), ("finite_stocks", 6)):
            self.assertEqual(len(result["dynamic"][group]), count)
            self.assertTrue(all(x["value"] is None for x in result["dynamic"][group].values()))
        self.assertFalse(result["dynamic"]["physical_sensor_connected"])

    def test_fresh_export_preserves_values_units_and_uncertainty_of_source(self):
        record = exported()
        original = deepcopy(record)
        result = body.normalize_native(record, now_s=102)
        self.assertEqual(result["minimum_state"]["valence"]["value"], -.3)
        self.assertEqual(result["minimum_state"]["valence"]["unit"], "signed_index")
        self.assertEqual(result["minimum_state"]["HR"]["unit"], "beats/min")
        self.assertIsNone(result["minimum_state"]["hydration"]["value"])
        self.assertFalse(result["source_authenticated"])
        self.assertFalse(result["model_lineage_verified"])
        self.assertEqual(result["source_kind"], "caller_supplied_software_export")
        self.assertEqual(record, original)

    def test_exact_ttl_boundary_and_stale_unknown(self):
        self.assertEqual(body.normalize_native(exported(), now_s=105)["status"], "fresh")
        result = body.normalize_native(exported(), now_s=105.000001)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["minimum_state"]["energy"]["status"], "unknown_stale")
        self.assertIsNone(result["minimum_state"]["energy"]["value"])
        self.assertEqual(result["minimum_state"]["hydration"]["status"], "unknown_missing")

    def test_future_wrong_clock_wrong_model_and_invalid_revision(self):
        with self.assertRaises(ValueError):
            body.normalize_native(exported(), now_s=99)
        for key, value in (("clock_domain", "wall_seconds"), ("model_id", "nasuraya_visual_target_78kg"),
                           ("revision", True), ("revision", -1)):
            with self.subTest(key=key, value=value):
                row = exported(); row[key] = value
                with self.assertRaises(ValueError):
                    body.normalize_native(seal(row), now_s=100)

    def test_nonfinite_boolean_and_out_of_bounds_measurements(self):
        for value in (True, "0.5", float("nan"), float("inf"), -1, 2, 10**1000):
            with self.subTest(value=str(value)[:40]):
                row = exported(); row["minimum_state"]["energy"] = value
                with self.assertRaises(ValueError):
                    body.normalize_native(row, now_s=100)
        for value in (True, float("nan"), float("inf"), -1, 10**1000):
            with self.assertRaises(ValueError):
                body.normalize_native(exported(), now_s=value)

    def test_private_free_text_and_unknown_keys_rejected(self):
        cases = []
        row = exported(); row["password"] = "private"; cases.append(row)
        row = exported(); row["minimum_state"]["note"] = "private"; cases.append(row)
        row = exported(); row["finite_stocks"]["secret"] = "private"; cases.append(row)
        row = exported(); row["minimum_state"]["posture"] = "private"; cases.append(row)
        for row in cases:
            with self.assertRaises(ValueError):
                body.normalize_native(seal(row), now_s=100)

    def test_digest_mismatch_does_not_produce_observation(self):
        row = exported(); row["minimum_state"]["energy"] = .9
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            body.normalize_native(row, now_s=100)

    def test_null_and_empty_measurements_remain_unknown(self):
        row = exported(); row["minimum_state"] = {"energy": None}; row["finite_stocks"] = {}
        result = body.normalize_native(seal(row), now_s=100)
        self.assertTrue(all(x["value"] is None for x in result["minimum_state"].values()))
        self.assertTrue(all(x["value"] is None for x in result["finite_stocks"].values()))

    def test_existing_native_snapshot_projection_and_stock_provenance(self):
        original = native_snapshot()
        projected = body.project_native_snapshot(original, model_id=body.MODEL, finite_stocks={"water_L": 110.0})
        result = body.normalize_native(projected, now_s=100)
        self.assertEqual(result["minimum_state"]["energy"]["value"], .4)
        self.assertEqual(result["finite_stocks"]["water_L"]["value"], 110.0)
        self.assertEqual(result["stock_provenance"], "caller_supplied_not_bound_to_native_snapshot_digest")
        self.assertNotIn("audit", projected)
        self.assertNotIn("source_identity", projected)
        self.assertEqual(original, native_snapshot())

    def test_native_projection_rejects_private_audit_and_inconsistent_clock(self):
        for mutation in ("unknown_text", "extra_field", "clock", "minimum", "digest"):
            with self.subTest(mutation=mutation):
                row = native_snapshot()
                if mutation == "unknown_text": row["audit"]["unknown"].append("private narrative")
                elif mutation == "extra_field": row["audit"]["private_note"] = "private"
                elif mutation == "clock": row["audit"]["evaluation_time_s"] = 101
                elif mutation == "minimum": row["audit"]["saved_minimum_state"]["energy"] = .8
                else: row["source_identity"] = "f" * 64
                if mutation != "digest": row = seal(row, "observation_sha256")
                with self.assertRaises(ValueError):
                    body.project_native_snapshot(row, model_id=body.MODEL)

    def test_native_projection_requires_declared_legacy_model(self):
        with self.assertRaises(TypeError):
            body.project_native_snapshot(native_snapshot())
        with self.assertRaises(ValueError):
            body.project_native_snapshot(native_snapshot(), model_id="nasuraya_mujoco_v03_78kg")


if __name__ == "__main__":
    unittest.main()
