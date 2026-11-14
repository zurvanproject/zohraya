"""Offline tests for human-only Nasuraya image review ledger."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import nasuraya_visual_review as review


class ReviewTests(unittest.TestCase):
    def test_pending_form_not_claimed_as_success(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not decoded test payload")
            entry = review.form(path)
            self.assertFalse(review.validate(entry)[1])
            summary = review.report([])
            self.assertEqual(summary["reviewed_count"], 0)
            self.assertFalse(summary["sufficient_samples_for_comparison"])
            self.assertIsNone(summary["scores"]["face_identity_consistent"]["pass_fraction"])
            self.assertFalse(summary["visual_review_automated"])
            self.assertFalse(summary["approval_for_publication"])

    def test_ten_distinct_complete_reviews(self):
        with TemporaryDirectory() as tmp:
            files = []
            for i in range(10):
                path = Path(tmp) / f"sample-{i}.png"
                path.write_bytes(b"\x89PNG\r\n\x1a\n" + f"sample-{i}".encode())
                entry = review.form(path)
                entry["reviewer"] = "human reviewer"
                entry["reviewed_at_utc"] = "2026-11-08T11:00:00Z"
                entry["scores"] = {key: True for key in review.CRITERIA}
                if i % 2:
                    entry["scores"]["feet_anatomically_consistent"] = "not_visible"
                if i == 3:
                    entry["scores"]["hands_anatomically_consistent"] = False
                rpath = Path(tmp) / f"review-{i}.json"
                rpath.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
                files.append(rpath)
            summary = review.report(files)
            self.assertEqual(summary["sample_count"], 10)
            self.assertEqual(summary["reviewed_count"], 10)
            self.assertTrue(summary["sufficient_samples_for_comparison"])
            self.assertEqual(summary["scores"]["feet_anatomically_consistent"]["denominator"], 5)
            self.assertEqual(summary["scores"]["feet_anatomically_consistent"]["not_visible"], 5)
            self.assertEqual(summary["scores"]["hands_anatomically_consistent"]["pass_fraction"], .9)
            self.assertFalse(summary["approval_for_publication"])

    def test_duplicates_do_not_inflate_sample_count(self):
        with TemporaryDirectory() as tmp:
            img = Path(tmp) / "image.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\nSAMPLE")
            entry = review.form(img)
            p1, p2 = Path(tmp) / "r1.json", Path(tmp) / "r2.json"
            p1.write_text(json.dumps(entry))
            p2.write_text(json.dumps(entry))
            with self.assertRaisesRegex(ValueError, "duplicate image hash"):
                review.report([p1, p2])

    def test_invalid_scores_and_unverified_reviewers(self):
        with TemporaryDirectory() as tmp:
            img = Path(tmp) / "image.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\nSAMPLE")
            base = review.form(img)
            incomplete = deepcopy(base)
            incomplete["scores"]["face_identity_consistent"] = True
            with self.assertRaisesRegex(ValueError, "partially"):
                review.validate(incomplete)
            forged = deepcopy(base)
            forged["reviewer"] = "anonymous"
            with self.assertRaisesRegex(ValueError, "pending"):
                review.validate(forged)
            invalid = deepcopy(base)
            invalid["scores"]["face_identity_consistent"] = 1
            with self.assertRaisesRegex(ValueError, "scores must"):
                review.validate(invalid)
            complete = deepcopy(base)
            complete["scores"] = {k: True for k in review.CRITERIA}
            complete["reviewer"] = "reviewer"
            complete["reviewed_at_utc"] = "2026-11-08T11:00:00"  # no TZ
            with self.assertRaisesRegex(ValueError, "UTC"):
                review.validate(complete)
            complete["reviewed_at_utc"] = datetime.now(timezone.utc).isoformat()
            self.assertTrue(review.validate(complete)[1])


if __name__ == "__main__":
    unittest.main()
