import base64
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "deploy/tadash_vps_v01.bundle.b64"


class NativeVPSHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "runtime"
        self.install.mkdir()
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(BUNDLE.read_bytes(), validate=True))) as archive:
            archive.extractall(self.install)
        self.state = self.root / "state"

    def call(self, command, *, identity=None, good=True):
        args = [sys.executable, "-I", "-X", "utf8", str(self.install / "driver.py"),
                command, "--state", str(self.state)]
        if identity:
            args += ["--decision-id", identity]
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if good:
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        else:
            self.assertNotEqual(done.returncode, 0, done.stdout)
        return json.loads(done.stdout)

    def test_native_memory_survives_separate_processes(self):
        init = self.call("init")
        one = self.call("step")
        two = self.call("step")
        self.assertEqual(init["completed_cycles"], 0)
        self.assertEqual((one["requested"], one["actual"]), ("walk", "protect"))
        self.assertEqual((two["requested"], two["actual"]), ("observe", "observe"))
        self.assertGreater(two["recalled_feedback"], 0)
        self.assertEqual(two["completed_cycles"], 2)
        self.assertNotEqual(one["checkpoint_sha256"], two["checkpoint_sha256"])
        self.assertEqual(self.call("status")["checkpoint_sha256"], two["checkpoint_sha256"])

    def test_completed_replay_never_repeats_native_effect(self):
        self.call("init")
        one = self.call("step", identity="vps-cycle-1")
        replay = self.call("step", identity="vps-cycle-1")
        self.assertEqual(replay["checkpoint_sha256"], one["checkpoint_sha256"])
        self.assertEqual(replay["native_cycles_in_call"], 0)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["completed_cycles"], 1)

    def test_replay_first_does_not_restore_historical_state(self):
        self.call("init")
        self.call("step")
        two = self.call("step")
        replay = self.call("replay-first")
        self.assertEqual(replay["actual"], "protect")
        self.assertEqual(replay["checkpoint_sha256"], two["checkpoint_sha256"])
        self.assertEqual(replay["revision"], 2)
        self.assertEqual(replay["native_cycles_in_call"], 0)

    def test_initialize_never_resets_existing_body(self):
        self.call("init")
        first = self.call("step")
        again = self.call("init")
        self.assertEqual(again["checkpoint_sha256"], first["checkpoint_sha256"])
        self.assertEqual(again["completed_cycles"], 1)

    def test_foreign_ledger_is_refused_without_mutation(self):
        self.state.mkdir()
        db = self.state / "session.sqlite"
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("CREATE TABLE foreign_data (value TEXT)")
            connection.execute("INSERT INTO foreign_data VALUES ('untouched')")
            connection.commit()
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        self.call("init", good=False)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

    def test_unresolved_operation_blocks_new_work(self):
        self.call("init")
        one = self.call("step")
        with closing(sqlite3.connect(self.state / "session.sqlite")) as db:
            record = json.loads(db.execute("SELECT record FROM decisions WHERE id='vps-cycle-1'").fetchone()[0])
            record["status"] = "running"
            db.execute("UPDATE decisions SET status='running',record=? WHERE id='vps-cycle-1'", (json.dumps(record),))
            db.commit()
        self.call("step", good=False)
        after = self.call("status")
        self.assertEqual(after["revision"], one["revision"])
        self.assertEqual(after["unresolved"], 1)

    def test_source_tampering_is_refused_before_native_init(self):
        source = self.install / "native/decision_core.py"
        source.write_bytes(source.read_bytes() + b"\n# changed")
        self.call("init", good=False)
        self.assertFalse((self.state / "session.sqlite").exists())

    def test_action_budget_persists_after_restart(self):
        self.call("init")
        for _ in range(20):
            latest = self.call("step")
        self.assertEqual(latest["completed_cycles"], 20)
        self.call("step", good=False)
        replay = self.call("replay-first")
        self.assertEqual(replay["completed_cycles"], 20)
        self.assertEqual(replay["native_cycles_in_call"], 0)

    def test_sqlite_host_mutex_and_process_death_release(self):
        self.call("init")
        ready = self.root / "ready"
        code = ("import sqlite3,sys,pathlib; "
                "db=sqlite3.connect(sys.argv[1],isolation_level=None); "
                "db.execute('BEGIN EXCLUSIVE');pathlib.Path(sys.argv[2]).write_text('ready');"
                "sys.stdin.readline()")
        process = subprocess.Popen([sys.executable, "-c", code, str(self.state / "host.lock.sqlite"),
                                    str(ready)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if ready.exists():
                    break
                time.sleep(.05)
            self.assertTrue(ready.exists())
            self.call("step", good=False)
            process.terminate()
            process.wait(timeout=5)
            self.assertEqual(self.call("status")["completed_cycles"], 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.communicate(timeout=5)

    def test_exact_native_source_manifest_preserved(self):
        native = self.install / "native"
        raw = (native / "PUBLIC_FILES_SHA256.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "b3b95a88885d903f638efbc26ed693bf7a211460a5adae6dd9abfa12ac7720ef")
        manifest = json.loads(raw)
        self.assertEqual(len(manifest), 70)
        for name, expected in manifest.items():
            self.assertEqual(hashlib.sha256((native / name).read_bytes()).hexdigest(), expected)

    @unittest.skipUnless(os.name == "nt", "native Windows locking adapter")
    def test_windows_flock_rejects_competing_process(self):
        lock = self.root / "native.lock"
        lock.write_bytes(b"x")
        code = ("import importlib.util,sys,os;"
                "s=importlib.util.spec_from_file_location('w',sys.argv[1]);"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                "f=open(sys.argv[2],'r+b');m.flock(f,m.LOCK_EX|m.LOCK_NB)")
        spec = importlib.util.spec_from_file_location("winlock", self.install / "windows_fcntl.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with lock.open("r+b") as stream:
            module.flock(stream, module.LOCK_EX | module.LOCK_NB)
            failed = subprocess.run([sys.executable, "-c", code, str(self.install / "windows_fcntl.py"), str(lock)],
                                    capture_output=True, timeout=5)
            self.assertNotEqual(failed.returncode, 0)
            module.flock(stream, module.LOCK_UN)
        passed = subprocess.run([sys.executable, "-c", code, str(self.install / "windows_fcntl.py"), str(lock)],
                                capture_output=True, timeout=5)
        self.assertEqual(passed.returncode, 0, passed.stderr)


if __name__ == "__main__":
    unittest.main()

