"""Negative controls for developmental affect. No claim of experience or sexuality."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from experiments import tadash_developmental_affect as affect


def audited_fake():
    return {"id": "real-aggregate", "origin": "verified_previous_motor_audit",
            "kind": "progress", "novelty": .8, "evidence_digest": "a" * 64}


class AffectTests(unittest.TestCase):
    def test_success_changes_proxies_and_proposal(self):
        old = vars(affect.State()).copy()
        new, proposal = affect.change(old, audited_fake())
        self.assertGreater(new["curiosity"], old["curiosity"])
        self.assertGreater(new["confidence"], old["confidence"])
        self.assertEqual(proposal, "propose_one_tiny_novel_trial")
        self.assertEqual(old, vars(affect.State()))

    def test_failed_attempt_simplifies(self):
        after, proposal = affect.change(vars(affect.State()).copy(), affect.synth_event("f1", "failed_attempt"))
        self.assertEqual(proposal, "simplify_next_trial")
        self.assertGreater(after["frustration"], .05)
        self.assertLess(after["calm"], .65)

    def test_rest_recovers_and_preserves_no_actuation(self):
        failed, _ = affect.change(vars(affect.State()).copy(), affect.synth_event("f1", "failed_attempt"))
        restored, proposal = affect.change(failed, affect.synth_event("r1", "rest"))
        self.assertLess(restored["frustration"], failed["frustration"])
        self.assertGreater(restored["calm"], failed["calm"])
        self.assertEqual(proposal, "repeat_known_safe_trial")

    def test_unsafe_event_stops(self):
        _, action = affect.change(vars(affect.State()).copy(), affect.synth_event("u1", "unsafe"))
        self.assertEqual(action, "stop_and_review")

    def test_no_synthetic_fake_progress(self):
        bad = dict(audited_fake(), origin="synthetic_fixture")
        with self.assertRaisesRegex(ValueError, "No synthetic success"):
            affect.checked_event(bad)

    def test_no_sexual_or_family_fields_accepted(self):
        for field in ("sexual_response", "libido", "relationship", "familial_reward"):
            with self.subTest(field=field):
                bad = dict(audited_fake())
                bad[field] = 1.
                with self.assertRaisesRegex(ValueError, "exact"):
                    affect.checked_event(bad)

    def test_invalid_float_bool_nan_inf(self):
        for novelty in (float("nan"), float("inf"), True, -1., 2.):
            with self.subTest(novelty=novelty):
                bad = dict(audited_fake(), novelty=novelty)
                with self.assertRaises(ValueError):
                    affect.checked_event(bad)

    def test_duplicate_idempotent_after_cold_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite"
            obj = affect.Ledger(path)
            first = obj.apply(audited_fake())
            before = obj.read()
            obj.close()
            next_obj = affect.Ledger(path)
            replay = next_obj.apply(audited_fake())
            self.assertEqual(before, next_obj.read())
            self.assertEqual(replay["state_after"], first["state_after"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(next_obj.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            next_obj.close()

    def test_conflicting_id_refused_without_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = affect.Ledger(Path(tmp) / "affect.sqlite")
            ledger.apply(audited_fake())
            saved = ledger.read()
            conflict = dict(audited_fake(), novelty=.3)
            with self.assertRaisesRegex(ValueError, "Conflicting replay"):
                ledger.apply(conflict)
            self.assertEqual(saved, ledger.read())
            ledger.close()

    def test_tampered_persistent_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite"
            db = affect.Ledger(path)
            db.close()
            with sqlite3.connect(path) as raw:
                raw.execute("UPDATE memory SET payload='{}' WHERE name='state'")
            with self.assertRaisesRegex(ValueError, "checksum"):
                affect.Ledger(path)

    def test_event_budget_is_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = affect.Ledger(Path(tmp) / "state.sqlite")
            for i in range(affect.MAX_EVENTS):
                ledger.apply(affect.synth_event(f"rest{i}", "rest"))
            with self.assertRaisesRegex(ValueError, "budget"):
                ledger.apply(affect.synth_event("extra", "rest"))
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], affect.MAX_EVENTS)
            ledger.close()

    def test_audit_origin_rejected_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "provenance"):
                affect.verify_audit(path)

    def test_actual_previous_motor_audit_only_influences_advice(self):
        path = Path(__file__).resolve().parents[1] / "docs/tadash-motor-learning-independent-audit-20261102.json"
        audit = affect.verify_audit(path)
        self.assertEqual(audit["motor_run_id"], affect.EXPECTED_MOTOR_RUN)
        with tempfile.TemporaryDirectory() as tmp:
            result = affect.demo(path, Path(tmp) / "demo")
            self.assertEqual(result["events"], 3)
            self.assertTrue(result["cold_recovered"])
            self.assertEqual(result["advice"],
                             ["propose_one_tiny_novel_trial",
                              "simplify_next_trial", "repeat_known_safe_trial"])
            self.assertTrue(result["no_actuation_or_sexual_activation"])
            saved = json.loads((Path(tmp) / "demo" / "report.json").read_text())
            self.assertEqual(saved["native_cycles_caused"], 0)
            self.assertTrue(saved["sexual_proxy_untouched"])
            self.assertEqual([e["origin"] for e in saved["events"]],
                             ["verified_previous_motor_audit", "synthetic_fixture", "synthetic_fixture"])


if __name__ == "__main__":
    unittest.main()
