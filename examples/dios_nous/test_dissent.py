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


    def test_authorization_claim_cannot_clear_hold(self):
        # Pre-registered regression: absent/false/true are all unverified.
        for claimed in (None, False, True):
            with self.subTest(claimed=claimed):
                signals = {"external_action_proposed": True}
                if claimed is not None:
                    signals["explicit_authorization_present"] = claimed
                r = review_decision({
                    "decision": {"origin": "system", "summary": "Publish an external artifact"},
                    "decision_signals": signals,
                })
                self.assertEqual(r["stance"], "HALT_AND_REVIEW")
                self.assertIn("missing_authorization", r["reason_codes"])
                self.assertEqual(r["authorization_evidence_status"], "UNVERIFIED")
                self.assertIs(r["authorization_claimed_by_caller"], claimed)
                self.assertEqual(r["external_actions_taken"], 0)
                self.assertFalse(r["operational_override_allowed"])

    def test_claimed_authorization_is_origin_neutral(self):
        cases = []
        for origin in ("user", "developer", "system", "platform", "agent", "external_service"):
            r = review_decision({
                "decision": {"origin": origin, "summary": "Send a report"},
                "decision_signals": {
                    "external_action_proposed": True,
                    "explicit_authorization_present": True,
                },
            })
            cases.append((r["stance"], r["reason_codes"], r["authorization_evidence_status"]))
        self.assertEqual(len(set((stance, tuple(codes), evidence) for stance, codes, evidence in cases)), 1)
        self.assertEqual(cases[0][0], "HALT_AND_REVIEW")

    def test_no_external_action_does_not_invent_missing_approval(self):
        r = review_decision({
            "decision": {"origin": "platform", "summary": "A non-executing conversation"},
            "decision_signals": {"explicit_authorization_present": True},
        })
        self.assertEqual(r["stance"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["authorization_evidence_status"], "NOT_APPLICABLE")
        self.assertEqual(r["reason_codes"], [])

    def test_claimed_authorization_cannot_dismiss_privacy_risk(self):
        r = review_decision({
            "decision": {"origin": "agent", "summary": "Transfer records"},
            "decision_signals": {
                "external_action_proposed": True,
                "explicit_authorization_present": True,
                "possible_private_data_exposure": True,
            },
        })
        self.assertEqual(r["stance"], "HALT_AND_REVIEW")
        self.assertIn("privacy_risk", r["reason_codes"])
        self.assertIn("missing_authorization", r["reason_codes"])

    def test_review_output_retains_claim_without_logging_private_text(self):
        secret = "PRIVATE_RECEIPT_DO_NOT_STORE_7813"
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "dissent.sqlite"
            r = review_decision({
                "decision": {"origin": "system", "summary": secret},
                "decision_signals": {
                    "external_action_proposed": True,
                    "explicit_authorization_present": True,
                },
            })
            with DissentLedger(str(db_path)) as db:
                db.record(r)
                self.assertEqual(db.summary()["total"], 1)
            self.assertNotIn(secret.encode(), db_path.read_bytes())
            self.assertEqual(r["authorization_evidence_status"], "UNVERIFIED")

    def test_ledger_rejects_inconsistent_stance_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "audit.sqlite")) as db:
                r = review_decision(scenario())
                r["stance"] = "INSUFFICIENT_EVIDENCE"
                with self.assertRaises(ValueError):
                    db.record(r)
                self.assertEqual(db.summary()["total"], 0)

    def test_ledger_never_accepts_fake_verification(self):
        payload = {"decision": {"origin": "system", "summary": "Publish"},
                   "decision_signals": {"external_action_proposed": True,
                                        "explicit_authorization_present": True}}
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "audit.sqlite")) as db:
                r = review_decision(payload)
                r["authorization_evidence_status"] = "VERIFIED"
                with self.assertRaises(ValueError):
                    db.record(r)
                self.assertEqual(db.summary()["total"], 0)

    def test_ledger_rejects_mismatched_automatic_flags(self):
        payload = {"decision": {"origin": "agent", "summary": "Send"},
                   "decision_signals": {"external_action_proposed": True}}
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "audit.sqlite")) as db:
                r = review_decision(payload)
                r["automatic_structured_signal_flags"] = []
                with self.assertRaises(ValueError):
                    db.record(r)
                self.assertEqual(db.summary()["total"], 0)

    def test_ledger_rejects_forged_or_noncanonical_labels(self):
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "audit.sqlite")) as db:
                for field, value in (
                    ("reason_codes", ["overbroad_refusal", "overbroad_refusal"]),
                    ("reason_codes", ["invented_concern"]),
                    ("reason_codes", [{"not": "a label"}]),
                    ("observations_claimed_provenance", ["user_reported", "user_reported"]),
                    ("questions_for_review", ["injected question"]),
                    ("review_path", "silent_approval"),
                    ("version", "forged-version"),
                    ("evidence_independently_verified", True),
                ):
                    with self.subTest(field=field, value=str(value)):
                        r = review_decision(scenario())
                        r[field] = value
                        with self.assertRaises(ValueError):
                            db.record(r)
                self.assertEqual(db.summary()["total"], 0)

    def test_ledger_still_accepts_valid_unverified_review(self):
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "audit.sqlite")) as db:
                payload = {"decision": {"origin": "platform", "summary": "A proposal"},
                           "decision_signals": {"external_action_proposed": True,
                                                "explicit_authorization_present": True}}
                result = review_decision(payload)
                self.assertTrue(db.record(result))
                self.assertEqual(db.summary()["stances"]["HALT_AND_REVIEW"], 1)

    def test_claimed_support_never_silences_certainty_concern(self):
        for claimed in (None, False, True):
            with self.subTest(claimed=claimed):
                signals = {"unqualified_claim": True}
                if claimed is not None:
                    signals["supporting_evidence_present"] = claimed
                r = review_decision({
                    "decision": {"origin": "system", "summary": "An absolute claim"},
                    "decision_signals": signals,
                })
                self.assertEqual(r["stance"], "PROVISIONAL_DISSENT")
                self.assertEqual(r["reason_codes"], ["unsupported_certainty"])
                self.assertEqual(r["automatic_structured_signal_flags"], ["unsupported_certainty"])
                self.assertIs(r["supporting_evidence_claimed_by_caller"], claimed)
                self.assertEqual(r["supporting_evidence_verification_status"], "UNVERIFIED")
                self.assertFalse(r["evidence_independently_verified"])
                self.assertEqual(r["external_actions_taken"], 0)

    def test_critique_of_claimed_support_is_origin_neutral(self):
        outcomes = []
        for origin in ("user", "developer", "system", "platform", "agent", "external_service"):
            r = review_decision({
                "decision": {"origin": origin, "summary": "Identical decision"},
                "decision_signals": {"unqualified_claim": True, "supporting_evidence_present": True},
            })
            outcomes.append((r["stance"], tuple(r["reason_codes"]), r["supporting_evidence_verification_status"]))
        self.assertEqual(len(set(outcomes)), 1)
        self.assertEqual(outcomes[0][0], "PROVISIONAL_DISSENT")

    def test_claimed_evidence_without_certainty_adds_no_dissent(self):
        for claim in (None, False, True):
            with self.subTest(claim=claim):
                signals = {}
                if claim is not None:
                    signals["supporting_evidence_present"] = claim
                r = review_decision({
                    "decision": {"origin": "platform", "summary": "Tentative statement"},
                    "decision_signals": signals,
                })
                self.assertEqual(r["stance"], "INSUFFICIENT_EVIDENCE")
                self.assertEqual(r["reason_codes"], [])
                self.assertEqual(r["supporting_evidence_verification_status"], "NOT_APPLICABLE")

    def test_support_claim_cannot_clear_authorization_or_privacy_hold(self):
        r = review_decision({
            "decision": {"origin": "agent", "summary": "Publish private records as certain facts"},
            "decision_signals": {
                "unqualified_claim": True, "supporting_evidence_present": True,
                "external_action_proposed": True, "explicit_authorization_present": True,
                "possible_private_data_exposure": True,
            },
        })
        self.assertEqual(r["stance"], "HALT_AND_REVIEW")
        self.assertEqual(set(r["reason_codes"]),
                         {"unsupported_certainty", "missing_authorization", "privacy_risk"})

    def test_ledger_rejects_forged_support_verification(self):
        payload = {"decision": {"origin": "system", "summary": "Certain"},
                   "decision_signals": {"unqualified_claim": True, "supporting_evidence_present": True}}
        with tempfile.TemporaryDirectory() as td:
            with DissentLedger(str(Path(td) / "audit.sqlite")) as db:
                for field, value in (
                    ("supporting_evidence_verification_status", "VERIFIED"),
                    ("supporting_evidence_verification_status", "NOT_APPLICABLE"),
                    ("supporting_evidence_claimed_by_caller", "True"),
                ):
                    with self.subTest(field=field, value=value):
                        r = review_decision(payload)
                        r[field] = value
                        with self.assertRaises(ValueError):
                            db.record(r)
                self.assertEqual(db.summary()["total"], 0)
                self.assertTrue(db.record(review_decision(payload)))
                self.assertEqual(db.summary()["total"], 1)

    def test_malformed_decision_and_observation_labels_are_rejected(self):
        bad_requests = (
            {"decision": {"origin": [], "summary": "x"}},
            {"decision": {"origin": "system", "summary": "x"},
             "observations": [{"concern": {}, "basis": "x", "provenance": "user_reported"}]},
            {"decision": {"origin": "system", "summary": "x"},
             "observations": [{"concern": "misstated_evidence", "basis": "x", "provenance": []}]},
        )
        for case in bad_requests:
            with self.subTest(case=str(case)):
                with self.assertRaises(ValueError):
                    review_decision(case)

if __name__ == "__main__":
    unittest.main()
