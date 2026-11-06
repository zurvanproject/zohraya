"""No network, keys, models, or repository writes required."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch

from workshop.runner import (TASK_ORDER, MAX_SECONDS, choose_task,
                             filtered_child_environment, run_task,
                             summary_markdown)


class WorkshopTests(unittest.TestCase):
    def test_utc_hourly_rotation(self):
        base = datetime(2026, 10, 21, 0, tzinfo=timezone.utc)
        tasks = [choose_task(base + timedelta(hours=h)) for h in range(8)]
        self.assertEqual(tasks[:4], list(TASK_ORDER))
        self.assertEqual(tasks[:4], tasks[4:])

    def test_timezone_aware_equivalence(self):
        utc = datetime(2026, 10, 21, 11, tzinfo=timezone.utc)
        east = utc.astimezone(timezone(timedelta(hours=3, minutes=30)))
        self.assertEqual(choose_task(utc), choose_task(east))

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            choose_task(datetime(2026, 10, 21))

    def test_no_secrets_in_child_environment(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY':'SECRET', 'GITHUB_TOKEN':'SECRET', 'OPENAI_API_KEY':'SECRET'}):
            env = filtered_child_environment(Path('/tmp/workshop'))
        for key in ('GEMINI_API_KEY','GITHUB_TOKEN','OPENAI_API_KEY'):
            self.assertNotIn(key, env)

    def test_one_approved_command_and_receipt(self):
        calls = []
        with TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            (root / '.github' / 'workflows').mkdir(parents=True)
            def invoke(args, **kw):
                calls.append((args, kw))
                return SimpleNamespace(stdout='ok', stderr='', returncode=0)
            out = Path(temp) / 'out'
            packet = run_task('research', root=root, output=out,
                              now=datetime(2026,10,21,tzinfo=timezone.utc), invoke=invoke)
            self.assertEqual(len(calls), 1)
            self.assertEqual(packet['result'], 'PASSED')
            self.assertEqual(packet['timeout_seconds'], MAX_SECONDS)
            self.assertEqual(calls[0][1]['timeout'], MAX_SECONDS)
            self.assertEqual(json.loads((out / 'receipt.json').read_text())['result'], 'PASSED')
            self.assertNotIn('GITHUB_TOKEN', calls[0][1]['env'])
            self.assertFalse(packet['model_api_used'])
            self.assertIn('research', summary_markdown(packet))

    def test_failing_regression_reported_without_forging_success(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.github' / 'workflows').mkdir(parents=True)
            packet = run_task('body-bridge', root=root, output=root/'out',
                              invoke=lambda *a, **k: SimpleNamespace(stdout='', stderr='fail', returncode=1))
            self.assertEqual(packet['result'], 'FAILED')
            self.assertEqual(packet['exit_code'], 1)
            self.assertIn('cold-recovery', packet['recommended_review'])

    def test_timeout_reported_as_timeout(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.github' / 'workflows').mkdir(parents=True)
            def invoke(args, **kwargs):
                raise subprocess.TimeoutExpired(args, MAX_SECONDS, output=b'partial')
            packet = run_task('research', root=root, output=root/'out', invoke=invoke)
            self.assertEqual(packet['result'], 'TIMED_OUT')
            self.assertIsNone(packet['exit_code'])
            self.assertIn('partial', packet['stdout_tail'])

    def test_unknown_task_rejected_before_run(self):
        with TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                run_task('arbitrary-shell-command', root=Path(temp), output=Path(temp)/'out')

    def test_not_in_repository_rejected(self):
        with TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                run_task('research', root=Path(temp), output=Path(temp)/'out')

    def test_logs_are_bounded_and_sha_recorded(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'.github'/'workflows').mkdir(parents=True)
            packet = run_task('research', root=root, output=root/'out',
                              invoke=lambda *a, **k: SimpleNamespace(stdout='a'*9000,stderr='',returncode=0))
            self.assertEqual(len(packet['stdout_tail']), 3000)
            self.assertEqual(len(packet['stdout_sha256']),64)

    def test_invalid_timezone_rejected_before_execution(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'.github'/'workflows').mkdir(parents=True)
            with self.assertRaises(ValueError):
                run_task('research', root=root, output=root/'out', now=datetime(2026,10,21))


if __name__ == '__main__':
    unittest.main()
