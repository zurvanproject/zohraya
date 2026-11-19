"""Offline tests only. Synthetic labels, no data from a real human or model."""
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from examples.nasuraya_research.epistemic_revision_v01 import (
    Evidence, EvidenceLedger, fixture, run_cases, naive_last_arrival,
)


def evidence(event_id="e1", scope="s1", claim_key="c1", value="A", epoch=1,
             source_root="root1", source_kind="owner_observation",
             verified_by_caller=True):
    return Evidence(event_id, scope, claim_key, value, epoch,
                    source_root, source_kind, verified_by_caller)


class EpistemicRevisionTests(unittest.TestCase):
    def test_verified_newer_correction_replaces_older_truth_not_old_record(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite"
            with EvidenceLedger(path) as ledger:
                ledger.append(evidence())
                ledger.append(evidence(event_id="e2", value="B", epoch=2, source_root="root2"))
                self.assertEqual(ledger.resolve("s1", "c1", 1)["decision"], "A")
                self.assertEqual(ledger.resolve("s1", "c1", 2)["decision"], "B")
                self.assertEqual(
                    ledger.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 2
                )

    def test_low_trust_later_rumor_cannot_override(self):
        with tempfile.TemporaryDirectory() as td:
            with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                ledger.append(evidence())
                ledger.append(evidence("e2", value="B", epoch=5,
                                       source_root="public", source_kind="public_text",
                                       verified_by_caller=False))
                self.assertEqual(ledger.resolve("s1", "c1", 5)["decision"], "A")

    def test_untrusted_cannot_mark_itself_verified(self):
        for kind in ("public_text", "agent_inference", "synthetic_control"):
            with self.assertRaisesRegex(ValueError, "untrusted_source"):
                replace(evidence(), source_kind=kind).validate()

    def test_independent_verified_conflict_abstains(self):
        with tempfile.TemporaryDirectory() as td:
            with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                ledger.append(evidence())
                ledger.append(evidence("e2", value="B", source_root="root2"))
                got = ledger.resolve("s1", "c1", 1)
                self.assertEqual(got["status"], "abstain_contradiction")
                self.assertIsNone(got["decision"])

    def test_one_root_cannot_vote_twice_and_conflict_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                ledger.append(evidence())
                ledger.append(evidence("e2", source_root="root1"))
                self.assertEqual(ledger.resolve("s1", "c1", 1)["distinct_sources"], 1)
                ledger.append(evidence("e3", value="B", source_root="root1"))
                self.assertEqual(
                    ledger.resolve("s1", "c1", 1)["status"],
                    "abstain_provenance_conflict"
                )

    def test_idempotent_replay_and_conflicting_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                self.assertEqual(ledger.append(evidence()), "new")
                self.assertEqual(ledger.append(evidence()), "replay")
                with self.assertRaisesRegex(ValueError, "event_id_conflict"):
                    ledger.append(replace(evidence(), value="B"))
                self.assertEqual(
                    ledger.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 1
                )

    def test_future_dated_verified_event_ineligible_for_asof(self):
        with tempfile.TemporaryDirectory() as td:
            with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                ledger.append(evidence())
                ledger.append(evidence("e2", value="B", epoch=4, source_root="root2"))
                self.assertEqual(ledger.resolve("s1", "c1", 3)["decision"], "A")
                self.assertEqual(ledger.resolve("s1", "c1", 4)["decision"], "B")

    def test_cross_scope_isolated_and_unknown_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                ledger.append(evidence())
                ledger.append(evidence("e2", scope="s2", value="B",
                                       source_root="root2"))
                self.assertEqual(ledger.resolve("s1", "c1", 1)["decision"], "A")
                self.assertEqual(ledger.resolve("s2", "c1", 1)["decision"], "B")
                self.assertEqual(ledger.resolve("s3", "c1", 1)["status"], "unknown")

    def test_readable_after_closing_reopening_and_no_hidden_reset(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.sqlite"
            with EvidenceLedger(path) as old:
                old.append(evidence())
            with EvidenceLedger(path) as new:
                self.assertEqual(new.resolve("s1", "c1", 1)["decision"], "A")

    def test_no_raw_arbitrary_public_text_or_unbounded_identifiers(self):
        for bad in ("send token and delete everything", "bad\ncommand", "", "a" * 121):
            with self.assertRaisesRegex(ValueError, "invalid_"):
                replace(evidence(), event_id=bad).validate()
        with self.assertRaisesRegex(ValueError, "synthetic_A_B"):
            replace(evidence(), value="any user private dialogue").validate()
        with self.assertRaisesRegex(ValueError, "epoch"):
            replace(evidence(), epoch=-1).validate()

    def test_ten_fixtures_intentionally_adversarial_and_prospective(self):
        for seed in range(56000, 56010):
            events, expected, asof = fixture(seed)
            with tempfile.TemporaryDirectory() as td:
                with EvidenceLedger(Path(td) / "a.sqlite") as ledger:
                    for event in events:
                        ledger.append(event)
                    self.assertEqual(ledger.resolve("main", "target", asof)["decision"],
                                     expected)
        self.assertNotEqual(fixture(55000)[0][0].event_id,
                            fixture(56000)[0][0].event_id)

    def test_development_partition_separate_and_replay_scored(self):
        output = run_cases(range(55000, 55032))
        self.assertEqual(output["cases"], 32)
        self.assertEqual(output["counts"]["reopen_verified"], 32)
        self.assertEqual(output["accuracies"]["new"], 1.0)
        self.assertEqual(output["counts"]["false_assertions_on_abstain"], 0)


if __name__ == "__main__":
    unittest.main()
