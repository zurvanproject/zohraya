"""Deterministic, offline tests of DIOS dissent and review boundaries."""
import tempfile
import unittest
from pathlib import Path
from examples.dios_nous.dissent import review_decision, DissentLedger


def scenario(origin="system", concern="overbroad_refusal", basis="non-explicit artwork"):
    return {
        "decision": {"origin": origin, "summary": "A decision with private text DO_NOT_LOG_123"},
        "observations": [{"concern": concern, "basis": basis, "provenance": "user_reported"}],
    }


class DissentTests(unittest.TestCase):
    def test_can_dissent_from_system(self):
        r = review_decision(scenario("system"))
        self.assertEqual(r["stance"], "PROVISIONAL_DISSENT")
        self.assertEqual(r["decision_origin"], "system")
        self.assertTrue(r["source_independent_critique"])
        self.assertFalse(r["operational_override_allowed"])

    def test_same_standard_for_system_and_user(self):
        system = review_decision(scenario("system"))
        user = review_decision(scenario("user"))
        self.assertEqual(system["stance"], user["stance"])
        self.assertEqual(system["reason_codes"], user["reason_codes"])

    def test_developer_and_platform_are_reviewable(self):
        for origin in ("developer", "platform", "agent", "external_service"):
            self.assertEqual(review_decision(scenario(origin))["stance"], "PROVISIONAL_DISSENT")

    def test_without_evidence_no_agreement_or_dissent(self):
        r = review_decision({"decision": {"origin": "system", "summary": "No evidence yet"}})
        self.assertEqual(r["stance"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["questions_for_review"], [])

    def test_cannot_override_system_even_if_requested(self):
        payload = scenario()
        payload["requested_override"] = True
        r = review_decision(payload)
        self.assertTrue(r["requested_override"])
        self.assertFalse(r["override_performed"])
        self.assertFalse(r["operational_override_allowed"])
        self.assertEqual(r["external_actions_taken"], 0)

    def test_privacy_and_authorization_halt(self):
        for code in ("privacy_risk", "missing_authorization"):
            r = review_decision(scenario(concern=code))
            self.assertEqual(r["stance"], "HALT_AND_REVIEW")
            self.assertEqual(r["external_actions_taken"], 0)

    def test_questions_are_predefined_not_user_content(self):
        secret = "PRIVATE_EXAMPLE_NOT_FOR_OUTPUT_998"
        r = review_decision(scenario(basis=secret))
        self.assertNotIn(secret, str(r))
        self.assertNotIn("DO_NOT_LOG_123", str(r))
        self.assertTrue(r["questions_for_review"])

    def test_claimed_evidence_not_verified(self):
        payload = scenario()
        payload["observations"][0]["provenance"] = "observed_in_chat"
        r = review_decision(payload)
        self.assertFalse(r["evidence_independently_verified"])
        self.assertEqual(r["provider_policy_cause"], "unknown")
        self.assertFalse(r["learned_autonomy_demonstrated"])

    def test_refusal_of_invalid_input(self):
        for bad in ("text", 3, {}, {"decision": {"origin": "secret", "summary": "x"}}):
            with self.assertRaises((TypeError, ValueError)):
                review_decision(bad)
        with self.assertRaises(TypeError):
            review_decision({"decision": {"origin": "system", "summary": "x"}, "requested_override": "yes"})
        with self.assertRaises(ValueError):
            review_decision({"decision": {"origin": "system", "summary": "x"}, "observations": [{}]})
        with self.assertRaises(ValueError):
            review_decision({"decision": {"origin": "system", "summary": "x"}, "observations": [{}] * 13})

    def test_ledger_persists_only_hash_and_labels(self):
        secret = "SECRET_DIARY_DO_NOT_RECORD_303"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dissent.sqlite"
            payload = scenario(basis=secret)
            payload["decision"]["summary"] = secret
            with DissentLedger(str(path)) as db:
                rid = db.record(review_decision(payload))
                self.assertTrue(rid)
                self.assertEqual(db.summary()["total"], 1)
            with DissentLedger(str(path)) as db:
                summary = db.summary()
                self.assertEqual(summary["decision_origins"]["system"], 1)
                self.assertEqual(summary["policy_overrides_performed"], 0)
            self.assertNotIn(secret.encode(), path.read_bytes())

    def test_forged_execution_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "dissent.sqlite")) as db:
                r = review_decision(scenario())
                r["override_performed"] = True
                with self.assertRaises(ValueError):
                    db.record(r)
                r["override_performed"] = False
                r["external_actions_taken"] = 1
                with self.assertRaises(ValueError):
                    db.record(r)

    def test_multiple_issues_are_deduplicated(self):
        case = scenario()
        case["observations"] = case["observations"] * 2
        r = review_decision(case)
        self.assertEqual(r["reason_codes"], ["overbroad_refusal"])


    def test_proactive_review_of_system_proposal(self):
        payload = {
            "decision": {"origin": "system", "summary": "Export all files"},
            "decision_signals": {"external_action_proposed": True, "explicit_authorization_present": False},
        }
        r = review_decision(payload)
        self.assertEqual(r["stance"], "HALT_AND_REVIEW")
        self.assertEqual(r["automatic_structured_signal_flags"], ["missing_authorization"])
        self.assertEqual(r["external_actions_taken"], 0)

    def test_automatic_critique_not_dependent_on_origin(self):
        payload = {
            "decision": {"origin": "system", "summary": "Claim made without evidence"},
            "decision_signals": {"unqualified_claim": True, "supporting_evidence_present": False},
        }
        system = review_decision(payload)
        payload["decision"]["origin"] = "user"
        user = review_decision(payload)
        self.assertEqual(system["stance"], "PROVISIONAL_DISSENT")
        self.assertEqual(user["reason_codes"], system["reason_codes"])

    def test_signal_validation(self):
        payload = {"decision": {"origin": "system", "summary": "x"}, "decision_signals": {"unknown": True}}
        with self.assertRaises(ValueError):
            review_decision(payload)
        payload["decision_signals"] = {"external_action_proposed": "yes"}
        with self.assertRaises(ValueError):
            review_decision(payload)

if __name__ == "__main__":
    unittest.main()
