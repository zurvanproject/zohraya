"""Separate-agent adversarial checks, not independent human evaluation.

These are boundary regressions without using the reserved evaluation episodes.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from examples.dios_nous.unified import body, cognitive, evidence
from examples.dios_nous.unified import coordinator
from examples.dios_nous.unified.recovery import RecoveryAdvisor


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def native_export():
    payload = {"schema": "dios.native_body_export/1", "model_id": "tadash_legacy_195kg",
        "clock_domain": "simulated_seconds", "sampled_at_s": 10, "revision": 1,
        "native_checkpoint_sha256": "0" * 64, "source_observation_sha256": "1" * 64,
        "minimum_state": {"valence": -0.75, "energy": 0.7}, "finite_stocks": {}}
    payload["sha256"] = digest(payload)
    return payload


class UnifiedIndependentTests(unittest.TestCase):
    def test_native_rejects_unknown_fields_even_with_matching_digest(self):
        for location in ("top", "minimum", "stocks"):
            with self.subTest(location=location):
                record = native_export()
                target = record if location == "top" else record[
                    "minimum_state" if location == "minimum" else "finite_stocks"]
                target["PRIVATE_FIELD_993"] = 0.5
                record["sha256"] = digest({k: v for k, v in record.items() if k != "sha256"})
                with self.assertRaises(ValueError):
                    body.normalize_native(record, now_s=10)

    def test_native_rejects_boolean_nonfinite_future_and_wrong_model(self):
        for invalid in (True, float("nan"), float("inf"), -float("inf")):
            record = native_export()
            record["minimum_state"]["energy"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                body.normalize_native(record, now_s=10)
        record = native_export()
        with self.assertRaises(ValueError):
            body.normalize_native(record, now_s=9)
        for model in ("nasuraya_visual_target_78kg", "nasuraya_mujoco_v03_78kg"):
            record = native_export()
            record["model_id"] = model
            record["sha256"] = digest({k: v for k, v in record.items() if k != "sha256"})
            with self.subTest(model=model), self.assertRaises(ValueError):
                body.normalize_native(record, now_s=10)

    def test_signed_valence_is_preserved_and_stale_sample_not_live(self):
        fresh = body.normalize_native(native_export(), now_s=15)
        self.assertEqual(fresh["minimum_state"]["valence"]["value"], -0.75)
        self.assertEqual(fresh["minimum_state"]["valence"]["unit"], "signed_index")
        self.assertFalse(fresh["source_authenticated"])
        stale = body.normalize_native(native_export(), now_s=15.000001)
        self.assertEqual(stale["status"], "stale")
        self.assertIsNone(stale["minimum_state"]["valence"]["value"])
        self.assertEqual(stale["minimum_state"]["valence"]["status"], "unknown_stale")

    def test_native_model_lineage_is_declared_not_verified(self):
        result = body.normalize_native(native_export(), now_s=10)
        self.assertFalse(result["model_lineage_verified"])
        self.assertEqual(result["model_id_status"], "caller_declared_not_verified")

    def test_source_change_rejected_before_catalogue_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sources"
            shutil.copytree(body.SOURCE_ROOT, root)
            altered = root / "tools/fullbody_design_atlas.py"
            altered.write_bytes(altered.read_bytes() + b"\nraise RuntimeError('SHOULD_NOT_EXECUTE')\n")
            with patch.object(body, "SOURCE_ROOT", root), self.assertRaisesRegex(ValueError, "source bytes changed"):
                body.inventory()

    def test_receipt_age_never_becomes_source_authentication(self):
        records = json.loads((evidence._ROOT / "receipts.json").read_text())
        for name, record in records.items():
            created = datetime.fromisoformat(record["receipt_utc"].replace("Z", "+00:00"))
            for delta, expected in ((300, "FRESH_REPORT"), (301, "HISTORICAL_REPORT")):
                now = (created + timedelta(seconds=delta)).astimezone(timezone.utc).isoformat()
                result = evidence.validate_receipt(name, record, now_utc=now)
                with self.subTest(name=name, delta=delta):
                    self.assertEqual(result["freshness"], expected)
                    self.assertFalse(result["source_authenticated"])
                    self.assertFalse(result["live_execution_verified"])
                    self.assertFalse(result["action_authority"])

    def test_receipt_rejects_forged_owner_extra_fields_and_future(self):
        record = json.loads((evidence._ROOT / "receipts.json").read_text())["desktop"]
        for edit in ({"reply_owner_login": "different_owner"},
                     {"source_authenticated": True}, {"reply_id": True}):
            forged = copy.deepcopy(record)
            forged.update(edit)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                evidence.validate_receipt("desktop", forged, now_utc="2026-11-12T02:00:00Z")
        with self.assertRaises(ValueError):
            evidence.validate_receipt("desktop", record, now_utc="2026-11-12T00:00:00Z")

    def test_unobserved_recovery_and_passive_read_do_not_recommend_work(self):
        advisor = RecoveryAdvisor()
        before = advisor.checkpoint()
        self.assertEqual(advisor.read()["state"], "UNKNOWN")
        self.assertEqual(advisor.read()["advice"], "REQUEST_OBSERVATION")
        self.assertEqual(advisor.checkpoint(), before)
        self.assertEqual(advisor.step(tick=1, stress=0, fatigue=0, energy=1000)["state"], "RECOVERING")
        self.assertEqual(advisor.step(tick=2, stress=0, fatigue=0, energy=1000)["state"], "ACTIVE")

    def test_stop_independent_of_sample_clock_is_sticky_after_restore(self):
        for sampled in (False, True):
            advisor = RecoveryAdvisor()
            if sampled:
                advisor.step(tick=1, stress=0, fatigue=0, energy=1000)
            self.assertEqual(advisor.request_stop()["state"], "HALTED")
            restored = RecoveryAdvisor.restore(advisor.checkpoint())
            self.assertEqual(restored.step(tick=2, stress=0, fatigue=0, energy=1000)["state"], "HALTED")
            self.assertFalse(restored.read()["execution_permitted"])
            self.assertFalse(restored.read()["empirical_recovery_benefit_measured"])

    def test_invalid_workload_input_and_extra_checkpoint_fields_do_not_mutate_state(self):
        advisor = RecoveryAdvisor()
        before = advisor.checkpoint()
        for bad in (True, 1.5, float("nan"), float("inf"), -1, 1001):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                advisor.step(tick=1, stress=bad, fatigue=0, energy=1000)
            self.assertEqual(advisor.checkpoint(), before)
        forged = copy.deepcopy(before)
        forged["action_authority"] = True
        with self.assertRaises(ValueError):
            RecoveryAdvisor.restore(forged)

    def test_cognitive_catalogue_is_independent_passive_metadata(self):
        with patch.object(cognitive, "run_episode", side_effect=AssertionError("MUST_NOT_EXECUTE")):
            first = cognitive.describe_interfaces()
            first["interfaces"]["core"]["outputs"].clear()
            second = cognitive.describe_interfaces()
        self.assertTrue(second["interfaces"]["core"]["outputs"])
        self.assertEqual(second["interfaces"]["evidence"]["outputs"]["confidence"]["type"], "null")
        self.assertEqual(second["interfaces"]["dissent"]["outputs"]["authorization"]["execution_permitted"]["constant"], False)

    def test_coordinator_rejects_external_input_before_cognitive_writes(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "episode"
            malformed = native_export()
            malformed["minimum_state"]["PRIVATE_NOTE_337"] = "private"
            with patch.object(cognitive, "run_episode", side_effect=AssertionError("MUST_NOT_EXECUTE")):
                with self.assertRaises(ValueError):
                    coordinator.run_demo(target, now_utc="2026-11-12T08:00:00Z",
                                         native_export=malformed, now_s=10)
            self.assertFalse(target.exists())

    def test_summary_reads_neither_advance_cognition_nor_write_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshot = coordinator.run_demo(root, now_utc="2026-11-12T08:00:00Z")
            before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in root.rglob("*") if p.is_file()}
            with patch.object(cognitive, "run_episode", side_effect=AssertionError("MUST_NOT_EXECUTE")):
                one = coordinator.summary(snapshot)
                two = coordinator.summary(snapshot)
            after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in root.rglob("*") if p.is_file()}
            self.assertEqual(one, two)
            self.assertEqual(before, after)
            self.assertFalse(one["execution_permitted"])
            self.assertFalse(one["subjective_experience_demonstrated"])


if __name__ == "__main__":
    unittest.main()
