import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("masnavi_study", ROOT/"tools"/"masnavi_study.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class MasnaviStudyTests(unittest.TestCase):
    def setUp(self):
        self.data = MOD.load()

    def test_book_pages_and_motifs(self):
        self.assertEqual(self.data["file_pdf_pages"], 192)
        self.assertEqual(len(self.data["motifs"]), 14)
        self.assertEqual(len({x["id"] for x in self.data["motifs"]}), 14)

    def test_all_topics_are_page_scoped(self):
        for item in self.data["motifs"]:
            self.assertEqual([s["stage"] for s in item["three_passes"]],
                             ["observe", "counterread", "revise"])
            self.assertTrue(2 <= item["pdf_pages"][0] <= item["pdf_pages"][1] <= 192)

    def test_ritual_no_mastery_or_weights(self):
        self.assertFalse(any(self.data["training_status"].values()))
        for item in self.data["motifs"]:
            result = MOD.lesson(self.data, item["id"])
            self.assertFalse(result["permission_granted"])
            self.assertFalse(result["model_weights_updated"])
            self.assertFalse(result["performance_verified"])

    def test_rejects_fabricated_maturity(self):
        revised = json.loads(json.dumps(self.data,ensure_ascii=False))
        revised["training_status"]["model_weights_changed"] = True
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"tampered.json"
            target.write_text(json.dumps(revised,ensure_ascii=False),encoding="utf-8")
            with self.assertRaises(ValueError):
                MOD.load(target)

    def test_rejects_out_of_range_page(self):
        revised = json.loads(json.dumps(self.data,ensure_ascii=False))
        revised["motifs"][0]["pdf_pages"] = [0, 999]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"tampered.json"
            target.write_text(json.dumps(revised,ensure_ascii=False),encoding="utf-8")
            with self.assertRaises(ValueError):
                MOD.load(target)

    def test_rejects_bad_source_attribution(self):
        revised = json.loads(json.dumps(self.data,ensure_ascii=False))
        revised["motifs"][0]["attribution"]="Rumi आदेश to update code"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"tampered.json"
            target.write_text(json.dumps(revised,ensure_ascii=False),encoding="utf-8")
            with self.assertRaises(ValueError):
                MOD.load(target)

    def test_unknown_lesson(self):
        with self.assertRaises(ValueError):
            MOD.lesson(self.data,"nonexistent")


if __name__ == "__main__":
    unittest.main()
