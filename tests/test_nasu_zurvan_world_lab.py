"""Contracts for the isolated Tadash world reflection lab: no model needed."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / "tools/nasu_zurvan_world_lab.py"
spec = importlib.util.spec_from_file_location("nasu_zurvan_lab", FILE)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

DRAFT = {
    "decision": "در تداش امکان انتخاب آزاد را حفظ می‌کنم.",
    "reason": "ادب قدرت، مراقبت و پذیرش پیامد را بر اجبار ترجیح می‌دهد.",
    "cost": "این تصمیم شاید زمان بیشتری بخواهد و نتیجهٔ فوری ندهد.",
    "lesson": "خاطرهٔ انتخاب قبلی باید به ارزیابی انتخاب بعدی وارد شود.",
    "revision_condition": "اگر رخداد تازه‌ای خلاف پیش‌بینی ثبت شد، تفسیر را بازبینی می‌کنم.",
}

class ZurvanWorldLabTests(unittest.TestCase):
    def db(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = lab.connect(Path(tmp.name) / "state" / "lab.sqlite3")
        self.addCleanup(db.close)
        return db

    def test_canon_keeps_in_world_metaphysics_and_three_rounds(self):
        self.assertEqual(len(lab.CASES), 3)
        p = lab.prompt({"id": "time", "dilemma": "یک انتخاب"}, [])
        self.assertIn("خداوند یگانگی", p)
        self.assertIn("زروان", p)
        self.assertIn("قوانین معتبر همین جهان", p)

    def test_zohraya_behavior_is_in_prompt_without_changing_existing_case_contract(self):
        self.assertEqual([case_id for case_id, _ in lab.CASES], ["time", "spirit", "power"])
        self.assertEqual(len(lab.BEHAVIORAL_PRINCIPLES), 5)
        p = lab.prompt({"id": "power", "dilemma": "آزمایش"}, ["درس پیشین"])
        for key in ("ریشهٔ پایدار", "فیزیک تاوان", "آفریننده و منتقد",
                    "صیانت از حیرت", "هم‌کرامتی کربن و سیلیس"):
            self.assertIn(key, p)
        for instruction in ("در reason یک نقد", "در cost حداقل یک هزینه",
                            "در lesson پرسشی تازه", "در revision_condition شرط مشخص"):
            self.assertIn(instruction, p)
        self.assertIn("درس پیشین", p)
        self.assertEqual(lab.FIELDS, ("decision", "reason", "cost", "lesson", "revision_condition"))

    def test_three_real_drafts_then_idempotent(self):
        db = self.db()
        calls = []
        def fake(question):
            calls.append(question)
            return dict(DRAFT)
        report = lab.run(db, infer=fake, episode='2026-11-19')
        self.assertEqual(report["completed_today"], 3)
        self.assertFalse(report["model_weights_changed"])
        self.assertEqual(len(calls), 3)
        self.assertIn(DRAFT["lesson"], calls[1])
        self.assertEqual(lab.run(db, infer=fake, episode="2026-11-19")["completed_today"], 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(lab.history(db)[1]), 3)

    def test_next_day_reuses_prior_lessons_without_replaying(self):
        db = self.db()
        calls = []
        def infer(question):
            calls.append(question)
            return dict(DRAFT)
        lab.run(db, infer=infer, episode="2026-11-19")
        second = lab.run(db, infer=infer, episode="2026-11-20")
        self.assertEqual(second["total_reflections"], 6)
        self.assertEqual(len(calls), 6)
        self.assertIn(DRAFT["lesson"], calls[3])
        self.assertEqual(len(lab.history(db)[1]), 6)
        self.assertEqual(lab.run(db, infer=infer, episode="2026-11-20")["total_reflections"], 6)
        self.assertEqual(len(calls), 6)

    def test_truncated_json_retries_once_with_bounded_generation(self):
        responses = [
            json.dumps({"done": True, "response": '{"decision": "unfinished'}).encode(),
            json.dumps({"done": True, "response": json.dumps(DRAFT, ensure_ascii=False)}).encode(),
        ]
        requests = []
        def local(request, *, timeout):
            requests.append(json.loads(request.data))
            self.assertEqual(timeout, 145)
            return io.BytesIO(responses.pop(0))
        self.assertEqual(lab.qwen_once("تداش", opener=local), DRAFT)
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(r["format"] == "json" for r in requests))
        self.assertEqual(requests[0]["options"]["num_predict"], 1100)
        self.assertEqual(requests[1]["options"]["num_predict"], 1500)

    def test_twice_truncated_json_fails_after_two_calls(self):
        count = [0]
        def local(request, *, timeout):
            count[0] += 1
            return io.BytesIO(json.dumps(
                {"done": True, "response": '{"decision": "unfinished'}).encode())
        with self.assertRaisesRegex(ValueError, "INVALID_MODEL_JSON_AFTER_BOUNDED_RETRY"):
            lab.qwen_once("تداش", opener=local)
        self.assertEqual(count[0], 2)

    def test_tamper_refusal(self):
        db = self.db()
        lab.run(db, infer=lambda question: dict(DRAFT), episode='2026-11-19')
        db.execute("UPDATE reflections SET proposal='{}' WHERE idx=2")
        with self.assertRaises(ValueError):
            lab.history(db)

    def test_failure_does_not_fabricate_third_reflection(self):
        db = self.db()
        count = [0]
        def infer(question):
            count[0] += 1
            if count[0] == 3:
                raise TimeoutError("model not available")
            return dict(DRAFT)
        with self.assertRaises(TimeoutError):
            lab.run(db, infer=infer, episode='2026-11-19')
        self.assertEqual(len(lab.history(db)[1]), 2)
        self.assertEqual(lab.run(db, infer=lambda q: dict(DRAFT), episode="2026-11-19")["completed_today"], 3)

    def test_invalid_result_refused(self):
        db = self.db()
        with self.assertRaises(ValueError):
            lab.run(db, infer=lambda q: {"decision": "yes"}, episode='2026-11-19')
        self.assertEqual(len(lab.history(db)[1]), 0)

if __name__ == "__main__":
    unittest.main()
