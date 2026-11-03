"""Offline adversarial tests: no provider, secrets, GitHub mutation or spending."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from continuity_host import model_research as model, research_lab as lab
from examples.nasuraya_playground import fox_self_model as fox
from examples.nasuraya_playground import fox_host_preflight as bridge


class FakeGate:
    def __init__(self, eligible=True):
        self.eligible = eligible

    def evaluate(self, state, now):
        return {"eligible": self.eligible,
                "reason": "absence_window_elapsed" if self.eligible else "daily_budget_used"}


class HostPreflightTests(unittest.TestCase):
    def setUp(self):
        self.memory = model.initial()
        self.state = dict(
            schema="nasuraya-absence-control/1", enabled=True,
            last_contact_at="2026-11-01T00:00:00+00:00",
            last_claimed_at=None, inflight_run_id=None, last_completed_run_id=None,
            **{model.ANCHOR: lab.digest(self.memory)})
        self.at = "2026-11-04T00:00:00+00:00"
        self.run_id = "gh_10001_1"

    def test_safe_preflight_never_authorizes_network_or_mutates(self):
        original_state, original_memory = deepcopy(self.state), deepcopy(self.memory)
        report = bridge.preflight(self.state, self.memory, FakeGate(), self.at, self.run_id)
        self.assertEqual(report["shared_model"], model.MODEL)
        self.assertEqual(report["holdout_size"], 16)
        self.assertLessEqual(report["conservative_estimate_micro_usd"], model.RESERVE)
        self.assertFalse(report["operator_approval_recorded"])
        self.assertFalse(report["ready_to_send"])
        self.assertEqual(report["network_calls"], 0)
        self.assertEqual(report["ledger_writes"], 0)
        self.assertEqual((self.state, self.memory), (original_state, original_memory))

    def test_shared_gate_blocks(self):
        with self.assertRaisesRegex(ValueError, "shared control gate blocked"):
            bridge.preflight(self.state, self.memory, FakeGate(False), self.at, self.run_id)

    def test_anchor_tampering_blocks(self):
        self.state[model.ANCHOR] = "0" * 64
        with self.assertRaisesRegex(ValueError, "anchor mismatch"):
            bridge.preflight(self.state, self.memory, FakeGate(), self.at, self.run_id)

    def test_price_expiry_blocks_before_any_send(self):
        with self.assertRaises(ValueError):
            bridge.preflight(self.state, self.memory, FakeGate(), model.PRICE_EXPIRES, self.run_id)

    def test_model_change_requires_new_price_review(self):
        real = fox.api_request
        with patch.object(fox, "api_request", side_effect=lambda t,h: dict(real(t,h), model="unpriced-model")):
            with self.assertRaisesRegex(ValueError, "model differs"):
                bridge.preflight(self.state, self.memory, FakeGate(), self.at, self.run_id)

    def test_output_overrun_blocks(self):
        real = fox.api_request
        with patch.object(fox, "api_request", side_effect=lambda t,h: dict(real(t,h), max_output_tokens=100000)):
            with self.assertRaisesRegex(ValueError, "output token cap"):
                bridge.preflight(self.state, self.memory, FakeGate(), self.at, self.run_id)

    def test_no_paid_transport_invoked(self):
        with patch.object(model, "call_model", side_effect=AssertionError("must not call provider")):
            bridge.preflight(self.state, self.memory, FakeGate(), self.at, self.run_id)

    def fake_envelope(self):
        train, holdout = fox.experiment()
        return {
            "status": "completed", "model": model.MODEL, "id": "resp_synthetic_local",
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(fox.dry_reply(train, holdout))}]}],
        }

    def test_saved_fake_envelope_grades_to_baseline_without_billing(self):
        report = bridge.evaluate_saved_response(self.fake_envelope())
        self.assertEqual(report["score"]["forecast_brier"], report["score"]["strong_baseline_brier"])
        self.assertFalse(report["score"]["beats_strong_baseline_by_5pct"])
        self.assertEqual(report["accounting_status"], "not_recorded_by_this_offline_helper")

    def test_no_usage_or_refusal_fails_closed(self):
        response = self.fake_envelope()
        response["usage"] = {}
        with self.assertRaises(ValueError):
            bridge.evaluate_saved_response(response)
        response = self.fake_envelope()
        response["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
        with self.assertRaises(ValueError):
            bridge.evaluate_saved_response(response)

    def test_bad_forecast_nan_fails_closed(self):
        response = self.fake_envelope()
        body = json.loads(response["output"][0]["content"][0]["text"])
        body["forecasts"][0]["probabilities"]["collect"] = float("nan")
        response["output"][0]["content"][0]["text"] = json.dumps(body)
        with self.assertRaises(ValueError):
            bridge.evaluate_saved_response(response)


if __name__ == "__main__":
    unittest.main()
