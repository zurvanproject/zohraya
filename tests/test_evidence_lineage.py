"""Frozen provenance challenge and generated-file controls for the offline rule bank."""
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from examples.nasuraya_research.evidence_lineage import decide_claim
from examples.nasuraya_research.lineage_file_control import run_file_control

CHALLENGE = Path(__file__).resolve().parents[1] / "docs/evidence/rule-transfer-lineage/holdout.json"
LOCK = "17a73e7154dde9d0cc96ffdbd806ee959f6332c6b59ed441e056d9a5bf9dffbe"


def score_challenge():
    payload = CHALLENGE.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(payload).hexdigest() != LOCK:
        raise ValueError("frozen challenge changed")
    scores = {p: Counter() for p in ("receipt_urls", "always_abstain", "lineage")}
    details = []
    for case in json.loads(payload)["cases"]:
        rows = [
            dict(receipt_id=o["public_locator"], root_id=o["claim_event"],
                 kind="execution" if o["kind"] == "execute" else o["kind"],
                 scope="public", verified=o["verified"],
                 verdict={"+": "support", "-": "oppose"}[o["verdict"]])
            for o in case["observations"]
        ]
        # Matched ablation: keep the same veto and threshold, change only provenance.
        # Count each verified address as an original source for the URL-only baseline.
        urls = [dict(row, root_id=row["receipt_id"], kind="execution") for row in rows]
        choices = {"receipt_urls": decide_claim(urls)["verdict"], "always_abstain": None,
                   "lineage": decide_claim(rows)["verdict"]}
        expected = {"select_positive": "support", "select_negative": "oppose",
                    "abstain": None}[case["expected_decision"]]
        for name, verdict in choices.items():
            scores[name]["correct"] += verdict == expected
            scores[name]["false_selections"] += expected is None and verdict is not None
            scores[name][case["stratum"] + "_correct"] += verdict == expected
        details.append({"id": case["id"], "expected": expected, "choices": choices})
    return {name: dict(counts) for name, counts in scores.items()}, details


class IndependentEvidenceTests(unittest.TestCase):
    def test_locked_provenance_challenge(self):
        scores, details = score_challenge()
        self.assertEqual(len(details), 12)
        self.assertEqual(scores["lineage"], dict(correct=12, false_selections=0,
                                                core_correct=9, stress_correct=3))
        self.assertLess(scores["receipt_urls"]["correct"], scores["lineage"]["correct"])

    def test_same_receipt_cannot_authenticate_two_roots(self):
        row = dict(receipt_id="receipt-1", root_id="a", kind="execution", scope="public",
                   verified=True, verdict="support")
        result = decide_claim([row, dict(row, root_id="b")])
        self.assertEqual(result["decision"], "abstain")
        self.assertEqual(result["reason"], "conflicting_receipt")

    def test_same_verified_receipt_cannot_be_execution_and_replay(self):
        row = dict(receipt_id="receipt-1", root_id="a", kind="execution", scope="public",
                   verified=True, verdict="support")
        second = dict(row, receipt_id="receipt-2", root_id="b")
        result = decide_claim([row, dict(row, kind="replay"), second])
        self.assertEqual((result["decision"], result["reason"]), ("abstain", "conflicting_receipt"))
        noise = dict(row, kind="replay", verified=False)
        self.assertEqual(decide_claim([row, noise, second])["decision"], "select")

    def test_unattested_origins_do_not_count(self):
        row = dict(receipt_id="receipt-1", root_id="a", kind="execution", scope="public",
                   verified=True, verdict="support")
        for invalid in (dict(root_id=None), dict(root_id=" "), dict(root_id="a "),
                        dict(receipt_id="receipt-1 "), dict(scope="private"),
                        dict(kind="synthetic"), dict(verified=1), dict(verdict="unknown")):
            with self.subTest(invalid=invalid):
                other = dict(row, receipt_id="receipt-2", root_id="b")
                result = decide_claim([row, dict(other, **invalid)])
                self.assertEqual((result["decision"], result["support"]), ("abstain", 1))

    def test_measured_file_recovery_and_bad_backup(self):
        report = run_file_control()
        traces = report["traces"]
        self.assertEqual(len({t["expected_sha256"] for t in traces}), 3)
        for trace in traces:
            self.assertNotEqual(trace["expected_sha256"], trace["damaged_sha256"])
        self.assertEqual([t["expected_sha256"] == t["after_recovery_sha256"] for t in traces],
                         [True, True, False])
        for key, expected in (("one_with_derivatives", ("abstain", 1, 0)),
                              ("two_primary_successes", ("select", 2, 0)),
                              ("with_contrary_failure", ("abstain", 2, 1))):
            result = report[key]
            self.assertEqual((result["decision"], result["support"], result["oppose"]), expected)


if __name__ == "__main__":
    unittest.main()
