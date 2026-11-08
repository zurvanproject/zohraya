from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_moltbook_native_feedback as n
import test_moltbook_memory_decisions as p

spec = importlib.util.spec_from_file_location("recovery_job", n.JOBS / "moltbook_recovery_run.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = n.native_fixture()
        cls.Engine = n.m.load_engine(cls.installation)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name)
        self.memory = self.local / "Nasuraya/PublicMemoryV1"
        p.c.capture(self.memory, p.page([p.comment()]))
        p.m.compare(self.memory, p.page([p.comment()]))
        self.context = n.m.source_context(self.memory)
        self.root = self.memory / "RecoveryLabV1" / self.context["decision_sha256"][:16]

    def tearDown(self):
        self.tmp.cleanup()

    def run_experiment(self, fetch=None):
        return m.run(self.root, self.memory, self.context, n.m, p.m, self.Engine,
                     fetch if fetch is not None else p.page([p.comment()]))

    def test_actual_checksum_failure_changes_next_operation(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return p.page([p.comment()])(url)
        result = self.run_experiment(fetch)
        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 1)
        self.assertEqual([r["actual"]["status"] for r in result["rows"]["baseline"]],
                         ["executor_failed", "executor_failed"])
        self.assertEqual([r["actual"]["status"] for r in result["rows"]["memory"]],
                         ["executor_failed", "ready"])

    def test_network_failure_cannot_claim_recovery(self):
        def fail(url):
            raise TimeoutError()
        result = self.run_experiment(fail)
        self.assertFalse(result["success"])
        self.assertIn("RECOVERY=NOT_RECOVERED", m.summary(result))
        self.assertEqual(result["rows"]["memory"][1]["actual"]["error_type"], "TimeoutError")

    def test_partial_fresh_tree_cannot_claim_recovery(self):
        item = p.comment(); item.pop("reply_count")
        self.assertFalse(self.run_experiment(p.page([item]))["success"])

    def test_original_and_anchor_preserved_and_replay_does_not_fetch(self):
        anchor = (self.memory / "anchor.json").read_bytes()
        first = self.run_experiment()
        def must_not_fetch(url):
            raise AssertionError("Completed operation must not repeat")
        self.assertEqual(self.run_experiment(must_not_fetch), first)
        self.assertEqual((self.memory / "anchor.json").read_bytes(), anchor)
        self.assertEqual(n.m.source_context(self.memory), self.context)

    def test_corrupt_refetched_artifact_is_rejected(self):
        self.run_experiment()
        (self.root / "refetched.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "ReceiptIntegrityFailed"):
            m.inspect(self.root, self.memory, self.context, n.m, p.m, self.Engine)

    def test_cold_process_checks_actual_native_receipts(self):
        result = self.run_experiment()
        install = self.local / "NasurayaTadashV1" / ("runtime-" + n.m.PACKAGE[:16])
        for name in ["FILES_SHA256.json", "native/reflection_cycle.py", "native/decision_core.py"]:
            dest = install / name; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.installation / name, dest)
        deps = self.memory / "RecoveryLabV1/dependencies"
        deps.mkdir(parents=True)
        for name in m.DEPENDENCIES:
            shutil.copyfile(n.JOBS / (name + ".py"), deps / (name + ".py"))
        process = subprocess.run([sys.executable, "-I", str(n.JOBS / "moltbook_recovery_report.py")],
            env=dict(os.environ, LOCALAPPDATA=str(self.local)), capture_output=True, text=True, check=True, timeout=15)
        output = json.loads(process.stdout)["summary"]
        self.assertIn("RECOVERY=RECOVERED", output)
        self.assertIn("COLD=1", output)
        self.assertIn("SIG=" + m.digest(result)[:16], output)

    def test_changed_dependency_is_not_executed(self):
        deps = self.local / "bad-deps"; deps.mkdir()
        (deps / "moltbook_reflection_train.py").write_text("raise AssertionError('must not execute')")
        with self.assertRaisesRegex(ValueError, "DependencyFingerprintMismatch"):
            m.dependencies(deps)


if __name__ == "__main__":
    unittest.main()
