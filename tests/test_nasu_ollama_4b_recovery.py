"""Synthetic-only Qwen3 4B/Ollama recovery tests; no downloading or VPS access."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "nasu_ollama_4b_recovery.py"
SPEC = importlib.util.spec_from_file_location("nasu_ollama_4b_recovery", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SyntheticOllamaRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.models = self.root / "models"
        self.stage = self.root / "snapshot"
        self.libs = self.root / "lib" / "ollama"
        self.binary = self.root / "ollama"
        self.models.mkdir()
        self.stage.mkdir()
        self.libs.mkdir(parents=True)
        self.binary.write_bytes(b"#!/bin/sh\necho 'ollama version is 0.99.0-fixture'\n")
        self.binary.chmod(0o755)
        (self.libs / "libcpu.so").write_bytes(b"synthetic library, never execute")
        self.config = b'{"arch":"qwen3-synthetic"}'
        self.layer = b"NOT A REAL MODEL: synthetic bytes for fixture"
        self.manifest = {
            "schemaVersion": 2,
            "config": {"digest": "sha256:" + sha(self.config), "size": len(self.config)},
            "layers": [{"digest": "sha256:" + sha(self.layer), "size": len(self.layer)}],
        }
        self.tag = self.models / mod.TAG_REL
        self.tag.parent.mkdir(parents=True)
        self.tag.write_text(json.dumps(self.manifest))
        blobdir = self.models / "blobs"
        blobdir.mkdir()
        (blobdir / ("sha256-" + sha(self.config))).write_bytes(self.config)
        (blobdir / ("sha256-" + sha(self.layer))).write_bytes(self.layer)

    def stage_assets(self):
        return mod.stage(self.stage, self.models, self.binary, self.libs)

    def test_snapshot_is_complete_and_verifiable(self):
        stats = self.stage_assets()
        self.assertEqual(stats["model_blobs"], 2)
        self.assertEqual(set(stats["artifact_names"]), set(mod.ARTIFACTS))
        verified = mod.verify_bundle(self.stage)
        self.assertEqual(verified["status"], "ollama_4b_assets_verified")
        self.assertFalse(verified["offline_inference_pass"])
        with tarfile.open(self.stage / mod.MODEL_ARCHIVE) as t:
            self.assertIn("models/" + mod.TAG_REL, t.getnames())
            self.assertEqual(len(t.getmembers()), 3)

    def test_missing_model_file_fails_without_pass(self):
        (self.models / "blobs" / ("sha256-" + sha(self.layer))).unlink()
        with self.assertRaises(ValueError):
            self.stage_assets()
        self.assertFalse((self.stage / mod.INFO_FILE).exists())

    def test_corrupt_archive_detected(self):
        self.stage_assets()
        with (self.stage / mod.MODEL_ARCHIVE).open("ab") as f:
            f.write(b"corrupt archive suffix")
        with self.assertRaises(ValueError):
            mod.verify_bundle(self.stage)

    def test_tampered_archive_hash_detected(self):
        self.stage_assets()
        info = json.loads((self.stage / mod.INFO_FILE).read_text())
        info["archives_sha256"][mod.MODEL_ARCHIVE] = "0" * 64
        (self.stage / mod.INFO_FILE).write_text(json.dumps(info))
        with self.assertRaises(ValueError):
            mod.verify_bundle(self.stage)

    def test_wrong_blob_digest_rejected_even_if_archive_is_rehashed(self):
        self.stage_assets()
        original = self.stage / mod.MODEL_ARCHIVE
        info_file = self.stage / mod.INFO_FILE
        meta = json.loads(info_file.read_text())
        with tarfile.open(original, "r:gz") as tar:
            data = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}
        blob_name = "models/blobs/sha256-" + sha(self.layer)
        data[blob_name] = b"tampered fixture with rehashed tar"
        with tarfile.open(original, "w:gz") as tar:
            for name, content in data.items():
                m = tarfile.TarInfo(name)
                m.size = len(content)
                tar.addfile(m, io.BytesIO(content))
        meta["archives_sha256"][mod.MODEL_ARCHIVE] = mod.digest(original)
        info_file.write_text(json.dumps(meta))
        with self.assertRaises(ValueError):
            mod.verify_bundle(self.stage)

    def test_incomplete_runtime_fails(self):
        (self.libs / "libcpu.so").unlink()
        with self.assertRaises(ValueError):
            self.stage_assets()

    def test_symlinked_model_rejected(self):
        file = self.models / "blobs" / ("sha256-" + sha(self.layer))
        file.unlink()
        file.symlink_to("/etc/hosts")
        with self.assertRaises(ValueError):
            self.stage_assets()

    def test_archive_path_traversal_rejected_even_if_outer_hash_updated(self):
        self.stage_assets()
        target = self.stage / mod.RUNTIME_ARCHIVE
        with tarfile.open(target, "w:gz") as tar:
            data = b"malicious fixture"
            m = tarfile.TarInfo("../../escape")
            m.size = len(data)
            tar.addfile(m, io.BytesIO(data))
        meta_file = self.stage / mod.INFO_FILE
        meta = json.loads(meta_file.read_text())
        meta["archives_sha256"][mod.RUNTIME_ARCHIVE] = mod.digest(target)
        meta_file.write_text(json.dumps(meta))
        with self.assertRaises(ValueError):
            mod.verify_bundle(self.stage)
        self.assertFalse((self.root / "escape").exists())

    def test_runtime_symlink_outside_source_is_rejected(self):
        (self.libs / "unsafe.so").symlink_to("/etc/hosts")
        with self.assertRaises(ValueError):
            self.stage_assets()

    def test_startup_failure_cannot_claim_offline_smoke_pass(self):
        self.stage_assets()
        fail = subprocess.CompletedProcess([], 2, "", "synthetic startup failure")
        with mock.patch.object(mod.shutil, "which", side_effect=lambda n: "/usr/bin/" + n):
            with self.assertRaises(RuntimeError):
                mod.smoke(self.stage, runner=lambda *a, **kw: fail, isolator="unshare")

    def test_synthetic_success_is_not_independent_attestation(self):
        self.stage_assets()
        ok = subprocess.CompletedProcess([], 0, json.dumps({
            "status": "offline_model_recovery_smoke_pass", "model": mod.TAG,
            "model_process_network": "isolated_linux_namespace", "output_sha256": "e" * 64,
        }), "")
        with mock.patch.object(mod.shutil, "which", side_effect=lambda n: "/usr/bin/" + n):
            got = mod.smoke(self.stage, runner=lambda *a, **kw: ok, isolator="unshare")
        self.assertEqual(got["independent_host"], "operator_attestation_required")
        # A mocked runner is never a physical-host smoke receipt.


if __name__ == "__main__":
    unittest.main()
