import base64
from contextlib import closing
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from urllib.request import urlopen
import zipfile

JOBS = Path(__file__).resolve().parents[1] / "tools/bridge_jobs"
spec = importlib.util.spec_from_file_location("native_feedback_job", JOBS / "moltbook_reflection_train.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture_context(memory):
    memory.mkdir(parents=True, exist_ok=True)
    first = {"source": m.ORIGIN, "synthetic_fixture": True, "version": 1}
    second = {"source": m.ORIGIN, "synthetic_fixture": True, "version": 2}
    record = {"baseline_sha256": m.digest(first), "observation_sha256": m.digest(second)}
    with closing(sqlite3.connect(memory / "episodes.sqlite3")) as db, db:
        db.executescript("CREATE TABLE episodes(digest TEXT PRIMARY KEY,body TEXT);"
                        "CREATE TABLE decisions(id TEXT PRIMARY KEY,body TEXT,digest TEXT);"
                        "CREATE TABLE decision_head(slot INTEGER,id TEXT);")
        for ep in (first, second):
            db.execute("INSERT INTO episodes VALUES (?,?)", (m.digest(ep), m.canonical(ep)))
        db.execute("INSERT INTO decisions VALUES ('fixture',?,?)", (m.canonical(record), m.digest(record)))
        db.execute("INSERT INTO decision_head VALUES (1,'fixture')")
    return m.source_context(memory)


class NativeFeedbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = None
        configured = os.environ.get("NASURAYA_NATIVE_FIXTURE")
        if configured:
            cls.installation = Path(configured).resolve()
        else:
            cls.prepared = tempfile.TemporaryDirectory()
            cls.installation = Path(cls.prepared.name)
            url = "https://raw.githubusercontent.com/zurvanproject/zohraya/33c669113f08da032c75d4eaf2f778d515d7669f/deploy/tadash_vps_v01.bundle.b64"
            with urlopen(url, timeout=30) as response:
                raw = response.read(500001)
            if len(raw) > 500000 or hashlib.sha256(raw).hexdigest() != m.PACKAGE:
                raise ValueError("PinnedFixtureMismatch")
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(raw, validate=True))) as archive:
                for name in ["FILES_SHA256.json", "native/reflection_cycle.py", "native/decision_core.py"]:
                    dest = cls.installation / name
                    dest.parent.mkdir(exist_ok=True, parents=True)
                    dest.write_bytes(archive.read(name))
        cls.Engine = m.load_engine(cls.installation)

    @classmethod
    def tearDownClass(cls):
        if cls.prepared:
            cls.prepared.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = fixture_context(self.root / "memory")
        self.lab = self.root / "lab"

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_native_feedback_controls(self):
        result = m.run(self.lab, self.context, self.Engine)
        self.assertEqual(result["observed"], {"baseline": "use_cached", "memory": "recheck_source",
             "unverified": "use_cached", "scope_control": "use_cached", "success_control": "use_cached"})
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["native_body_cycles"], 0)

    def test_cold_native_process_recalls_exact_feedback(self):
        local = self.root / "local"
        memory = local / "Nasuraya/PublicMemoryV1"
        context = fixture_context(memory)
        lab = memory / "ReflectionLabV1" / context["decision_sha256"][:16]
        result = m.run(lab, context, self.Engine)
        installed = local / "NasurayaTadashV1" / ("runtime-" + m.PACKAGE[:16])
        for name in ["FILES_SHA256.json", "native/reflection_cycle.py", "native/decision_core.py"]:
            dest = installed / name; dest.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(self.installation / name, dest)
        process = subprocess.run([sys.executable, "-I", str(JOBS / "moltbook_reflection_report.py")],
            env=dict(os.environ, LOCALAPPDATA=str(local)), capture_output=True, text=True, check=True, timeout=15)
        output = json.loads(process.stdout)["summary"]
        self.assertIn("REFLECT=RECOVERED", output)
        self.assertIn("COLD=1", output)
        self.assertIn("SIG=" + m.digest(result)[:16], output)

    def test_replay_does_not_repeat_native_callback(self):
        result = m.run(self.lab, self.context, self.Engine)
        with self.Engine(self.lab / "memory.sqlite3") as engine:
            before = engine.export()
        self.assertEqual(m.run(self.lab, self.context, self.Engine), result)
        with self.Engine(self.lab / "memory.sqlite3") as engine:
            self.assertEqual(engine.export(), before)

    def test_result_corruption_rejected(self):
        m.run(self.lab, self.context, self.Engine)
        path = self.lab / "result.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["observed"]["memory"] = "use_cached"
        path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ResultIntegrityFailed"):
            m.recover(self.lab, self.context, self.Engine)

    def test_changed_real_context_is_not_silently_reused(self):
        m.run(self.lab, self.context, self.Engine)
        context = dict(self.context, observation_sha256="a" * 64)
        with self.assertRaisesRegex(ValueError, "SavedExerciseMismatch"):
            m.run(self.lab, context, self.Engine)

    def test_wrong_native_source_is_not_imported(self):
        installed = self.root / "wrong"
        (installed / "native").mkdir(parents=True)
        shutil.copyfile(self.installation / "FILES_SHA256.json", installed / "FILES_SHA256.json")
        (installed / "native/decision_core.py").write_text("raise RuntimeError('must not execute')")
        with self.assertRaisesRegex(ValueError, "NativeSourceMismatch"):
            m.load_engine(installed)

    def test_corrupt_public_episode_rejected_before_training(self):
        with closing(sqlite3.connect(self.root / "memory/episodes.sqlite3")) as db, db:
            db.execute("UPDATE episodes SET body='{}'")
        with self.assertRaisesRegex(ValueError, "EpisodeIntegrityFailed"):
            m.source_context(self.root / "memory")


if __name__ == "__main__":
    unittest.main()
