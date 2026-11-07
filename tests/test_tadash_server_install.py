"""Pinned deployment package boundaries; no network or scheduled task changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("server_installer",ROOT/"tools/bridge_jobs/worker_install.py")
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_exact_package_and_manifest_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            installer.unpack((ROOT/"deploy/tadash_server_v01.bundle.b64").read_bytes(),root)
            self.assertEqual({p.name for p in root.iterdir()},installer.NAMES)
            self.assertEqual(installer.verify(root),root)
            (root/"worker.py").write_text("changed")
            with self.assertRaises(ValueError):installer.verify(root)

    def test_changed_transport_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            payload=(ROOT/"deploy/tadash_server_v01.bundle.b64").read_bytes()
            with self.assertRaises(ValueError):installer.unpack(payload+b"x",root)
            self.assertFalse(list(root.iterdir()))

if __name__=="__main__":unittest.main()
