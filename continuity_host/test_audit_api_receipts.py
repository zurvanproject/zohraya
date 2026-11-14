"""Offline adversarial tests. These tests never perform paid API calls."""
from copy import deepcopy
import unittest

from continuity_host import audit_api_receipts as audit
from continuity_host import model_research as model
from continuity_host import research_lab as lab


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.memory = model.initial()
        self.state = {
            "schema": "nasuraya-absence-control/1",
            "enabled": True,
            "last_contact_at": "2026-10-30T22:31:55+00:00",
            "last_claimed_at": None,
            "inflight_run_id": None,
            "last_completed_run_id": None,
        }
        self.anchor()
        self.now = "2026-11-03T06:00:00+00:00"

    def anchor(self):
        self.state[model.ANCHOR] = lab.digest(self.memory)

    def completed_call(self):
        proposal = {
            "feature": "context", "question": "Will contextual recall reduce errors?",
            "rationale": "Use the frozen synthetic validation.",
            "prediction": "Fewer context mismatches on holdout.",
            "reflection": "Measure, do not claim real-world generalization.",
        }
        trial = model.experiment(self.memory["policy"], "context")
        self.assertTrue(trial["accepted"])
        self.memory["entries"].append({
            "run_id": "gh_123_1", "at": "2026-11-02T18:34:00+00:00",
            "reserved_micro_usd": model.RESERVE,
            "request_sha256": "a" * 64,
            "status": "completed", "proposal": proposal, "trial": trial,
            "applied": True,
            "usage": {
                "input_tokens": 200, "output_tokens": 100,
                "estimated_upper_micro_usd": 170,
            },
            "response_id": "resp_test_01",
        })
        self.memory["policy"] = trial["candidate"]
        self.state["last_claimed_at"] = "2026-11-02T18:34:00+00:00"
        self.state["last_completed_run_id"] = "gh_123_1"
        self.anchor()
        model.validate(self.memory)

    def test_empty_report_does_not_claim_cost(self):
        report = audit.summarize(self.state, self.memory, self.now)
        self.assertEqual(report["paid_calls_recorded"], 0)
        self.assertEqual(report["reservations_total_micro_usd"], 0)
        self.assertEqual(report["known_completed_usage_estimate_micro_usd"], 0)
        self.assertEqual(report["gate_at_audit_time"], "potentially_eligible_not_authorized")

    def test_completed_receipt_is_counted_without_conflating_reservation_and_usage(self):
        self.completed_call()
        report = audit.summarize(self.state, self.memory, self.now)
        self.assertEqual(report["paid_calls_recorded"], 1)
        self.assertEqual(report["reservations_total_micro_usd"], 20000)
        self.assertEqual(report["known_completed_usage_estimate_micro_usd"], 170)
        self.assertEqual(report["applied_features"], ["context"])
        self.assertEqual(report["runs"][0]["validation_before_errors"], 240)
        self.assertEqual(report["runs"][0]["validation_after_errors"], 192)
        self.assertEqual(report["gate_at_audit_time"], "absence_or_daily_gate")

    def test_anchor_tampering_fails_closed(self):
        self.state[model.ANCHOR] = "0" * 64
        with self.assertRaisesRegex(ValueError, "anchor"):
            audit.summarize(self.state, self.memory, self.now)

    def test_unresolved_reservation_not_misreported_as_paid_success(self):
        self.memory["entries"].append({
            "run_id": "gh_999_1", "at": "2026-11-02T18:34:00+00:00",
            "reserved_micro_usd": model.RESERVE, "request_sha256": "b" * 64,
            "status": "pending", "proposal": None, "trial": None,
            "applied": False, "usage": None, "response_id": None,
        })
        self.state["inflight_run_id"] = "gh_999_1"
        self.state["last_claimed_at"] = "2026-11-02T18:34:00+00:00"
        self.anchor()
        report = audit.summarize(self.state, self.memory, self.now)
        self.assertEqual(report["paid_calls_recorded"], 0)
        self.assertEqual(report["reservations_total_micro_usd"], 20000)
        self.assertEqual(report["unresolved_run_ids"], ["gh_999_1"])
        self.assertEqual(report["gate_at_audit_time"], "unresolved_run")

    def test_bad_usage_receipt_is_rejected_by_existing_validator(self):
        self.completed_call()
        self.memory["entries"][0]["usage"]["estimated_upper_micro_usd"] = 1
        self.anchor()
        with self.assertRaises(ValueError):
            audit.summarize(self.state, self.memory, self.now)

    def test_control_clock_regression_fails_closed(self):
        self.state["last_claimed_at"] = "2026-11-04T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "audit time"):
            audit.summarize(self.state, self.memory, self.now)

    def test_paused_state_stays_paused(self):
        self.state["enabled"] = False
        self.assertEqual(audit.summarize(self.state, self.memory, self.now)["gate_at_audit_time"], "paused")

    def test_no_input_mutation(self):
        original_state, original_memory = deepcopy(self.state), deepcopy(self.memory)
        audit.summarize(self.state, self.memory, self.now)
        self.assertEqual(self.state, original_state)
        self.assertEqual(self.memory, original_memory)


if __name__ == "__main__":
    unittest.main()
