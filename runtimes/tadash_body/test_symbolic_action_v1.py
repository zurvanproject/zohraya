"""Sidecar tests use an explicit test double, not biological evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from symbolic_action_v1 import (Intention, NativeBodyPort, OutcomeUnknown,
    SymbolicCycle, prepare, receipt_digest, seal)


class TestPort:
    scope = "test_double_not_native_physiology"

    def __init__(self):
        self.state = dict(revision=0, arousal=.6, pain=.1, fatigue=.1,
                          energy=.8, hydration=.9)
        self.calls = 0
        self.fail = False
        self.veto = False
        self.bad_revision = False

    def snapshot(self):
        return deepcopy(self.state)

    def cycle(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic transport interruption")
        assert kwargs["external"] == {}
        assert kwargs["expected_revision"] == self.state["revision"]
        action = "protect" if self.veto else kwargs["requested"]
        self.state["revision"] += 2 if self.bad_revision else 1
        # Deliberate fixture rule, not a claim about any physiological effect.
        if action == "slow_breath":
            self.state["arousal"] -= .01
        return dict(owner=dict(selected_action=action,
                    prediction={"fixture": True}), whole_body_audit={"fixture": True})


class SymbolicActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "ledger.sqlite")
        self.port = TestPort()
        self.host = SymbolicCycle(self.path, self.port)
        self.addCleanup(self.host.close)
        self.intent = Intention("demo", "settle", 0, "2026-01-01T00:00:08+00:00")

    def run_intent(self, intent=None):
        return self.host.run(intent or self.intent, authorized=True)

    def test_plan_is_read_only(self):
        before = self.port.snapshot()
        plan = prepare(self.intent, before)
        self.assertEqual(plan["requested_action"], "slow_breath")
        self.assertEqual(self.port.snapshot(), before)
        self.assertEqual(self.port.calls, 0)
        self.assertFalse(plan["gesture_executed"])

    def test_default_authorization_denied(self):
        with self.assertRaises(PermissionError):
            self.host.run(self.intent)
        self.assertEqual(self.port.calls, 0)

    def test_truthy_nonboolean_authorization_denied(self):
        with self.assertRaises(PermissionError):
            self.host.run(self.intent, authorized=1)
        self.assertEqual(self.port.calls, 0)

    def test_only_one_native_call(self):
        receipt = self.run_intent()
        self.assertEqual(self.port.calls, 1)
        self.assertEqual(receipt["phases"][-1], "close")
        self.assertFalse(receipt["physical_protection_claimed"])

    def test_replay_has_no_body_effect(self):
        first = self.run_intent()
        state = self.port.snapshot()
        replay = self.run_intent()
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["native_calls_this_run"], 0)
        self.assertEqual(self.port.snapshot(), state)
        self.assertEqual(self.port.calls, 1)
        self.assertEqual(first["receipt_seal"], receipt_digest(replay))

    def test_reopen_retains_replay_receipt(self):
        first = self.run_intent()
        with SymbolicCycle(self.path, self.port) as restarted:
            replay = restarted.run(self.intent, authorized=True)
        self.assertEqual(first["receipt_seal"], replay["receipt_seal"])
        self.assertEqual(self.port.calls, 1)

    def test_changed_request_cannot_reuse_id(self):
        self.run_intent()
        with self.assertRaisesRegex(ValueError, "conflicting replay"):
            self.run_intent(replace(self.intent, purpose="explore"))
        self.assertEqual(self.port.calls, 1)

    def test_stale_revision_blocks_dispatch(self):
        self.port.state["revision"] = 1
        with self.assertRaisesRegex(ValueError, "stale"):
            self.run_intent()
        self.assertEqual(self.port.calls, 0)

    def test_nonfinite_or_missing_observation_blocks_dispatch(self):
        for value in (None, float("nan"), float("inf"), True, -0.1, 1.1):
            with self.subTest(value=value):
                self.port.state["arousal"] = value
                with self.assertRaises(ValueError):
                    self.run_intent()
        self.assertEqual(self.port.calls, 0)

    def test_high_fatigue_precedes_exploration(self):
        self.port.state["fatigue"] = .6
        receipt = self.run_intent(replace(self.intent, purpose="explore"))
        self.assertEqual(receipt["plan"]["requested_action"], "protect")

    def test_high_pain_precedes_settling(self):
        self.port.state["pain"] = .5
        self.assertEqual(self.run_intent()["actual_action"], "protect")

    def test_native_veto_is_retained(self):
        self.port.veto = True
        receipt = self.run_intent()
        self.assertTrue(receipt["native_veto"])
        self.assertEqual(receipt["actual_action"], "protect")
        self.assertEqual(receipt["deltas"]["arousal"], 0)

    def test_failed_dispatch_is_never_retried(self):
        self.port.fail = True
        with self.assertRaises(OutcomeUnknown):
            self.run_intent()
        self.port.fail = False
        with SymbolicCycle(self.path, self.port) as restarted:
            with self.assertRaises(OutcomeUnknown):
                restarted.run(self.intent, authorized=True)
        self.assertEqual(self.port.calls, 1)

    def test_crash_after_reservation_is_conservative(self):
        plan = prepare(self.intent, self.port.snapshot())
        self.host.db.execute("INSERT INTO symbolic_cycles VALUES (?,?,?,?,NULL)",
            (self.intent.event_id, seal(self.intent.__dict__), "running", json.dumps(plan)))
        with self.assertRaises(OutcomeUnknown):
            self.run_intent()
        self.assertEqual(self.port.calls, 0)

    def test_invalid_native_revision_becomes_unknown(self):
        self.port.bad_revision = True
        with self.assertRaises(OutcomeUnknown):
            self.run_intent()
        with self.assertRaises(OutcomeUnknown):
            self.run_intent()
        self.assertEqual(self.port.calls, 1)

    def test_unrecognized_symbol_cannot_authorize_action(self):
        with self.assertRaises(ValueError):
            self.run_intent(replace(self.intent, cue="magic_override"))
        self.assertEqual(self.port.calls, 0)

    def test_invalid_intentions(self):
        invalid = [dict(event_id=""), dict(event_id="x"*101),
            dict(purpose="heal_human"), dict(expected_revision=True),
            dict(expected_revision=-1), dict(at_utc="2026-01-01T00:00:00"),
            dict(duration_s=0), dict(duration_s=2.1), dict(duration_s=.15),
            dict(duration_s=float("nan")), dict(duration_s=True)]
        for delta in invalid:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.run_intent(replace(self.intent, **delta))
        self.assertEqual(self.port.calls, 0)

    def test_all_purposes_are_bounded(self):
        for purpose, action in (("observe","observe"), ("protect","protect"),
                                ("settle","slow_breath"), ("explore","walk")):
            self.assertEqual(prepare(replace(self.intent, purpose=purpose),
                                     self.port.snapshot())["requested_action"], action)

    def test_plan_seal_and_source_are_independent(self):
        first = prepare(self.intent, self.port.snapshot())
        payload = {k:v for k,v in first.items() if k != "seal"}
        self.assertEqual(first["seal"], seal(payload))
        first["source"]["use"] = "modified"
        second = prepare(self.intent, self.port.snapshot())
        self.assertNotEqual(first["source"], second["source"])

    def test_receipt_tampering_is_rejected(self):
        self.run_intent()
        raw = self.host.db.execute("SELECT receipt_json FROM symbolic_cycles").fetchone()[0]
        value = json.loads(raw)
        value["actual_action"] = "invented"
        self.host.db.execute("UPDATE symbolic_cycles SET receipt_json=?", (json.dumps(value),))
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.run_intent()
        self.assertEqual(self.port.calls, 1)

    def test_native_adapter_reads_only_known_fields(self):
        from types import SimpleNamespace
        fake = SimpleNamespace(revision=0,
            owner=SimpleNamespace(body=lambda: {"minimum_state": self.port.state}),
            cycle=self.port.cycle)
        adapter = NativeBodyPort(fake)
        self.assertEqual(adapter.snapshot(), self.port.snapshot())
        self.assertEqual(self.port.calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
