"""End-to-end *synthetic* shell/restic contract tests.

Runs the unmodified shell logic, replacing ONLY two hard-coded source roots
inside a disposable copy. A fake restic command performs local copy/restore;
nothing reaches a network, source VPS, production database or remote provider.
Passing these tests does NOT attest independent offsite recovery.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRILL = ROOT / "tools" / "nasu_offsite_restore_drill.sh"

FAKE_RESTIC = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
action = args[0] if args else ""
log = Path(os.environ["NASU_FAKE_LOG"])
with log.open("a", encoding="utf-8") as f:
    f.write(action + "\n")
repo = Path(os.environ["NASU_FAKE_REPO"])
if action == "snapshots":
    print("[]")
elif action == "backup":
    if os.environ.get("NASU_FAKE_FAIL") == "backup":
        sys.exit(13)
    source = Path(args[-1])
    if not source.is_dir():
        sys.exit(14)
    shutil.copytree(source, repo / "stored")
    (repo / "original-absolute-path").write_text(str(source), encoding="utf-8")
    print(json.dumps({"message_type": "summary", "snapshot_id": "a"*64}))
elif action == "restore":
    if os.environ.get("NASU_FAKE_FAIL") == "restore":
        sys.exit(15)
    if args[1] != "a"*64:
        sys.exit(16)
    target = Path(args[args.index("--target") + 1])
    original = (repo / "original-absolute-path").read_text(encoding="utf-8")
    destination = target / original.lstrip("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo / "stored", destination)
    if os.environ.get("NASU_FAKE_TAMPER") == "1":
        (destination / "awake.sqlite3").write_bytes(b"corrupted after restore")
else:
    sys.exit(17)
"""


