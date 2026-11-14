"""Synthetic tests; no network, model download, real Awake data, or production writes."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/"tools"/"nasu_offline_research_queue.py"
SEEDS=ROOT/"docs"/"nasuraya_offline_research_seeds_v1.json"
spec=importlib.util.spec_from_file_location("nasu_research_queue",MOD)
queue=importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)
T0=dt.datetime(2026,11,16,3,0,0,tzinfo=dt.timezone.utc)


class ResearchQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.db=queue.connect(self.base/"research.sqlite3")

    def tearDown(self):
        self.db.close()

    def test_seed_and_weekly_bounded_generation(self):
        fake=lambda q:("SYNTHETIC_UNVERIFIED_NOTE", "a"*64)
        first=queue.run(self.db,SEEDS,T0,infer=fake)
        self.assertEqual(first["status"],"draft_recorded")
        self.assertEqual(queue.verify(self.db)["notes"],1)
        too_soon=queue.run(self.db,SEEDS,T0+dt.timedelta(days=1),infer=fake)
        self.assertEqual(too_soon["status"],"not_due")
        self.assertEqual(queue.verify(self.db)["notes"],1)
        later=queue.run(self.db,SEEDS,T0+dt.timedelta(days=7),infer=fake)
        self.assertEqual(later["status"],"draft_recorded")
        v=queue.verify(self.db)
        self.assertEqual(v["notes"],2)
        self.assertEqual(v["pending"],24)
        self.assertNotEqual(v["last_hash"],"0"*64)
        labels=self.db.execute("SELECT DISTINCT label FROM notes").fetchall()
        self.assertEqual(labels,[("UNVERIFIED_DRAFT",)])

    def test_missing_local_model_does_not_spend_attempts(self):
        with mock.patch.object(queue,"MODEL",self.base/"does-not-exist.gguf"):
            result=queue.run(self.db,SEEDS,T0)
        self.assertEqual(result["status"],"blocked_model_missing")
        self.assertEqual(self.db.execute("SELECT SUM(attempts) FROM tasks").fetchone()[0],0)
        self.assertEqual(queue.verify(self.db)["notes"],0)

    def test_failing_model_preserves_evidence_and_pending_work(self):
        def fails(q):raise RuntimeError("synthetic model failure")
        result=queue.run(self.db,SEEDS,T0,infer=fails)
        self.assertEqual(result["status"],"failed_no_new_note")
        self.assertEqual(queue.verify(self.db)["notes"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0],26)
        self.assertEqual(self.db.execute("SELECT attempts FROM tasks WHERE ordinal=0").fetchone()[0],1)

    def test_note_tampering_rejected(self):
        queue.run(self.db,SEEDS,T0,infer=lambda _:("SYNTHETIC_NOTE","a"*64))
        self.db.execute("UPDATE notes SET output='tampered'")
        with self.assertRaises(ValueError):
            queue.verify(self.db)

    def test_seed_changes_or_queue_corruption_fail_closed(self):
        queue.seed(self.db,SEEDS)
        self.db.execute("UPDATE tasks SET question='HACKED' WHERE ordinal=0")
        with self.assertRaises(ValueError):
            queue.seed(self.db,SEEDS)
        raw=json.loads(SEEDS.read_text())
        raw["tasks"][0]["question"]="New question must be explicitly reviewed before continuation."
        test_seed=self.base/"mutated.json"
        test_seed.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            queue.seed(self.db,test_seed)

    def test_script_syntax(self):
        subprocess.run(["bash","-n",str(ROOT/"tools"/"install_nasu_offline_research.sh")],check=True)
        subprocess.run(["python3","-m","py_compile",str(MOD)],check=True)


if __name__=="__main__":
    unittest.main()
