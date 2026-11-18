"""Offline cognitive-growth contracts. No Ollama or server connection needed."""
import datetime as dt
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / "tools/nasu_autonomous_cognition.py"
spec = importlib.util.spec_from_file_location("growth", FILE)
growth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(growth)

DRAFT = {
    "hypothesis": "Adding provenance checks will reduce ambiguous results.",
    "test": "Run the fixed contract suite and reject any changed source digest.",
    "metric": "Count failed contracts and compare to the baseline.",
    "next_topic": "frontier",
    "limitation": "A passing fixture does not prove live-system correctness.",
}

class GrowthTests(unittest.TestCase):
    def fixture(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for topic in ("continuity", "frontier"):
            path = root / growth.TOPICS[topic][0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("value = 1\n")
        db = growth.connect(root / "journal" / "cycles.sqlite3")
        self.addCleanup(db.close)
        return root, db

    def clock(self, hour):
        return dt.datetime(2026,11,18,hour,5,tzinfo=dt.timezone.utc)

    def test_utc_slots_and_non_utc_refusal(self):
        self.assertEqual(growth.slot(self.clock(11)), "2026-11-18T06")
        with self.assertRaises(ValueError):
            growth.slot(dt.datetime(2026,11,18,1,tzinfo=dt.timezone(dt.timedelta(hours=1))))

    def test_draft_schema_and_scope(self):
        self.assertEqual(growth.validate(dict(DRAFT))["next_topic"], "frontier")
        with self.assertRaises(ValueError):
            growth.validate(dict(DRAFT, next_topic="all_shell_commands"))
        with self.assertRaises(ValueError):
            growth.validate(dict(DRAFT, token="secret"))

    def test_source_symlink_is_rejected(self):
        root, _ = self.fixture()
        p = root / growth.TOPICS["continuity"][0]
        p.unlink()
        p.symlink_to(root / "other")
        with self.assertRaises(ValueError):
            growth.source("continuity", root)

    def test_persistent_verified_cycle_and_next_goal(self):
        root, db = self.fixture()
        inference = lambda *args: dict(DRAFT)
        first = growth.run(db, now=self.clock(1), root=root,
                           infer=inference, tester=lambda *args:"PASS")
        self.assertEqual(first["model"], "UNVERIFIED_DRAFT")
        self.assertEqual(first["topic"], "continuity")
        self.assertEqual(growth.verify(db)["completed"], 1)
        repeated = growth.run(db, now=self.clock(2), root=root,
                              infer=inference, tester=lambda *args:"PASS")
        self.assertEqual(repeated["status"], "already_attempted")
        second = growth.run(db, now=self.clock(8), root=root,
                            infer=inference, tester=lambda *args:"PASS")
        self.assertEqual(second["topic"], "frontier")
        self.assertEqual(growth.verify(db)["completed"], 2)

    def test_model_failure_is_saved_not_faked(self):
        root, db = self.fixture()
        def fail(*args):
            raise TimeoutError("No model")
        result = growth.run(db, now=self.clock(1), root=root,
                            infer=fail, tester=lambda *args:"PASS")
        self.assertEqual(result["model"], "model_unavailable:TimeoutError")
        row = db.execute("SELECT proposal FROM cycles").fetchone()[0]
        self.assertEqual(row, "{}")
        self.assertEqual(growth.verify(db)["completed"], 1)

    def test_post_write_change_is_detected(self):
        root, db = self.fixture()
        growth.run(db, now=self.clock(1), root=root,
                   infer=lambda *args:dict(DRAFT), tester=lambda *args:"PASS")
        db.execute("UPDATE cycles SET fixed_result='FAIL'")
        with self.assertRaises(ValueError):
            growth.verify(db)

    def test_static_source_syntax_is_checked(self):
        root, _ = self.fixture()
        (root / growth.TOPICS["continuity"][0]).write_text("def malformed(:\n")
        with self.assertRaises(SyntaxError):
            growth.source("continuity",root)

if __name__ == "__main__":
    unittest.main()
