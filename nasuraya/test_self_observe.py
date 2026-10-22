"""Exercise the projection on real native checkpoints, without an extra action."""
from copy import deepcopy
import fcntl
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from .catalog import ROOT
from .demo import call
from .self_observe import observe_checkpoint, observe_session, _session_checkpoint


class NativeSelfObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.session = Path(cls.temporary.name)/'session'
        call('dialogue', 'init', '--session-dir', cls.session, '--max-actions', '1')
        cls.path = cls.session/'body.sqlite'
        with sqlite3.connect(cls.path.as_uri()+'?mode=ro', uri=True) as db:
            cls.checkpoint = _session_checkpoint(db)

    def test_actual_audit_and_projection_preserve_saved_body(self):
        original = deepcopy(self.checkpoint)
        report = observe_checkpoint(self.checkpoint)
        self.assertEqual(self.checkpoint, original)
        self.assertEqual(report['checkpoint_sha256'], original['sha256'])
        self.assertEqual(report['audit']['body_revision'], original['payload']['revision'])
        self.assertEqual(report['telemetry']['cycle_count'], report['audit']['body_revision'])
        self.assertEqual(report['telemetry']['integrity'], None)
        self.assertIn('physical_sensor_attachment', report['telemetry']['unknown'])
        self.assertTrue(report['native_checkpoint_unchanged'])
        self.assertEqual(report['simulated_cycles_executed'], 0)

    def test_expired_native_checkpoint_remains_stale_and_unknown(self):
        saved_time = observe_checkpoint(self.checkpoint)['audit']['body_time_s']
        report = observe_checkpoint(self.checkpoint, at_simulated_s=saved_time+6)
        self.assertEqual(report['telemetry']['operational_status'], 'STALE_EVIDENCE')
        self.assertFalse(report['telemetry']['optional_motion_permitted'])
        self.assertIn('current_body_state', report['telemetry']['unknown'])
        self.assertEqual(report['audit']['body_time_s'], saved_time)

    def test_nonfinite_and_backward_clocks_are_rejected(self):
        for clock in (float('nan'), float('inf'), True, -1):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                observe_checkpoint(self.checkpoint, at_simulated_s=clock)

    def test_corrupt_checkpoint_is_rejected(self):
        checkpoint = deepcopy(self.checkpoint)
        checkpoint['payload']['revision'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            observe_checkpoint(checkpoint)

    def test_existing_ledger_readout_leaves_file_and_schema_unchanged(self):
        before = self.path.read_bytes()
        report = observe_session(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(report['source_access'], 'existing_body_loop_sqlite_read_only')
        self.assertEqual(report['checkpoint_sha256'], self.checkpoint['sha256'])
        self.assertEqual(report['external_api_calls'], 0)

    def test_missing_session_and_active_writer_are_rejected(self):
        missing = self.session/'missing.sqlite'
        with self.assertRaises(FileNotFoundError):
            observe_session(missing)
        self.assertFalse(missing.exists())
        with self.path.open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                observe_session(self.path)

    def test_unresolved_execution_does_not_report_saved_body_as_current(self):
        path = self.session/'unresolved.sqlite'
        shutil.copyfile(self.path, path)
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?)',
                       ('unresolved', 1, 'synthetic', 'test', 'test', 'running', '{}'))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unresolved native execution'):
            observe_session(path)
        self.assertEqual(path.read_bytes(), before)

    def test_hardlink_and_symlink_aliases_are_rejected(self):
        hardlink = self.session/'hardlink.sqlite'
        symlink = self.session/'symlink.sqlite'
        os.link(self.path, hardlink)
        try:
            with self.assertRaisesRegex(ValueError, 'without hard links'):
                observe_session(hardlink)
            with self.assertRaisesRegex(ValueError, 'without hard links'):
                observe_session(self.path)
        finally:
            hardlink.unlink()
        symlink.symlink_to(self.path)
        with self.assertRaises(OSError):
            observe_session(symlink)

    def test_cli_rejects_invalid_checkpoint_without_creating_state(self):
        path = self.session/'invalid.json'
        path.write_text('{}\n')
        result = subprocess.run([sys.executable, '-m', 'nasuraya.self_observe',
                                 '--checkpoint', str(path)], cwd=ROOT,
                                 capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_text(), '{}\n')


if __name__ == '__main__':
    unittest.main()
