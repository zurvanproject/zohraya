"""Development-only unit tests for the preregistered equal-information study."""
from dataclasses import replace
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from examples.nasuraya_research.epistemic_revision_v01 import (
    Evidence, EvidenceLedger, fixture,
)
from examples.nasuraya_research.equal_information_v02 import (
    DEV_SEEDS, HELDOUT_SEEDS, gates_pass, matched_reference,
    pinned_snapshot_digest, run_equal_information,
)


class MatchedEvidenceTests(unittest.TestCase):
    def test_dev_seeds_and_sealed_seeds_do_not_overlap(self):
        self.assertEqual(len(DEV_SEEDS), 40)
        self.assertEqual(len(HELDOUT_SEEDS), 160)
        self.assertEqual(set(DEV_SEEDS) & set(HELDOUT_SEEDS), set())
        self.assertEqual(set(seed % 10 for seed in DEV_SEEDS), set(range(10)))

    def test_reference_uses_same_as_of_and_scope(self):
        events, _, as_of = fixture(610009)
        self.assertEqual(matched_reference(events, "main", "target", as_of)["status"],
                         "supported")
        self.assertEqual(matched_reference(events, "main", "target", 4)["decision"],
                         events[-1].value)
        self.assertEqual(matched_reference(events, "other", "target", 3)["status"],
                         "unknown")

    def test_verified_newer_correction_not_latest_arrival(self):
        evidence = [
            Evidence("one", "sample", "fact", "A", 1, "root1",
                     "independent_execution", True),
            Evidence("two", "sample", "fact", "B", 2, "root2",
                     "owner_observation", True),
            Evidence("rumor", "sample", "fact", "A", 3, "root3",
                     "public_text", False),
        ]
        result = matched_reference(evidence, "sample", "fact", 4)
        self.assertEqual(result["decision"], "B")
        self.assertEqual(result["latest_epoch"], 2)

    def test_same_root_conflict_abstains_independent_of_arrival(self):
        e1 = Evidence("a", "s", "c", "A", 1, "same",
                      "owner_observation", True)
        e2 = replace(e1, event_id="b", value="B")
        result = matched_reference([e1, e2], "s", "c", 1)
        self.assertEqual(result["status"], "abstain_provenance_conflict")
        self.assertEqual(result, matched_reference([e2, e1], "s", "c", 1))

    def test_disagreeing_independent_roots_abstain(self):
        a = Evidence("a", "s", "c", "A", 1, "source_a",
                     "owner_observation", True)
        b = replace(a, event_id="b", value="B", source_root="source_b")
        self.assertEqual(
            matched_reference([a, b], "s", "c", 1)["status"],
            "abstain_contradiction",
        )

    def test_aliasing_and_reordering_are_not_new_information(self):
        events, _, as_of = fixture(610002)
        original = matched_reference(events, "main", "target", as_of)
        alias = replace(events[0], event_id="610002:extra_alias")
        scrambled = events + [alias]
        random.Random(20).shuffle(scrambled)
        self.assertEqual(original,
                         matched_reference(scrambled, "main", "target", as_of))

    def test_snapshot_digest_changes_with_damaged_record_not_row_order(self):
        with tempfile.TemporaryDirectory() as td:
            p1 = Path(td) / "a.sqlite"
            p2 = Path(td) / "b.sqlite"
            a = Evidence("a", "s", "c", "A", 1, "root_a",
                         "owner_observation", True)
            b = replace(a, event_id="b", source_root="root_b")
            with EvidenceLedger(p1) as ledger:
                ledger.append(a)
                ledger.append(b)
                digest = pinned_snapshot_digest(ledger.conn)
            with EvidenceLedger(p2) as ledger:
                ledger.append(b)
                ledger.append(a)
                self.assertEqual(digest, pinned_snapshot_digest(ledger.conn))
                # A controlled corruption on a disposable fixture, not the user's memory.
                ledger.conn.execute(
                    "UPDATE evidence SET value='B' WHERE event_id='a'"
                )
                ledger.conn.commit()
                self.assertNotEqual(digest, pinned_snapshot_digest(ledger.conn))

    def test_metadata_baseline_explains_easy_fixture_outcome(self):
        report = run_equal_information(DEV_SEEDS)
        self.assertEqual(report["cases"], 40)
        self.assertEqual(report["checks"]["same_decision"], 40)
        self.assertEqual(report["scores"]["sqlite_p1"],
                         report["scores"]["matched_p2"])
        self.assertEqual(report["checks"]["cold_reopen_invariant"], 40)
        self.assertEqual(report["checks"]["tampered_copy_detected"], 40)
        self.assertTrue(gates_pass(report))
        self.assertTrue(report["not_generalization_evidence"])

    def test_gate_rejects_failed_replay_or_hidden_false_claim(self):
        report = run_equal_information(range(610000, 610010))
        self.assertTrue(gates_pass(report))
        report["checks"]["cold_reopen_invariant"] -= 1
        self.assertFalse(gates_pass(report))
        report["checks"]["cold_reopen_invariant"] += 1
        report["checks"]["p1_false_assertion_on_unknown"] = 1
        self.assertFalse(gates_pass(report))

    def test_reference_cannot_consume_unverified_public_text_as_fact(self):
        social = Evidence("web", "s", "c", "B", 11, "page",
                          "public_text", False)
        self.assertEqual(matched_reference([social], "s", "c", 12)["status"],
                         "unknown")


if __name__ == "__main__":
    unittest.main()
