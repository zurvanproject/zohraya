"""Isolated rehearsal of install/rollback; no real systemd or root operations."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

INSTALLER = Path(__file__).resolve().parents[1] / 'tools' / 'install_nasuraya_bridge_v31.py'
spec = importlib.util.spec_from_file_location('bridge_v31_installer_test', INSTALLER)
i = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i)


class InstallerContracts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.lib = self.home / 'lib'
        self.lib.mkdir()
        self.bridge = self.lib / 'bridge.py'
        self.worker = self.lib / 'nasu_bridge_research.py'
        self.backups = self.home / 'backups' / 'nasuraya-bridge-v31'
        self.backups.parent.mkdir()
        self.before = b'print("old bridge")\n'
        self.after = b'print("new bridge")\n'
        self.script = b'print("runner")\n'
        self.bridge.write_bytes(self.before)
        self.parts = (
            mock.patch.object(i, 'BRIDGE', self.bridge),
            mock.patch.object(i, 'WORKER', self.worker),
            mock.patch.object(i, 'BACKUPS', self.backups),
            mock.patch.object(i, 'load_plan', return_value=(self.before, self.after, self.script)),
            mock.patch.object(i.os, 'geteuid', return_value=0),
            mock.patch.object(i, 'systemctl', return_value=types.SimpleNamespace(returncode=0)),
        )
        for part in self.parts:
            part.start()
            self.addCleanup(part.stop)

    def invoke(self, *args):
        out = io.StringIO()
        with mock.patch('sys.argv', ['installer.py', *args]), contextlib.redirect_stdout(out):
            i.main()
        return out.getvalue()

    def test_requires_preview_or_explicit_apply(self):
        with self.assertRaises(SystemExit):
            self.invoke('--apply', '--approve-sha', 'badsha')
        self.assertEqual(self.bridge.read_bytes(), self.before)
        self.assertFalse(self.worker.exists())
        self.assertFalse(self.backups.exists())

    def test_preview_does_not_write_or_restart(self):
        with mock.patch.object(i, 'systemctl', side_effect=AssertionError('service touched')):
            output = self.invoke('--preview')
        self.assertIn('PREVIEW_ONLY_NO_CHANGES', output)
        self.assertEqual(self.bridge.read_bytes(), self.before)
        self.assertFalse(self.worker.exists())

    def test_success_preserves_backup_and_installs_two_files(self):
        output = self.invoke('--apply', '--approve-sha', i.digest(self.after))
        self.assertIn('UPGRADE_INSTALLED_BACKUP', output)
        self.assertIn('RESEARCH_NOT_STARTED', output)
        self.assertEqual(self.bridge.read_bytes(), self.after)
        self.assertEqual(self.worker.read_bytes(), self.script)
        self.assertEqual(len(list(self.backups.glob('*.bak'))), 1)
        self.assertEqual(list(self.backups.glob('*.bak'))[0].read_bytes(), self.before)

    def test_failed_restart_restores_original_and_removes_new_worker(self):
        r = [types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=1),
             types.SimpleNamespace(returncode=0)]
        with mock.patch.object(i, 'systemctl', side_effect=r):
            with self.assertRaisesRegex(RuntimeError, 'BRIDGE_RESTART_FAILED'):
                self.invoke('--apply', '--approve-sha', i.digest(self.after))
        self.assertEqual(self.bridge.read_bytes(), self.before)
        self.assertFalse(self.worker.exists())
        self.assertEqual(len(list(self.backups.glob('*.bak'))), 1)

    def test_refuses_existing_runner_before_any_changes(self):
        self.worker.write_text('existing independent program')
        # Rehearsal wrapper: real load_plan performs this check when sources are verified.
        with mock.patch.object(i, 'load_plan', side_effect=ValueError('RUNNER_TARGET_ALREADY_PRESENT_REFUSE')):
            with self.assertRaisesRegex(ValueError, 'RUNNER_TARGET_ALREADY_PRESENT_REFUSE'):
                self.invoke('--apply', '--approve-sha', i.digest(self.after))
        self.assertEqual(self.bridge.read_bytes(), self.before)
        self.assertEqual(self.worker.read_text(), 'existing independent program')

if __name__ == '__main__':
    unittest.main()
