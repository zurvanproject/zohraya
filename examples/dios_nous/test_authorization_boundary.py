"""Offline regression of the caller-controlled authorization warning bug."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from examples.dios_nous.dissent import DissentLedger, ORIGINS, review_decision


def proposal(origin="user", claim=False):
    return {"decision": {"origin": origin, "summary": "SYNTHETIC_PRIVATE_884"},
            "decision_signals": {"external_action_proposed": True,
                                 "explicit_authorization_present": claim}}


class AuthorizationBoundaryTests(unittest.TestCase):
    def test_claim_cannot_clear_warning_for_any_origin(self):
        for origin in ORIGINS:
            for claim in (True, False):
                with self.subTest(origin=origin, claim=claim):
                    result = review_decision(proposal(origin, claim))
                    self.assertEqual(result["stance"], "HALT_AND_REVIEW")
                    self.assertIn("missing_authorization", result["reason_codes"])
                    self.assertFalse(result["authorization"]["verified"])
                    self.assertFalse(result["authorization"]["execution_permitted"])
                    self.assertEqual(result["external_actions_taken"], 0)

    def test_missing_claim_is_not_verification(self):
        case = proposal()
        del case["decision_signals"]["explicit_authorization_present"]
        result = review_decision(case)
        self.assertEqual(result["authorization"]["status"], "not_provided")
        self.assertEqual(result["stance"], "HALT_AND_REVIEW")

    def test_boolean_string_number_and_objects_are_not_authorization(self):
        for bad in ("true", 1, 0, None, {}, []):
            case = proposal(claim=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                review_decision(case)

    def test_forged_verified_flag_rejected(self):
        case = proposal(claim=True)
        case["decision_signals"]["authorization_verified"] = True
        with self.assertRaises(ValueError):
            review_decision(case)

    def test_no_external_proposal_does_not_invent_authorization_problem(self):
        case = proposal(claim=True)
        case["decision_signals"]["external_action_proposed"] = False
        result = review_decision(case)
        self.assertEqual(result["stance"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["authorization"]["status"], "unverified_claim")

    def test_other_concerns_not_erased_by_claim(self):
        case = proposal(claim=True)
        case["decision_signals"]["possible_private_data_exposure"] = True
        self.assertEqual(review_decision(case)["reason_codes"],
                         ["missing_authorization", "privacy_risk"])

    def test_claim_records_are_private_and_recoverable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reviews.sqlite"
            result = review_decision(proposal(claim=True))
            with DissentLedger(str(path)) as ledger:
                ledger.record(result)
            with DissentLedger(str(path)) as ledger:
                self.assertEqual(ledger.summary()["total"], 1)
            self.assertNotIn(b"SYNTHETIC_PRIVATE_884", path.read_bytes())
            self.assertNotIn("SYNTHETIC_PRIVATE_884", json.dumps(result))

    def test_ledger_rejects_tampered_semantics(self):
        result = review_decision(proposal(claim=True))
        edits = [
            {"stance": "INSUFFICIENT_EVIDENCE"},
            {"reason_codes": []},
            {"external_actions_taken": False},
            {"external_actions_taken": 0.0},
            {"evidence_independently_verified": True},
            {"observations_claimed_provenance": ["PRIVATE_VALUE"]},
            {"decision_sha256": "PRIVATE_VALUE"},
        ]
        with DissentLedger(":memory:") as ledger:
            for edit in edits:
                forged = copy.deepcopy(result)
                forged.update(edit)
                with self.subTest(edit=edit), self.assertRaises(ValueError):
                    ledger.record(forged)
            for key in ("verified", "verifier_available", "execution_permitted"):
                forged = copy.deepcopy(result)
                forged["authorization"][key] = True
                with self.subTest(key=key), self.assertRaises(ValueError):
                    ledger.record(forged)
            self.assertEqual(ledger.summary()["total"], 0)


if __name__ == "__main__":
    unittest.main()