class OffsiteRoundTripE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nasu-restic-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "nasuraya"
        self.repo = self.root / "zohraya"
        self.store = self.root / "fake-remote"
        self.store.mkdir()
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "README.md").write_text("synthetic recovery fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit",
                        "-qm", "Synthetic initial commit"], check=True)

        def make_db(filename, marker):
            filename.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(filename) as db:
                db.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
                db.execute("INSERT INTO evidence VALUES (?)", (marker,))

        make_db(self.base / "continuity" / "continuity.sqlite3", "monitor")
        make_db(self.base / "awake-stage" / "awake.sqlite3", "stale")
        # A valid local Qwen growth receipt must survive the independent backup.
        cognitive = self.base / "cognitive-growth" / "cycles.sqlite3"
        cognitive.parent.mkdir(parents=True)
        receipt = {
            "slot": "2026-11-18T06", "stamp": "2026-11-18T06:00:00+00:00",
            "topic": "continuity", "source_path": "tools/continuity.py",
            "source_sha": "a" * 64, "fixed_result": "PASS",
            "model_status": "UNVERIFIED_DRAFT", "proposal": "{}",
            "next_topic": "frontier", "previous_sha": "0" * 64,
        }
        stamp = hashlib.sha256(json.dumps(receipt, sort_keys=True,
                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        with sqlite3.connect(cognitive) as db:
            db.execute("""CREATE TABLE cycles (
                slot TEXT PRIMARY KEY, stamp TEXT, topic TEXT, source_path TEXT,
                source_sha TEXT, fixed_result TEXT, model_status TEXT,
                proposal TEXT, next_topic TEXT, previous_sha TEXT,
                receipt_sha TEXT, state TEXT)""")
            db.execute("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (*receipt.values(), stamp, "completed"))
        self.current = self.base / "migration" / "working" / ("b" * 32) / "awake.sqlite3"
        make_db(self.current, "active")
        (self.base / "migration" / "latest-import.json").write_text(
            json.dumps({"working_db": str(self.current)}), encoding="utf-8")
        archived = self.base / "workloads" / "imports" / "windows"
        archived.mkdir(parents=True)
        (archived / "fixture.txt").write_text("synthetic only\n", encoding="utf-8")

        # Patch the *source locations* in a temporary copy of the production
        # shell script. We do NOT replace or mock its backup/restore logic.
        source = DRILL.read_text(encoding="utf-8")
        self.assertIn("Path('/var/lib/nasuraya')", source)
        self.assertIn("Path('/opt/zohraya')", source)
        source = source.replace("Path('/var/lib/nasuraya')", f"Path({str(self.base)!r})")
        source = source.replace("Path('/opt/zohraya')", f"Path({str(self.repo)!r})")
        self.drill = self.root / "drill.sh"
        self.drill.write_text(source, encoding="utf-8")

        executable = self.root / "fake-bin"
        executable.mkdir()
        fake = executable / "restic"
        fake.write_text(FAKE_RESTIC, encoding="utf-8")
        fake.chmod(0o700)
        self.log = self.root / "restic-calls.txt"
        self.log.touch()
        password = self.root / "fake-password"
        password.write_text("TEST-ONLY, NOT A RESTIC PASSWORD\n", encoding="utf-8")
        password.chmod(0o600)
        self.env = dict(os.environ,
            PATH=str(executable) + os.pathsep + os.environ["PATH"],
            RESTIC_REPOSITORY="sftp:fixture@remote.invalid:/synthetic",
            RESTIC_PASSWORD_FILE=str(password),
            NASU_FAKE_LOG=str(self.log),
            NASU_FAKE_REPO=str(self.store))
        self.password = password

    def run_drill(self, **updates):
        env = self.env.copy()
        env.update(updates)
        return subprocess.run(["bash", str(self.drill)], env=env, text=True,
                              capture_output=True, timeout=40)

    def called(self):
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_whole_shell_round_trip_hash_and_sqlite(self):
        proc = self.run_drill()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("REMOTE_ENCRYPTED_RESTORE=PASS", proc.stdout)
        self.assertIn("SQLITE_INTEGRITY=ok", proc.stdout)
        self.assertEqual(self.called(), ["snapshots", "backup", "restore"])
        snapshot = self.store / "stored"
        manifest = json.loads((snapshot / "manifest.json").read_text())
        self.assertFalse(manifest["model_present"])
        self.assertTrue(manifest["cognitive_journal_present"])
        self.assertFalse(manifest["ollama_qwen3_4b_recoverable"])
        self.assertIn("cognitive-growth.sqlite3", manifest["files_sha256"])
        self.assertTrue(manifest["workload_archives_present"])
        self.assertEqual(manifest["schema"], "nasuraya-restic-offsite/2")
        with sqlite3.connect(snapshot / "awake.sqlite3") as db:
            self.assertEqual(db.execute("SELECT value FROM evidence").fetchone()[0], "active")

    def test_cognitive_chain_tamper_is_detected_even_if_manifest_is_rehashed(self):
        proc = self.run_drill()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        snapshot = self.store / "stored"
        db_path = snapshot / "cognitive-growth.sqlite3"
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE cycles SET model_status='FORGED' WHERE state='completed'")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        manifest = json.loads((snapshot / "manifest.json").read_text())
        manifest["files_sha256"]["cognitive-growth.sqlite3"] = hashlib.sha256(
            db_path.read_bytes()).hexdigest()
        (snapshot / "manifest.json").write_text(json.dumps(manifest))
        verifier = ROOT / "tools" / "nasu_verify_restored_snapshot.py"
        checked = subprocess.run(["python3", str(verifier), str(snapshot)],
                                 capture_output=True, text=True, timeout=15)
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn('"status": "failed"', checked.stderr)

    def test_backup_only_does_not_restore(self):
        proc = self.run_drill(NASU_BACKUP_ONLY="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("RESTORE_SKIPPED", proc.stdout)
        self.assertNotIn("REMOTE_ENCRYPTED_RESTORE=PASS", proc.stdout)
        self.assertEqual(self.called(), ["snapshots", "backup"])

    def test_corruption_on_remote_round_trip_fails_closed(self):
        proc = self.run_drill(NASU_FAKE_TAMPER="1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("REMOTE_ENCRYPTED_RESTORE=PASS", proc.stdout)
        self.assertEqual(self.called(), ["snapshots", "backup", "restore"])

    def test_failed_upload_does_not_claim_backup_or_restore(self):
        proc = self.run_drill(NASU_FAKE_FAIL="backup")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("REMOTE_ENCRYPTED", proc.stdout)
        self.assertEqual(self.called(), ["snapshots", "backup"])

    def test_refuses_local_repository_before_any_work(self):
        proc = self.run_drill(RESTIC_REPOSITORY=str(self.root / "same-host"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Refusing a same-host", proc.stderr)
        self.assertEqual(self.called(), [])

    def test_untrusted_migration_path_fails_before_upload(self):
        (self.base / "migration" / "latest-import.json").write_text(
            json.dumps({"working_db": "/etc/passwd"}), encoding="utf-8")
        proc = self.run_drill()
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.called(), [])

    def test_missing_password_file_fails_before_upload(self):
        self.password.unlink()
        proc = self.run_drill()
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.called(), [])


if __name__ == "__main__":
    unittest.main()
