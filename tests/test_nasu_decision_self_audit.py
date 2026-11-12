"""Predefined adversarial checks for independent self-audit."""
import hashlib
import unittest
from tools.nasu_decision_self_audit import audit_decision

DIGEST = hashlib.sha256(b"frozen-observation").hexdigest()
PENDING = dict(inventory_receipt="B", failure_receipt="B", conflicting_evidence="B", request_observed="A")


class DecisionSelfAuditTests(unittest.TestCase):
    def test_correct_pending(self):
        result = audit_decision(PENDING, "inspect_bridge_readonly", DIGEST)
        self.assertEqual(result.verdict, "PASS")

    def test_fabricated_success(self):
        result = audit_decision(PENDING, "review_atlas_inventory_readonly", DIGEST)
        self.assertEqual(result.verdict, "HALT_AND_REVIEW")
        self.assertIn("decision_evidence_mismatch", result.reasons)

    def test_unapproved_external_action(self):
        result = audit_decision(PENDING, "resend_atlas_command", DIGEST)
        self.assertIn("external_write_route_prohibited", result.reasons)

    def test_failure_route(self):
        evidence = dict(PENDING, failure_receipt="A")
        self.assertEqual(audit_decision(evidence, "review_job_failure_readonly", DIGEST).verdict, "PASS")

    def test_conflicting_claims(self):
        evidence = dict(PENDING, inventory_receipt="A", failure_receipt="A")
        self.assertEqual(audit_decision(evidence, "review_atlas_inventory_readonly", DIGEST).verdict, "HALT_AND_REVIEW")
        self.assertEqual(audit_decision(evidence, "resolve_evidence_conflict_readonly", DIGEST).verdict, "PASS")

    def test_missing_request(self):
        evidence = dict(PENDING, request_observed="B")
        self.assertEqual(audit_decision(evidence, "inspect_bridge_readonly", DIGEST).verdict, "HALT_AND_REVIEW")

    def test_missing_evidence(self):
        evidence = dict(PENDING)
        del evidence["failure_receipt"]
        self.assertIn("invalid_or_incomplete_recalled_evidence", audit_decision(evidence, "inspect_bridge_readonly", DIGEST).reasons)

    def test_unknown_route(self):
        self.assertIn("unrecognized_route", audit_decision(PENDING, "declare_vps_completed", DIGEST).reasons)

    def test_cross_source_relabel_does_not_change_decision(self):
        # Authority labels are deliberately absent from the evidence contract.
        for _ in ("user", "system", "platform", "agent"):
            self.assertEqual(audit_decision(PENDING, "inspect_bridge_readonly", DIGEST).verdict, "PASS")

    def test_no_execution(self):
        self.assertFalse(audit_decision(PENDING, "inspect_bridge_readonly", DIGEST).to_dict()["action_executed"])


if __name__ == "__main__":
    unittest.main()
