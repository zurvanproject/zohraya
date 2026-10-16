from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from visual_status import digest, observe, render, read_file


class VisualChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.py'
        self.source.write_text("raise RuntimeError('NEVER_IMPORT_ME')")
        self.manifest = self.root / 'baseline.json'
        self.manifest.write_text(json.dumps({'source.py': hashlib.sha256(self.source.read_bytes()).hexdigest()}))
        self.expected = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.alerts = self.root / 'alerts.sqlite'
        self.now = datetime.now(timezone.utc)
        with sqlite3.connect(self.alerts) as db:
            db.execute('CREATE TABLE control (singleton INTEGER PRIMARY KEY,latched INTEGER,head TEXT,seq INTEGER)')
            db.execute('INSERT INTO control VALUES (1,0,?,0)', ('0' * 64,))
            db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY,record TEXT,hash TEXT)')

    def snapshot(self):
        return observe(self.root, self.manifest, self.expected, self.alerts, self.now)

    def event(self, code='invalid_request', severity='warning', at=None):
        with sqlite3.connect(self.alerts) as db:
            head, seq = db.execute('SELECT head,seq FROM control').fetchone()
            event = dict(seq=seq + 1, previous=head, at_utc=(at or self.now).isoformat(), code=code, severity=severity)
            h = digest(event)
            db.execute('INSERT INTO events VALUES (?,?,?)', (seq + 1, json.dumps(event), h))
            db.execute('UPDATE control SET head=?,seq=?', (h, seq + 1))

    def test_healthy_observation_no_project_import_or_disk_changes(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch('subprocess.run', side_effect=AssertionError('unexpected process')):
            result = self.snapshot()
        self.assertEqual(result['state'], 'healthy')
        self.assertEqual(result['checks'], dict(source='pass', audit='pass'))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_warning_survives_subsequent_allowed_event(self):
        self.event()
        self.event('allowed', 'info')
        self.assertEqual(self.snapshot()['state'], 'warning')
        self.assertEqual(self.snapshot()['audit']['warnings'], 1)

    def test_latch_is_shown_without_reset(self):
        with sqlite3.connect(self.alerts) as db:
            db.execute('UPDATE control SET latched=1')
        self.assertEqual(self.snapshot()['state'], 'blocked')
        with sqlite3.connect(self.alerts) as db:
            self.assertEqual(db.execute('SELECT latched FROM control').fetchone()[0], 1)

    def test_changed_source_blocks(self):
        self.source.write_text('changed')
        self.assertEqual(self.snapshot()['state'], 'blocked')

    def test_rewritten_manifest_is_not_self_trusted(self):
        self.manifest.write_text('{}')
        self.assertEqual(self.snapshot()['state'], 'blocked')

    def test_missing_store_stays_missing_and_unknown(self):
        self.alerts.unlink()
        self.assertEqual(self.snapshot()['state'], 'unknown')
        self.assertFalse(self.alerts.exists())

    def test_missing_source_and_wrong_digest_never_healthy(self):
        self.source.unlink()
        self.assertEqual(self.snapshot()['state'], 'unknown')
        self.expected = 'not a digest'
        self.assertEqual(self.snapshot()['state'], 'unknown')

    def test_symlink_source_and_store_refused(self):
        target = self.root / 'target'
        self.source.rename(target)
        self.source.symlink_to(target)
        self.assertEqual(self.snapshot()['state'], 'unknown')
        self.source.unlink()
        target.rename(self.source)
        self.alerts.rename(target)
        self.alerts.symlink_to(target)
        self.assertNotEqual(self.snapshot()['state'], 'healthy')

    def test_oversized_or_non_regular_input_refused(self):
        self.manifest.write_bytes(b' ' * (128 * 1024 + 1))
        self.assertEqual(self.snapshot()['state'], 'unknown')
        fifo = self.root / 'fifo'
        import os
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            read_file(fifo, 100)

    def test_audit_tamper_or_truncation_blocks(self):
        self.event()
        with sqlite3.connect(self.alerts) as db:
            db.execute("UPDATE events SET record='{}'")
        self.assertEqual(self.snapshot()['state'], 'blocked')
        with sqlite3.connect(self.alerts) as db:
            db.execute('DELETE FROM events')
        self.assertEqual(self.snapshot()['state'], 'blocked')

    def test_unrecognized_event_not_rendered_even_with_valid_hash(self):
        self.event('</script><img src=x onerror=alert(1)>', 'warning')
        result = self.snapshot()
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(result['audit']['recent'], [])
        self.assertNotIn('onerror', json.dumps(result))

    def test_future_event_blocks(self):
        self.event(at=self.now + timedelta(seconds=60))
        self.assertEqual(self.snapshot()['state'], 'blocked')

    def test_rollback_journal_or_wal_is_unknown(self):
        Path(str(self.alerts) + '-wal').write_bytes(b'pending')
        self.assertEqual(self.snapshot()['state'], 'unknown')

    def test_corrupt_database_is_unknown_and_preserved(self):
        self.alerts.write_bytes(b'bad database')
        self.assertEqual(self.snapshot()['state'], 'unknown')
        self.assertEqual(self.alerts.read_bytes(), b'bad database')

    def test_no_raw_paths_or_exceptions_leak(self):
        with patch('visual_status.read_audit', side_effect=OSError('SECRET_PATH_TOKEN')):
            result = self.snapshot()
        self.assertNotIn('SECRET_PATH_TOKEN', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_known_block_not_hidden_by_unavailable_audit(self):
        self.source.write_text('changed')
        self.alerts.unlink()
        self.assertEqual(self.snapshot()['state'], 'blocked')

    def test_html_payload_cannot_terminate_json_script(self):
        result = self.snapshot()
        result['hostile'] = '</script><script>alert(1)</script>&'
        html = render(result)
        self.assertNotIn('</script><script>alert(1)', html)
        self.assertIn('\\u003c/script\\u003e', html)
        self.assertIn("connect-src 'none'", html)
        self.assertNotIn('innerHTML', html)
        self.assertNotIn('unsafe-inline', html)
        self.assertNotIn('__SCRIPT_HASH__', html)
        import base64
        import re
        script = re.search(r'<script>(.*?)</script>', html, re.S).group(1)
        sha = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + sha + "'", html)


if __name__ == '__main__':
    unittest.main()
