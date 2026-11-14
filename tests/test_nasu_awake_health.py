"""Health reads must not expose private memory or confuse old and current state."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


health = load('health_test', 'tools/nasu_awake_health.py')
probe = load('probe_test', 'tools/nasu_scheduler_probe.py')
bridge = load('bridge_test', 'tools/nasuraya_linux_bridge.py')


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.path = self.home / 'migration' / 'working' / ('a' * 32) / 'awake.sqlite3'
        self.make_db(self.path, 6)
        self.make_db(self.home / 'awake-stage' / 'awake.sqlite3', 5)
        (self.home / 'migration' / 'latest-import.json').write_text(json.dumps({
            'working_db': str(self.path), 'id': 'reviewed-import'}))
        self.uid = patch.object(health.os, 'geteuid', return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)

    def make_db(self, path, questions):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            for table, count in [('evidence', 54), ('questions', questions), ('ticks', 17), ('ledger', 24)]:
                db.execute('CREATE TABLE ' + table + '(id INTEGER, content TEXT)')
                db.executemany('INSERT INTO ' + table + ' VALUES (?,?)',
                               [(i, 'PRIVATE_MEMORY_SENTINEL') for i in range(count)])
            db.execute('CREATE TABLE control(name TEXT, value TEXT)')
            db.execute("INSERT INTO control VALUES ('paused','1')")

    def read(self):
        with patch.object(health, 'systemd_value', return_value='unknown'):
            return health.health(self.home)

    def test_current_counts_not_stale_root_and_no_private_text(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = self.read()
        self.assertEqual(result['counts'], [54, 6, 17, 24])
        self.assertEqual(result['source'], 'VERSIONED')
        text = health.render(result)
        self.assertIn('AWAKE_CURRENT=PAUSED:1', text)
        self.assertIn('Q=6', text)
        self.assertNotIn('PRIVATE_MEMORY_SENTINEL', text)
        self.assertNotIn(str(self.home), text)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_missing_current_state_does_not_fall_back_or_create_database(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.read()
        self.assertFalse(self.path.exists())

    def test_symlink_database_rejected(self):
        self.path.unlink()
        self.path.symlink_to(self.home / 'awake-stage' / 'awake.sqlite3')
        with self.assertRaises(ValueError):
            self.read()

    def test_symlink_parent_rejected(self):
        moved = self.home / 'other'
        self.path.parent.rename(moved)
        self.path.parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.read()

    def test_gate_must_match_current_import(self):
        (self.home / 'awake-control.json').write_text(json.dumps({
            'schema': 'nasuraya-awake-offline/1', 'enabled': True, 'import_id': 'different'}))
        with self.assertRaises(ValueError):
            self.read()

    def test_enabled_gate_does_not_imply_running_or_unpause_state(self):
        (self.home / 'awake-control.json').write_text(json.dumps({
            'schema': 'nasuraya-awake-offline/1', 'enabled': True, 'import_id': 'reviewed-import'}))
        result = self.read()
        self.assertEqual(result['gate'], 'ENABLED')
        self.assertEqual(result['paused'], 1)
        self.assertEqual(result['timer'], 'unknown')

    def test_exception_message_not_published(self):
        output = io.StringIO()
        with patch.object(health, 'health', side_effect=ValueError('PRIVATE_SQL_SENTINEL')):
            with contextlib.redirect_stdout(output):
                self.assertEqual(health.main(), 2)
        self.assertEqual(output.getvalue(), 'AWAKE_HEALTH=UNKNOWN;CAUSE=ValueError\n')

    def test_awake_status_dispatches_only_fixed_health_reader(self):
        with patch.object(bridge, 'command', return_value='safe') as command:
            self.assertEqual(bridge.dispatch('awake-status'), 'safe')
        self.assertEqual(command.call_args.args[0],
                         ['/usr/bin/python3', '/usr/local/lib/nasuraya/awake_health.py'])


class ProbeTests(unittest.TestCase):
    def run_probe(self, rc, stdout, stderr):
        results = [types.SimpleNamespace(returncode=0, stdout='active\n', stderr=''),
                   types.SimpleNamespace(returncode=0, stdout='enabled\n', stderr=''),
                   types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)]
        with patch.object(probe.os, 'geteuid', return_value=1000), \
             patch.object(probe.shutil, 'which', return_value='/usr/bin/crontab'), \
             patch.object(probe.subprocess, 'run', side_effect=results):
            return probe.probe()

    def test_permission_error_is_not_scheduler_readiness(self):
        result = self.run_probe(1, '', 'crontabs/nasuraya: Permission denied')
        self.assertFalse(result['user_crontab_readable'])
        self.assertFalse(result['unprivileged_schedule_possible'])

    def test_known_empty_crontab_is_readable(self):
        self.assertTrue(self.run_probe(1, '', 'no crontab for nasuraya')['user_crontab_readable'])

    def test_other_rc_one_error_fails_closed(self):
        self.assertFalse(self.run_probe(1, '', 'unexpected failure')['user_crontab_readable'])


if __name__ == '__main__':
    unittest.main()
