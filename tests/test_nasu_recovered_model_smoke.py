"""Synthetic, never-executed recovery-model tests; no model download."""
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

MOD_PATH = Path(__file__).resolve().parents[1] / "tools" / "nasu_recovered_model_smoke.py"
SPEC = importlib.util.spec_from_file_location("nasu_recovered_model_smoke", MOD_PATH)
import sys
sys.path.insert(0, str(MOD_PATH.parent))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class RecoveryModelTests(unittest.TestCase):
    def fixture(self, folder, unsafe=False):
        root = Path(folder)
        (root / mod.MODEL_NAME).write_bytes(b"synthetic model only")
        with tarfile.open(root / "llama-runtime.tar.gz", "w:gz") as t:
            data = b"#!/bin/sh\necho synthetic\n"
            info = tarfile.TarInfo("../escape" if unsafe else "llama-bin/llama-cli")
            info.mode = 0o755
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        return root

    def test_offline_namespace_is_mandatory(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.fixture(td)
            def fake_runner(command, **kwargs):
                self.assertEqual(command[:4], ["/usr/bin/unshare", "--net", "--fork", "--"])
                self.assertTrue(kwargs["env"]["LD_LIBRARY_PATH"].endswith("llama-bin"))
                return subprocess.CompletedProcess(command, 0, "Recovered output is synthetic.\n", "")
            with mock.patch.object(mod, "verify", return_value={"model_present": True, "file_count": 6}):
                result = mod.exercise(root, runner=fake_runner, isolator="/usr/bin/unshare")
            self.assertEqual(result["status"], "offline_model_recovery_smoke_pass")
            self.assertEqual(result["independent_machine"], "operator_attestation_required")

    def test_missing_model_fails_closed(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            mod, "verify", return_value={"model_present": False}
        ):
            with self.assertRaises(ValueError):
                mod.exercise(td, isolator="/usr/bin/unshare")

    def test_archive_traversal_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.fixture(td, unsafe=True)
            with mock.patch.object(mod, "verify", return_value={"model_present": True, "file_count": 5}):
                with self.assertRaises(ValueError):
                    mod.exercise(root, runner=lambda *a, **k: self.fail("Must not execute"),
                                 isolator="/usr/bin/unshare")

    def test_failed_inference_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.fixture(td)
            with mock.patch.object(mod, "verify", return_value={"model_present": True, "file_count": 5}):
                with self.assertRaises(RuntimeError):
                    mod.exercise(root, runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""),
                                 isolator="/usr/bin/unshare")


if __name__ == "__main__":
    unittest.main()
