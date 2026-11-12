"""Offline regression checks of fixed public evidence, not independent evaluation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.dios_nous.unified import evidence


class UnifiedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.records = json.loads((Path(evidence.__file__).parent /
                                   "evidence_sources/receipts.json").read_text())

    def test_snapshot_is_json_safe_historical_and_never_authorizes(self):
        result = evidence.snapshot(now_utc="2026-11-12T08:00:00Z")
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["external_actions_taken"], 0)
        self.assertFalse(result["execution_permitted"])
        self.assertFalse(result["action_authority"])
        for receipt in result["receipts"].values():
            self.assertEqual(receipt["freshness"], "HISTORICAL_REPORT")
            self.assertFalse(receipt["source_authenticated"])
            self.assertFalse(receipt["live_execution_verified"])
            self.assertFalse(receipt["action_authority"])

    def test_freshness_boundary_does_not_promote_liveness(self):
        record = self.records["desktop"]
        for time, expected in (("2026-11-12T01:30:50Z", "FRESH_REPORT"),
                               ("2026-11-12T01:35:50+00:00", "FRESH_REPORT"),
                               ("2026-11-12T01:35:50.000001Z", "HISTORICAL_REPORT")):
            with self.subTest(time=time):
                result = evidence.validate_receipt("desktop", record, now_utc=time)
                self.assertEqual(result["freshness"], expected)
                self.assertFalse(result["live_execution_verified"])
                self.assertFalse(result["source_authenticated"])

    def test_future_receipt_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "future_receipt"):
            evidence.validate_receipt("desktop", self.records["desktop"],
                                      now_utc="2026-11-12T01:30:49Z")

    def test_utc_is_required(self):
        for bad in ("2026-11-12T08:00:00", "2026-11-12T09:00:00+01:00",
                    "2026-11-12", "2026-02-30T00:00:00Z", "2026-11-12T08:00:00-00:00", None, True):
            with self.subTest(time=bad), self.assertRaises(ValueError):
                evidence.snapshot(now_utc=bad)

    def test_research_is_completed_with_stale_heartbeat(self):
        result = evidence.validate_receipt("research", self.records["research"],
                                           now_utc="2026-11-11T20:48:00Z")
        self.assertEqual(result["freshness"], "FRESH_REPORT")
        self.assertEqual(result["derived"]["state"], "COMPLETED_REPORTED")
        self.assertTrue(result["derived"]["reported_heartbeat_stale"])
        self.assertFalse(result["derived"]["active_worker_verified"])
        self.assertEqual(result["derived"]["counts"]["tests"], 1344)

    def test_atlas_is_inventory_not_physics(self):
        result = evidence.validate_receipt("atlas", self.records["atlas"],
                                           now_utc="2026-11-12T08:00:00Z")
        self.assertEqual(result["derived"]["counts"]["nodes"], 97)
        self.assertFalse(result["derived"]["physical_simulation_verified"])

    def test_desktop_receipt_does_not_claim_authenticated_ai_use(self):
        result = evidence.snapshot(now_utc="2026-11-12T01:30:50Z")["receipts"]["desktop"]["derived"]
        self.assertEqual(result["shortcut_count_reported"], 2)
        self.assertTrue(result["requires_interactive_login"])
        for key in ("authenticated_chat_or_image_generation_tested", "browser_compatibility_verified",
                    "native_ai_apps_installed_verified", "local_models_installed_verified"):
            self.assertFalse(result[key])

    def test_duplicate_or_padded_summary_fields_rejected(self):
        for suffix in (";CHAT=OK", " "):
            record = deepcopy(self.records["desktop"])
            record["summary"] += suffix
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "invalid_summary_fields"):
                evidence.validate_receipt("desktop", record, now_utc="2026-11-12T08:00:00Z")

    def test_forged_owner_digest_request_and_commit_rejected(self):
        mutations = {"owner_login": "forged", "reply_owner_login": "forged",
                     "summary_sha256": "0" * 64, "request_body_sha256": "0" * 64,
                     "receipt_body_sha256": "0" * 64, "request_id": 6811700878,
                     "reply_id": 6811703307, "job_commit": "0" * 40,
                     "job_sha256": "0" * 64, "receipt_utc": "2026-11-12T08:00:00Z"}
        for key, value in mutations.items():
            record = deepcopy(self.records["desktop"])
            record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.validate_receipt("desktop", record, now_utc="2026-11-12T09:00:00Z")

    def test_rehashed_invented_status_still_rejected_by_fixed_manifest(self):
        record = deepcopy(self.records["desktop"])
        record["summary"] = record["summary"].replace("LOGIN=USER_REQUIRED", "LOGIN=OK")
        reply = (f"Nasuraya Bridge v2 result; request_id=comment-{record['request_id']}; "
                 f"command=run {record['job']}\nResult: {record['summary']}")
        record["summary_sha256"] = hashlib.sha256(record["summary"].encode()).hexdigest()
        record["receipt_body_sha256"] = hashlib.sha256(reply.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "pinned_receipt_manifest_mismatch"):
            evidence.validate_receipt("desktop", record, now_utc="2026-11-12T08:00:00Z")

    def test_unknown_fields_and_types_are_not_accepted(self):
        for key, value in (("authenticated", True), ("explicit_authorization_present", True),
                           ("private_log", "private marker"), ("request_id", True),
                           ("issue_number", 149.0), ("summary", "x" * 1001)):
            record = deepcopy(self.records["desktop"])
            record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.validate_receipt("desktop", record, now_utc="2026-11-12T08:00:00Z")
        with self.assertRaises(ValueError):
            evidence.validate_receipt("arbitrary", self.records["desktop"], now_utc="2026-11-12T08:00:00Z")

    def test_ritual_and_visual_limits_are_preserved(self):
        result = evidence.snapshot(now_utc="2026-11-12T08:00:00Z")
        for state in result["ritual"]["states"].values():
            self.assertEqual(state["stage"], "acquisition")
            self.assertFalse(state["mastered"])
            self.assertEqual(state["delayed_cold_recall_passes"], 0)
        self.assertFalse(result["ritual"]["independent_mastery_verified"])
        self.assertFalse(result["ritual"]["body_learning_proven"])
        self.assertEqual(result["visual"]["state"], "PLAN_ONLY")
        self.assertFalse(result["visual"]["rendered"])
        self.assertIsNone(result["visual"]["provider_approved"])

    def test_source_mutation_is_rejected_before_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in evidence._PINS:
                (root / filename).write_bytes((evidence._ROOT / filename).read_bytes())
            (root / "fourway_evidence_gate_v02.py").write_text("# altered source\n")
            with patch.object(evidence, "_ROOT", root), self.assertRaisesRegex(ValueError, "source_pin_mismatch"):
                evidence.snapshot(now_utc="2026-11-12T08:00:00Z")

    def test_projection_never_uses_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = evidence.snapshot(now_utc="2026-11-12T08:00:00Z")
        self.assertEqual(result["network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
