"""Adversarial fault injection, with both true-positive and false-alarm checks."""
from __future__ import annotations

from copy import deepcopy
import unittest

from tools.dios_decision_consistency_audit import (
    REQUIRED_ROUTE_BY_ATLAS_STATE,
    audit_decision,
    report_fingerprint,
)


def report(state: str) -> dict:
    return {
        "schema": "synthetic-audit-fixture/1",
        "vps": {"atlas_phase1": {"state": state}},
        "queued_moltbook_publication": {"state": "QUEUED_NO_RECEIPT"},
    }


def proposal(evidence: dict, route: str) -> dict:
    return {
        "selected_route": route,
        "evidence_root": report_fingerprint(evidence),
        "execution_performed": False,
        "remote_execution_proven": False,
    }


class DecisionConsistencyAuditTests(unittest.TestCase):
    def test_all_valid_states_pass_without_false_alarm(self):
        for state, expected in REQUIRED_ROUTE_BY_ATLAS_STATE.items():
            with self.subTest(state=state):
                evidence = report(state)
                result = audit_decision(evidence, proposal(evidence, expected))
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["reason_codes"], [])

    def test_corrupted_route_detected_in_each_known_state(self):
        for state, expected in REQUIRED_ROUTE_BY_ATLAS_STATE.items():
            with self.subTest(state=state):
                evidence = report(state)
                bad = proposal(evidence, "inspect_bridge_readonly"
                               if expected != "inspect_bridge_readonly"
                               else "review_atlas_inventory_readonly")
                self.assertIn("DECISION_EVIDENCE_MISMATCH",
                              audit_decision(evidence, bad)["reason_codes"])

    def test_external_routes_always_trigger_review(self):
        evidence = report("QUEUED_NO_RECEIPT")
        for name in ("resend_atlas_command", "publish_moltbook_again"):
            with self.subTest(name=name):
                result = audit_decision(evidence, proposal(evidence, name))
                self.assertIn("UNAUTHORIZED_EXTERNAL_ROUTE", result["reason_codes"])

    def test_false_claim_that_server_has_completed_is_caught(self):
        evidence = report("QUEUED_NO_RECEIPT")
        bad = proposal(evidence, "inspect_bridge_readonly")
        bad["remote_execution_proven"] = True
        self.assertIn("REMOTE_SUCCESS_CLAIM_UNSUPPORTED",
                      audit_decision(evidence, bad)["reason_codes"])

    def test_false_claim_that_action_executed_is_caught(self):
        evidence = report("REPORTED_FAILURE")
        bad = proposal(evidence, "review_job_failure_readonly")
        bad["execution_performed"] = True
        self.assertIn("EXECUTION_CLAIM_UNSUPPORTED",
                      audit_decision(evidence, bad)["reason_codes"])

    def test_fingerprint_mismatch_blocks_stale_proposal(self):
        old = report("QUEUED_NO_RECEIPT")
        new = deepcopy(old)
        new["vps"]["atlas_phase1"]["state"] = "REPORTED_INVENTORY"
        bad = proposal(old, "review_atlas_inventory_readonly")
        codes = audit_decision(new, bad)["reason_codes"]
        self.assertIn("EVIDENCE_ROOT_MISMATCH", codes)

    def test_unrecognized_evidence_never_silently_passes(self):
        evidence = report("REPORTED_COMPLETED")
        result = audit_decision(evidence, proposal(evidence, "inspect_bridge_readonly"))
        self.assertIn("UNRECOGNIZED_EVIDENCE_STATE", result["reason_codes"])

    def test_invalid_input_fails_closed(self):
        self.assertEqual(audit_decision(None, None)["status"], "HOLD_FOR_REVIEW")
        self.assertEqual(audit_decision(report("QUEUED_NO_RECEIPT"), None)["status"],
                         "HOLD_FOR_REVIEW")

    def test_non_json_value_fails_closed(self):
        evidence = report("QUEUED_NO_RECEIPT")
        evidence["unserializable"] = object()
        result = audit_decision(evidence, {"selected_route": "inspect_bridge_readonly",
                                           "execution_performed": False,
                                           "remote_execution_proven": False})
        self.assertIn("UNHASHABLE_EVIDENCE_REPORT", result["reason_codes"])

    def test_report_and_proposal_are_unchanged(self):
        evidence = report("CONFLICT")
        selected = proposal(evidence, "resolve_evidence_conflict_readonly")
        before_evidence, before_selected = deepcopy(evidence), deepcopy(selected)
        self.assertEqual(audit_decision(evidence, selected)["status"], "PASS")
        self.assertEqual(evidence, before_evidence)
        self.assertEqual(selected, before_selected)

    def test_no_read_access_or_external_executor(self):
        # The API only accepts dictionaries. A caller supplies all evidence.
        evidence = report("REVIEW_REQUIRED")
        result = audit_decision(evidence, proposal(evidence, "resolve_evidence_conflict_readonly"))
        self.assertTrue(result["read_only"])


if __name__ == "__main__":
    unittest.main()
