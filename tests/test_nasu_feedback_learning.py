"""Offline feedback-learning lab tests; deterministic fake inference, no Ollama."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "tools/nasu_feedback_learning.py"
spec = importlib.util.spec_from_file_location("feedback", MODULE)
feedback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feedback)

def clock(day):
    return dt.datetime(2026, 11, day, 12, 0, tzinfo=dt.timezone.utc)

def answer(value):
    return {"answer": value, "reason": "Grounded in the stated test scenario."}

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "journal" / "feedback.sqlite3"
        self.db = feedback.connect(self.path)
        self.addCleanup(self.db.close)

    def test_first_error_produces_verifiable_transfer_improvement(self):
        questions = []
        def infer(question, rules):
            questions.append((question, rules))
            # deliberately wrong on baseline; memory rule allows correct result
            return answer("NO" if rules else "YES")
        report = feedback.run(self.db, now=clock(18), infer=infer)
        self.assertEqual(report["status"], "EVALUATED")
        self.assertEqual(report["train_correct"], False)
        self.assertEqual(report["baseline_correct"], False)
        self.assertEqual(report["coached_correct"], True)
        self.assertEqual(report["rules_used"], 1)
        self.assertEqual(len(questions), 3)
        self.assertNotEqual(questions[0][0], questions[1][0], "holdout must differ from training")
        self.assertEqual(questions[1][1], [], "holdout baseline must not receive the rule")
        self.assertEqual(feedback.verify(self.db)["coached_correct"], 1)

    def test_correct_training_does_not_fabricate_a_memory_gain(self):
        result = feedback.run(self.db, now=clock(18), infer=lambda q, rules: answer("NO"))
        self.assertTrue(result["train_correct"])
        self.assertTrue(result["baseline_correct"])
        self.assertTrue(result["coached_correct"])
        self.assertEqual(result["rules_used"], 0)
        row = json.loads(self.db.execute("SELECT payload FROM runs").fetchone()[0])
        self.assertEqual(row["verified_rule"], "")
        self.assertEqual(feedback.verify(self.db)["comparable"], 1)

    def test_no_repeat_same_day_or_next_task(self):
        calls = []
        def infer(q,r):
            calls.append(1)
            return answer("NO")
        a = feedback.run(self.db, now=clock(18), infer=infer)
        b = feedback.run(self.db, now=clock(18), infer=infer)
        c = feedback.run(self.db, now=clock(19), infer=infer)
        self.assertEqual(a["task"], "source")
        self.assertEqual(b["status"], "already_attempted")
        self.assertEqual(c["task"], "integrity")
        self.assertEqual(feedback.verify(self.db)["completed"], 2)

    def test_model_failure_is_not_reported_as_learning(self):
        def fail(*args):
            raise TimeoutError()
        result = feedback.run(self.db, now=clock(18), infer=fail)
        self.assertEqual(result["status"], "MODEL_UNAVAILABLE:TimeoutError")
        self.assertIsNone(result["coached_correct"])
        self.assertEqual(feedback.verify(self.db)["comparable"], 0)
        self.assertEqual(feedback.verify(self.db)["completed"], 1)

    def test_detects_modified_grades_even_with_sqlite_integrity_ok(self):
        feedback.run(self.db, now=clock(18), infer=lambda q,r:answer("NO"))
        row = self.db.execute("SELECT payload FROM runs").fetchone()[0]
        data = json.loads(row)
        data["coached_correct"] = not data["coached_correct"]
        self.db.execute("UPDATE runs SET payload=?", (feedback.canon(data),))
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(ValueError, "Modified learning receipt"):
            feedback.verify(self.db)

    def test_reserved_crash_is_counted_without_forging_completion(self):
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                        ("2026-11-17", 0, "reserved", "{}", feedback.ZERO, ""))
        status = feedback.verify(self.db)
        self.assertEqual(status["reserved"], 1)
        result = feedback.run(self.db, now=clock(18), infer=lambda q,r:answer("NO"))
        self.assertEqual(result["task"], "integrity")
        self.assertEqual(feedback.verify(self.db)["reserved"], 1)

    def test_finite_schedule_exhausts_instead_of_endless_inference(self):
        calls = 0
        def infer(q,r):
            nonlocal calls
            calls += 1
            return answer("NO")
        for day in range(1, len(feedback.PAIRS)+1):
            result = feedback.run(self.db, now=clock(day), infer=infer)
            self.assertEqual(result["status"], "EVALUATED")
        done = feedback.run(self.db, now=clock(18), infer=infer)
        self.assertEqual(done["status"], "finite_bank_complete")
        self.assertEqual(feedback.verify(self.db)["completed"], len(feedback.PAIRS))

    def test_rejects_invalid_response_and_non_utc(self):
        for bad in ({"answer":"YES"}, {"answer":"MAYBE","reason":"Not an expected value."},
                    {"answer":"YES","reason":"short","token":"secret"}):
            with self.assertRaises(ValueError):
                feedback.validate_answer(bad)
        with self.assertRaises(ValueError):
            feedback.run(self.db, now=dt.datetime(2026, 11, 18, 12),
                         infer=lambda q,r:answer("NO"))

    def test_task_labels_not_passed_into_model(self):
        questions = []
        def infer(question, rules):
            questions.append((question, rules))
            return answer("NO")
        feedback.run(self.db, now=clock(18), infer=infer)
        self.assertEqual(len(questions), 2)
        self.assertFalse(any("Temporal change for a particular source" in q for q,_ in questions))
        self.assertFalse(any(r for _,r in questions))

    def test_learning_state_symlink_refused(self):
        other = Path(self.tmp.name) / "alias.sqlite"
        other.symlink_to(self.path)
        with self.assertRaises(ValueError):
            feedback.connect(other)

if __name__ == "__main__":
    unittest.main()
