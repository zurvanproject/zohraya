"""Offline-readiness preflight only. Uses synthetic data; never runs a production job."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "tools" / "nasu_offsite_restore_drill.sh"
MODEL = ROOT / "tools" / "nasu_install_local_llm.sh"
EXPECTED = "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"


def extracted_python():
    text = BACKUP.read_text()
    blocks = re.findall(r"(?ms)^python3 - <<'PY'\n(.*?)\nPY$", text)
    if len(blocks) != 2:
        raise AssertionError("Expected snapshot and restore Python blocks")
    for b in blocks:
        compile(b, "embedded-python", "exec")
    return blocks


class OfflineReadinessTests(unittest.TestCase):
    def test_shell_syntax_and_model_sha(self):
        for script in (BACKUP, MODEL, ROOT / "tools" / "install_nasu_offsite_backup_timer.sh"):
            subprocess.run(["bash", "-n", str(script)], check=True)
        install = MODEL.read_text()
        self.assertIn(EXPECTED, install)
        self.assertIn("sha256sum -c -", install)
        self.assertIn("--single-turn", install)
        self.assertIn("Qwen/Qwen3-1.7B-GGUF", install)

    def test_synthetic_migrated_sqlite_git_workloads_and_tamper(self):
        snapshot, verify = extracted_python()
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            home = temp / "nasuraya"
            stage = temp / "stage"
            stage.mkdir()
            source_repo = temp / "zohraya"
            source_repo.mkdir()
            subprocess.run(["git", "init", "-q", str(source_repo)], check=True)
            (source_repo / "README.md").write_text("offline research fixture\n")
            subprocess.run(["git", "-C", str(source_repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source_repo),
                            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-qm", "Synthetic fixture"], check=True)

            def db(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(path) as cx:
                    cx.execute("CREATE TABLE evidence(value TEXT)")
                    cx.execute("INSERT INTO evidence VALUES (?)", (value,))
            db(home / "continuity" / "continuity.sqlite3", "synthetic-monitor")
            db(home / "awake-stage" / "awake.sqlite3", "stale")
            db(home / "local-research" / "research.sqlite3", "synthetic research")
            current = home / "migration" / "working" / ("a"*32) / "awake.sqlite3"
            db(current, "current")
            (home / "migration" / "latest-import.json").write_text(
                json.dumps({"working_db": str(current)}))
            archived = home / "workloads" / "imports" / "memory"
            archived.mkdir(parents=True)
            (archived / "synthetic.txt").write_text("synthetic history\n")

            snapshot = snapshot.replace("Path('/var/lib/nasuraya')", f"Path({str(home)!r})")
            snapshot = snapshot.replace("Path('/opt/zohraya')", f"Path({str(source_repo)!r})")
            env = dict(os.environ, STAGE=str(stage), RESTORED=str(stage))
            run = subprocess.run(["python3", "-c", snapshot], env=env,
                                 text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            manifest = json.loads((stage / "manifest.json").read_text())
            self.assertEqual(manifest["schema"], "nasuraya-restic-offsite/2")
            self.assertFalse(manifest["model_present"])
            self.assertTrue(manifest["workload_archives_present"])
            self.assertTrue(manifest["research_journal_present"])
            self.assertIn("research.sqlite3", manifest["files_sha256"])
            self.assertIn("zohraya.bundle", manifest["files_sha256"])
            with tarfile.open(stage / "workload-imports.tar.gz") as tar:
                self.assertIn("imports/memory/synthetic.txt", tar.getnames())
            with sqlite3.connect(stage / "awake.sqlite3") as cx:
                self.assertEqual(cx.execute("SELECT value FROM evidence").fetchone()[0],
                                 "current")
            good = subprocess.run(["python3", "-c", verify], env=env,
                                  text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn("REMOTE_ENCRYPTED_RESTORE=PASS", good.stdout)
            verifier_path=ROOT / "tools" / "nasu_verify_restored_snapshot.py"
            spec=importlib.util.spec_from_file_location("nasu_fresh_verify",verifier_path)
            verifier=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(verifier)
            self.assertEqual(verifier.verify(stage)["status"],"verified")

            with open(stage / "awake.sqlite3", "ab") as fh:
                fh.write(b"tamper")
            bad = subprocess.run(["python3", "-c", verify], env=env,
                                 text=True, capture_output=True)
            self.assertNotEqual(bad.returncode, 0, "Tampering must fail closed")
            with self.assertRaises(ValueError):
                verifier.verify(stage)


if __name__ == "__main__":
    unittest.main()
