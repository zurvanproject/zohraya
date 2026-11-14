import json
from pathlib import Path
import tempfile
import unittest

from examples.nasuraya_research import public_receipt_lineage as adapter


class PublicReceiptLineageTests(unittest.TestCase):
    def test_replays_and_synthetic_controls_are_not_independent_support(self):
        audit = adapter.audit()
        self.assertEqual((audit["receipt_count"], audit["signature_pair_count"]), (10, 5))
        for claim, data in audit["propositions"].items():
            with self.subTest(claim=claim):
                self.assertEqual(data["naive_url_support"], 2)
                synthetic = claim == "recheck_synthetic_failure"
                self.assertEqual(data["support"], 0 if synthetic else 1)
                self.assertEqual(data["decision"], "abstain")
                self.assertEqual([row["kind"] for row in data["rows"]],
                                 ["synthetic", "synthetic"] if synthetic else ["execution", "replay"])

    def test_distinct_recovery_and_repair_claims_have_common_upstream(self):
        props = adapter.audit()["propositions"]
        recovery = props["recover_after_injected_corruption"]["rows"][0]
        repaired = props["read_locally_after_verified_repair"]["rows"][0]
        self.assertNotEqual(recovery["receipt_id"], repaired["receipt_id"])
        self.assertEqual(recovery["root_id"], repaired["root_id"])

    def test_checkout_line_endings_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.json"
            raw = adapter.FIXTURE.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(raw.replace(b"\n", b"\r\n"))
            self.assertEqual(adapter.audit(path), adapter.audit())
            path.write_bytes(raw.replace(b"PROBE=FORCED", b"PROBE=AUTO"))
            with self.assertRaisesRegex(ValueError, "checksum"):
                adapter.audit(path)

    def test_pair_parser_requires_revalidation_and_distinct_modes(self):
        raw = json.loads(adapter.FIXTURE.read_text(encoding="utf-8"))["receipts"]
        with self.assertRaisesRegex(ValueError, "unmet claim conditions"):
            adapter._pairs([dict(row, result=row["result"].replace("PROBE=FORCED", "PROBE=AUTO"))
                            for row in raw])
        with self.assertRaisesRegex(ValueError, "duplicate receipt role"):
            adapter._pairs([dict(row, result=row["result"].replace("REPAIR=REPLAY", "REPAIR=RUN"))
                            for row in raw])


if __name__ == "__main__":
    unittest.main()
