"""Offline contract tests for rootless, bounded, daily mission scheduler."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools/nasu_offline_missions.py'
sp = importlib.util.spec_from_file_location('nasu_offline_missions', MODULE_PATH)
m = importlib.util.module_from_spec(sp)
sp.loader.exec_module(m)


class Missions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.lab = self.home / 'autonomous-lab'

    def test_host_telemetry_is_bounded_scalar(self):
        p = m.telemetry(self.home)
        self.assertGreater(p['mem_total_kib'], 0)
        self.assertGreater(p['disk_available_bytes'], 0)

    def test_missing_journal_backup_no_unwanted_creation(self):
        self.lab.mkdir()
        result = m.backup_journal(self.home, self.lab)
        self.assertEqual(result['status'], 'journal_missing')
        self.assertFalse((self.lab / 'local-brain-backups').exists())

    def test_sqlite_backup_integrity_and_repeat(self):
        p = self.home / 'local-brain'
        p.mkdir()
        source = p / 'journal.sqlite3'
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE reports (id INTEGER)')
            db.execute('INSERT INTO reports VALUES (3)')
        self.lab.mkdir()
        result = m.backup_journal(self.home, self.lab)
        self.assertEqual(result['status'], 'created')
        repeat = m.backup_journal(self.home, self.lab)
        self.assertEqual(repeat['status'], 'existing')
        self.assertEqual(result['sha256'], repeat['sha256'])
        item = next((self.lab / 'local-brain-backups').glob('*.sqlite3'))
        with sqlite3.connect(item) as db:
            self.assertEqual(db.execute('SELECT * FROM reports').fetchone(), (3,))

    def test_unknown_checkout_is_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, 'Verified existing'):
            m.source_checkout(self.home)

    def test_practice_uses_3_passes_and_carries_previous_checkpoint(self):
        repo = self.home / 'repo'
        repo.mkdir()
        parent = self.home / 'parent.json'
        parent.write_text('{}')
        responses = []
        def fake(argv, *, cwd, timeout=240):
            responses.append(argv)
            if 'practice' in argv:
                target = Path(argv[argv.index('--output-dir') + 1])
                target.mkdir()
                (target / 'checkpoint.json').write_text('{"total_updates":2912}')
                (target / 'practice.wav').write_bytes(b'audio')
                return {'episodes': 3, 'inherited_updates': 2878,
                        'new_updates': 34, 'total_updates': 2912,
                        'scheduled_music_seconds': 30, 'note_events': 34,
                        'checkpoint_sha256': m.digest(target / 'checkpoint.json'),
                        'audio': {'sha256': m.digest(target / 'practice.wav')}}
            return {'status': {'total_updates': 2878}, 'summary': {'pitch': 2.5}}
        with patch.object(m, 'source_checkout', return_value=(repo, Path('/python'), 'a'*40)), \
             patch.object(m, 'get_parent', return_value=parent), \
             patch.object(m, 'call_checked', fake), \
             patch.object(m.subprocess, 'run', return_value=type('Result', (), {'returncode': 0})()):
            self.lab.mkdir()
            folder = self.lab / '2026-11-15'
            folder.mkdir()
            result = m.practice(None, folder, day='2026-11-15', home=self.home)
        self.assertEqual(result['total_updates'], 2912)
        self.assertEqual(result['synthetic_seconds'], 30)
        self.assertEqual(result['source_regression'], 'passed')
        self.assertEqual(len(responses), 3)
        self.assertIn('--accelerated', responses[1])
        self.assertEqual(responses[1][responses[1].index('--checkpoint') + 1], str(parent))

    def fake_practice(self):
        return {'status': 'completed', 'total_updates': 2912,
                'note_events': 54, 'synthetic_seconds': 30}

    def test_success_reserves_and_does_not_repeat(self):
        with patch.object(m.os, 'geteuid', return_value=1001), \
             patch.object(m, 'telemetry', return_value={'load_1min': 0.1}), \
             patch.object(m, 'read_existing', return_value={'awake': {}, 'focus': {}}), \
             patch.object(m, 'backup_journal', return_value={'status': 'created'}), \
             patch.object(m, 'practice', return_value=self.fake_practice()) as exercise, \
             patch.object(m, 'qwen_reflect', return_value='مشاهده: گزارش ثبت شد'):
            first = m.run(home=self.home, state=self.lab, date='2026-11-15')
            second = m.run(home=self.home, state=self.lab, date='2026-11-15')
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(second['status'], 'already_reserved')
        exercise.assert_called_once()
        self.assertEqual(m.status(self.lab)['day_count'], 1)
        self.assertTrue((self.lab / '2026-11-15/result.json').is_file())

    def test_practice_failure_stops_but_no_replay(self):
        with patch.object(m.os, 'geteuid', return_value=1001), \
             patch.object(m, 'telemetry', return_value={}), \
             patch.object(m, 'read_existing', return_value={'awake': {}, 'focus': {}}), \
             patch.object(m, 'backup_journal', return_value={'status': 'missing'}), \
             patch.object(m, 'practice', side_effect=RuntimeError('no verified source')) as exercise:
            first = m.run(home=self.home, state=self.lab, date='2026-11-15')
            second = m.run(home=self.home, state=self.lab, date='2026-11-15')
        self.assertEqual(first['status'], 'failed')
        self.assertEqual(second['status'], 'already_reserved')
        exercise.assert_called_once()
        self.assertEqual(m.status(self.lab)['recent'][0]['state'], 'failed')

    def test_qwen_failure_keeps_completed_practice_for_next_day(self):
        with patch.object(m.os, 'geteuid', return_value=1001), \
             patch.object(m, 'telemetry', return_value={}), \
             patch.object(m, 'read_existing', return_value={'awake': {}, 'focus': {}}), \
             patch.object(m, 'backup_journal', return_value={'status': 'missing'}), \
             patch.object(m, 'practice', return_value=self.fake_practice()), \
             patch.object(m, 'qwen_reflect', side_effect=TimeoutError()):
            first = m.run(home=self.home, state=self.lab, date='2026-11-15')
        self.assertEqual(first['status'], 'completed_without_qwen')
        self.assertEqual(m.status(self.lab)['recent'][0]['total_updates'], 2912)
        item = json.loads((self.lab / '2026-11-15/result.json').read_text())
        self.assertEqual(item['reflection']['error_class'], 'TimeoutError')

    def test_missions_refuse_root(self):
        with patch.object(m.os, 'geteuid', return_value=0):
            with self.assertRaises(PermissionError):
                m.run(home=self.home, state=self.lab, date='2026-11-15')
        self.assertFalse(self.lab.exists())


if __name__ == '__main__':
    unittest.main()
