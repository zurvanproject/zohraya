"""Offline fourway integration tests: original public records + labeled controls."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tools.fourway_evidence_gate_v02 import (
    REPO, SCHEMA, OWNER, atlas_status, extract_pair, fetch_live_issue_comments,
    moltbook_status, reconcile, research_status,
)

ROOT = Path(__file__).resolve().parents[1]
CI_PATH = ROOT / "docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json"
BRIDGE_PATH = ROOT / "docs/evidence/fourway-evidence-v02/frozen-bridge-comments.json"


def source_inputs():
    return (
        json.loads(CI_PATH.read_text(encoding="utf-8")),
        json.loads(BRIDGE_PATH.read_text(encoding="utf-8")),
    )


def reply(number: int, req: int, job: str, result: str, owner: str = OWNER):
    return {
        "id": number,
        "user": {"login": owner},
        "body": (
            "Nasuraya Bridge v2 result; request_id=comment-" + str(req) +
            "; command=run " + job + "\nResult: " + result
        ),
    }


class FourwayEvidenceGateTests(unittest.TestCase):
    def test_frozen_real_records_preserve_unknown_vps(self):
        ci, bridge = source_inputs()
        report = reconcile(ci, bridge)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["github_ci"]["observed_public_runs"], 5)
        self.assertEqual(report["github_ci"]["passed"], 4)
        self.assertEqual(report["github_ci"]["failed"], 1)
        self.assertEqual(report["github_ci"]["body_atlas_offline_ci"], "PASSED")
        self.assertEqual(report["github_ci"]["fourway_offline_ci"], "PASSED")
        self.assertEqual(report["vps"]["atlas_phase1"]["state"], "QUEUED_NO_RECEIPT")
        self.assertEqual(
            report["vps"]["research_fresh_request"]["state"],
            "STATUS_REQUEST_PENDING",
        )
        self.assertEqual(
            report["vps"]["research_previous_historical"]["state"],
            "REPORTED_RUNNING",
        )
        self.assertTrue(
            report["vps"]["research_previous_historical"]["historical_not_current"]
        )
        self.assertEqual(report["moltbook"]["state"], "HISTORICAL_REPLAY_ONLY")
        self.assertFalse(report["moltbook"]["direct_current_moltbook_confirmed"])
        self.assertEqual(report["whole_fourway_status"], "NOT_LIVE_VERIFIED")
        self.assertTrue(report["no_new_command_dispatched"])

    def test_fake_success_from_non_owner_ignored(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900001, 6771977584, "nasu_wholebody_phase1",
            "OK ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;"
            "EXTRA=35;PHYSICS=UNVERIFIED", owner="attacker"
        ))
        self.assertEqual(
            reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
            "QUEUED_NO_RECEIPT",
        )

    def test_wrong_request_id_does_not_complete_atlas(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900002, 6771977585, "nasu_wholebody_phase1",
            "OK ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;"
            "EXTRA=35;PHYSICS=UNVERIFIED",
        ))
        self.assertEqual(
            reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
            "QUEUED_NO_RECEIPT",
        )

    def test_owner_wrong_job_reply_fails_closed(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900003, 6771977584, "runtime_probe", "OK PYTHON=3.12.10"
        ))
        self.assertEqual(
            reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"], "CONFLICT"
        )

    def test_correct_reply_only_promotes_to_reported_inventory(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900004, 6771977584, "nasu_wholebody_phase1",
            "OK ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;"
            "EXTRA=35;PHYSICS=UNVERIFIED;REG=abc123;GAPS=abc123"
        ))
        report = reconcile(ci, bridge)
        self.assertEqual(report["vps"]["atlas_phase1"]["state"],
                         "REPORTED_INVENTORY")
        self.assertTrue(report["vps"]["atlas_phase1"]["not_physical_body"])
        self.assertFalse(report["vps"]["server_liveness_independently_verified"])
        self.assertEqual(report["whole_fourway_status"], "NOT_LIVE_VERIFIED")

    def test_unexpected_ok_claim_is_not_completed(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900005, 6771977584, "nasu_wholebody_phase1", "OK EVERYTHING=COMPLETE"
        ))
        self.assertEqual(reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
                         "REVIEW_REQUIRED")

    def test_reported_job_failure_not_success(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900006, 6771977584, "nasu_wholebody_phase1", "JOB_TIMEOUT"
        ))
        self.assertEqual(reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
                         "REPORTED_FAILURE")

    def test_owner_duplicate_reply_is_conflict_not_double_evidence(self):
        ci, bridge = source_inputs()
        b = "OK ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;EXTRA=35;PHYSICS=UNVERIFIED"
        bridge["comments"].append(reply(900007, 6771977584, "nasu_wholebody_phase1", b))
        bridge["comments"].append(reply(900008, 6771977584, "nasu_wholebody_phase1", b))
        self.assertEqual(reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
                         "CONFLICT")

    def test_conflicting_owner_reply_for_same_command(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900009, 6771977584, "nasu_wholebody_phase1", "JOB_FAILED"
        ))
        bridge["comments"].append(reply(
            900010, 6771977584, "nasu_wholebody_phase1",
            "OK ATLAS=INVENTORY;NODES=97;SYSTEMS=12;ROUTES=31;"
            "EXTRA=35;PHYSICS=UNVERIFIED"
        ))
        self.assertEqual(reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
                         "CONFLICT")

    def test_recent_research_completed_is_only_reported(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900011, 6770326192, "nasu_research_status",
            "OK STATE=COMPLETED;CYCLES=96;BAD=0;TF=0"
        ))
        report = reconcile(ci, bridge)
        self.assertEqual(report["vps"]["research_fresh_request"]["state"],
                         "REPORTED_COMPLETED_NO_TEST_FAILURE")
        self.assertFalse(report["vps"]["server_liveness_independently_verified"])

    def test_research_running_does_not_authorize_new_work(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(reply(
            900012, 6770326192, "nasu_research_status",
            "OK STATE=RUNNING;CYCLES=4;BAD=0;TF=0"
        ))
        report = reconcile(ci, bridge)
        self.assertEqual(report["vps"]["research_fresh_request"]["state"],
                         "REPORTED_RUNNING")
        self.assertTrue(report["no_new_command_dispatched"])

    def test_old_moltbook_replay_does_not_prove_live_read(self):
        ci, bridge = source_inputs()
        report = reconcile(ci, bridge)
        self.assertEqual(report["moltbook"]["state"], "HISTORICAL_REPLAY_ONLY")
        self.assertFalse(report["moltbook"]["direct_current_moltbook_confirmed"])
        self.assertFalse(report["chatgpt"]["model_memory_changed"])

    def test_wrong_repo_rejected(self):
        ci, bridge = source_inputs()
        bridge["repository"] = "another/repo"
        with self.assertRaisesRegex(ValueError, "invalid_bridge_fixture_source"):
            reconcile(ci, bridge)

    def test_duplicate_comment_id_causes_error_not_guess(self):
        ci, bridge = source_inputs()
        bridge["comments"].append(deepcopy(bridge["comments"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_comment_id"):
            reconcile(ci, bridge)

    def test_edited_request_is_not_owner_verified_original(self):
        ci, bridge = source_inputs()
        for item in bridge["comments"]:
            if item["id"] == 6771977584:
                item["body"] += " something unsafe"
        self.assertEqual(reconcile(ci, bridge)["vps"]["atlas_phase1"]["state"],
                         "REQUEST_UNVERIFIED")

    def test_missing_required_ci_run_cannot_claim_pass(self):
        ci, bridge = source_inputs()
        ci["runs"] = [x for x in ci["runs"] if x["run_id"] != 42846878619]
        report = reconcile(ci, bridge)
        self.assertEqual(report["github_ci"]["body_atlas_offline_ci"],
                         "NOT_OBSERVED")
        self.assertEqual(report["vps"]["atlas_phase1"]["state"],
                         "QUEUED_NO_RECEIPT")


if __name__ == "__main__":
    unittest.main()
