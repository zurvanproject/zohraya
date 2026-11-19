"""Bounded contracts for the educational Kavakeb three-gazes practice."""
import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / "tools/nasu_kavakeb_three_gazes.py"
spec = importlib.util.spec_from_file_location("nasu_kavakeb", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def journal(access="viewed_image"):
    return {
        "source": {"page": 71, "access": access},
        "rounds": [
            {"phase": "observe", "observed": "سه حلقه قابل مشاهده است" if access == "viewed_image" else "",
             "hypothesis": "", "unknown": "تعداد نوشته‌های حاشیه مشخص نیست",
             "revision": "", "score": 1},
            {"phase": "geometry", "observed": "دایره در مرکز شکل است" if access == "viewed_image" else "",
             "hypothesis": "شاید آرایش هندسی برای دسته‌بندی باشد",
             "unknown": "خوانش واژه‌ها نامعلوم است",
             "revision": "تقسیم‌ها را دوباره بررسی می‌کنم", "score": 2},
            {"phase": "revise", "observed": "",
             "hypothesis": "تعبیر فقط حدس است",
             "unknown": "کارکرد دقیق شکل از این صفحه ثابت نمی‌شود",
             "revision": "اگر نسخهٔ خواناتر پیدا شد، برداشت را اصلاح می‌کنم", "score": 3},
        ],
    }

class BookPracticeContracts(unittest.TestCase):
    def test_plan_has_three_distinct_passes_and_exact_book_anchors(self):
        p = mod.plan()
        self.assertEqual(p["state"], "PLAN_NOT_PERFORMED")
        self.assertEqual(p["duration_seconds"], 660)
        self.assertEqual([x["id"] for x in p["three_passes"]], ["observe", "geometry", "revise"])
        self.assertEqual([x["book_page"] for x in p["three_passes"]], [83, 84, 85])
        self.assertEqual(p["source"]["pages"], 154)

    def test_magic_square_checks_all_lines_without_occult_claims(self):
        d = mod.demo_square()
        self.assertTrue(d["pass_2"]["equal_to_15"])
        self.assertEqual(d["pass_2"]["rows"], [15] * 3)
        self.assertEqual(d["pass_2"]["columns"], [15] * 3)
        self.assertEqual(d["pass_2"]["diagonals"], [15] * 2)
        self.assertIn("NOT_A_BOOK_IMAGE_OBSERVATION", d["state"])

    def test_three_rounds_can_be_structurally_checked_not_certified(self):
        result = mod.assess(journal())
        self.assertEqual(result["state"], "JOURNAL_SCHEMA_CHECKED_ONLY")
        self.assertTrue(result["not_independently_verified"])
        self.assertEqual(result["self_reported_score_total"], 6)
        self.assertEqual(len(result["record_sha256"]), 64)

    def test_text_only_cannot_pretend_to_have_seen_image(self):
        record = journal("text_only")
        record["rounds"][0]["observed"] = "دیدم"
        with self.assertRaisesRegex(ValueError, "NO_IMAGE_NO_DIRECT_VISUAL_OBSERVATION"):
            mod.assess(record)
        record = journal("not_available")
        self.assertFalse(mod.assess(record)["observed_image"])

    def test_first_pass_cannot_supply_unsupported_interpretation(self):
        record = journal()
        record["rounds"][0]["hypothesis"] = "به یقین آینده را پیشگویی می‌کند"
        with self.assertRaisesRegex(ValueError, "FIRST_PASS"):
            mod.assess(record)

    def test_round_order_exact_score_bound_and_source_are_checked(self):
        record = journal()
        record["rounds"].reverse()
        with self.assertRaisesRegex(ValueError, "WRONG_ROUND_ORDER"):
            mod.assess(record)
        record = journal()
        record["rounds"][1]["score"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_SELF_REPORTED_SCORE"):
            mod.assess(record)
        record = journal()
        record["source"]["page"] = 155
        with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_PROVENANCE"):
            mod.assess(record)

    def test_square_rejects_malformed_and_noninteger_input(self):
        with self.assertRaises(ValueError):
            mod.square_sums([[1, 2], [3, 4], [5, 6]])
        with self.assertRaises(ValueError):
            mod.square_sums([[True, 2, 3], [4, 5, 6], [7, 8, 9]])

if __name__ == "__main__":
    unittest.main()
