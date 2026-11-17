from contextlib import closing
"""Engine unit tests and real Linux subprocess/network/cancellation probes."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from . import engine, worker


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.work = self.base / 'repo', self.base / 'work'
        (self.root / 'examples').mkdir(parents=True)
        self.source = self.root / 'examples/sample.py'
        self.source.write_text('VALUE = 1\n')
        self.calls = []

    def fake(self, role, snapshot, output, stop, deadline):
        self.calls.append(role)
        output.mkdir(parents=True)
        (output / 'proof.txt').write_text(role)
        return {'agent': role, 'passed': True, 'network_syscalls_denied': True,
                'model_api_calls': 0, 'metrics': {},
                'commands': [{'returncode': 0, 'interrupted': None, 'network_syscalls_denied': True}]}

    def invoke(self, name='run1', workers=2):
        return engine.run(self.root, self.work, name, workers)

    def test_success_and_durable_jobs(self):
        with patch.object(worker, 'execute', self.fake):
            report = self.invoke()
        self.assertEqual(report['status'], 'passed')
        self.assertCountEqual(self.calls, worker.ROLES)
        self.assertEqual(report['model_api_calls'], 0)
        with closing(sqlite3.connect(self.work / 'ledger.sqlite')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs WHERE status="completed"').fetchone()[0], 5)
        self.assertEqual(self.source.read_text(), 'VALUE = 1\n')

    def test_replay_no_worker_execution(self):
        with patch.object(worker, 'execute', self.fake):
            first = self.invoke()
        with patch.object(worker, 'execute', side_effect=AssertionError('must not run')):
            self.assertEqual(first, self.invoke())

    def test_replay_reconstructs_summary(self):
        with patch.object(worker, 'execute', self.fake):
            first = self.invoke()
        (self.work / 'run1/summary.json').unlink()
        with patch.object(worker, 'execute', side_effect=AssertionError('must not run')):
            self.assertEqual(first, self.invoke())
        self.assertTrue((self.work / 'run1/summary.json').exists())

    def test_artifact_tamper_rejected(self):
        with patch.object(worker, 'execute', self.fake):
            self.invoke()
        (self.work / 'run1/body/proof.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            self.invoke()

    def test_source_drift_rejected(self):
        with patch.object(worker, 'execute', self.fake):
            self.invoke()
        self.source.write_text('VALUE = 2\n')
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.invoke()

    def test_configuration_drift_rejected(self):
        with patch.object(worker, 'execute', self.fake):
            self.invoke()
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.invoke(workers=3)

    def test_failed_worker_blocks_review_without_retry(self):
        def fail(role, *args):
            result = self.fake(role, *args)
            if role == 'body':
                result['passed'] = False
            return result
        with patch.object(worker, 'execute', fail):
            first = self.invoke()
        self.assertEqual(first['status'], 'failed')
        self.assertFalse(first['reviewer']['passed'])
        with patch.object(worker, 'execute', side_effect=AssertionError('no retry')):
            self.assertEqual(first, self.invoke())

    def test_worker_exception_recorded(self):
        with patch.object(worker, 'execute', side_effect=ValueError('injected failure')):
            report = self.invoke()
        self.assertEqual(report['status'], 'failed')
        self.assertIn('ValueError', report['workers']['body']['error'])

    def test_preexisting_stop_prevents_claim(self):
        self.work.mkdir()
        (self.work / 'STOP').touch()
        with self.assertRaisesRegex(RuntimeError, 'paused'):
            self.invoke()
        with closing(sqlite3.connect(self.work / 'ledger.sqlite')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 0)

    def test_budget_exhaustion_blocks_new_work(self):
        with patch.object(engine, 'MAX_RUN_SECONDS', 0), patch.object(worker, 'execute', side_effect=AssertionError('budget')):
            report = self.invoke()
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(all('not started' in r['error'] for r in report['workers'].values()))

    def test_parallel_limit_and_overlap(self):
        lock, barrier = threading.Lock(), threading.Barrier(2)
        counts = {'active': 0, 'peak': 0}
        def overlap(*args):
            with lock:
                counts['active'] += 1
                counts['peak'] = max(counts['peak'], counts['active'])
            barrier.wait(timeout=5)
            result = self.fake(*args)
            with lock:
                counts['active'] -= 1
            return result
        with patch.object(worker, 'execute', overlap):
            report = self.invoke()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(counts['peak'], 2)

    def test_exclusive_coordinator(self):
        self.work.mkdir()
        with engine.coordinator_lock(self.work):
            with self.assertRaisesRegex(RuntimeError, 'another coordinator'):
                self.invoke()

    def test_invalid_run_id(self):
        for name in ('../escape', '', 'a/b', 'x' * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.invoke(name)

    def test_invalid_parallelism(self):
        for value in (0, 5, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.invoke(workers=value)

    def test_workspace_inside_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            engine.run(self.root, self.root / 'output', 'x')

    def test_empty_source_rejected(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'no repository'):
            self.invoke()

    def test_symlink_file_rejected(self):
        (self.root / 'examples/link.py').symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.invoke()

    def test_symlink_root_rejected(self):
        (self.root / 'runtimes').symlink_to(self.root / 'examples', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.invoke()

    def test_nonsecret_gitignore_metadata_is_ignored(self):
        (self.root / 'examples/.gitignore').write_text('*.pyc\n')
        with patch.object(worker, 'execute', self.fake):
            report = self.invoke()
        self.assertEqual(report['status'], 'passed')

    def test_hidden_credentials_rejected(self):
        (self.root / 'examples/.env.local').write_text('NOT_A_REAL_SECRET')
        with self.assertRaisesRegex(ValueError, 'credential'):
            self.invoke()

    def test_source_size_cap(self):
        with patch.object(engine, 'MAX_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'size budget'):
                self.invoke()

    def test_incomplete_review_fails(self):
        self.assertFalse(engine.review({})['passed'])

    def test_actual_coordinator_kill_blocks_replay(self):
        marker = self.base / 'claimed'
        script = '''from pathlib import Path
import sys,time
from nasuraya_agent_network import engine,worker
def slow(*args):
    Path(sys.argv[3]).write_text('claimed')
    time.sleep(60)
worker.execute=slow
engine.run(Path(sys.argv[1]),Path(sys.argv[2]),'crash',1)
'''
        process = subprocess.Popen([sys.executable, '-c', script, str(self.root), str(self.work), str(marker)])
        try:
            deadline = time.monotonic() + 8
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists())
        finally:
            process.kill(); process.wait(timeout=5)
        self.assertEqual(process.returncode, -signal.SIGKILL)
        with patch.object(worker, 'execute', side_effect=AssertionError('must not retry')):
            with self.assertRaisesRegex(RuntimeError, 'unfinished run'):
                self.invoke('crash', 1)


class RealWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.snapshot = self.base / 'snapshot'
        self.snapshot.mkdir()
        self.output, self.stop = self.base / 'output', self.base / 'STOP'

    def execute_code(self, text, seconds=5):
        (self.snapshot / 'probe.py').write_text(text)
        with patch.object(worker, 'commands', return_value=[['-m', 'probe']]), patch.object(worker, 'metrics', return_value={}):
            return worker.execute('body', self.snapshot, self.output, self.stop, time.monotonic() + seconds)

    def test_real_network_and_secrets_denied_in_child_and_grandchild(self):
        code = '''import errno,os,socket,subprocess,sys
assert 'OPENAI_API_KEY' not in os.environ
assert 'GITHUB_TOKEN' not in os.environ
try: socket.socket()
except OSError as e: assert e.errno == errno.EPERM
else: raise AssertionError('network permitted')
p=subprocess.run([sys.executable,'-c','import socket; socket.socket()'],capture_output=True)
assert p.returncode != 0 and b'Operation not permitted' in p.stderr
print('probe passed')
'''
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sentinel-not-a-key', 'GITHUB_TOKEN': 'sentinel-not-a-token'}):
            result = self.execute_code(code)
        self.assertTrue(result['passed'], result)
        self.assertTrue(result['network_syscalls_denied'])

    def test_disposable_source_copy(self):
        text = "from pathlib import Path\nPath(__file__).write_text('changed')\n"
        result = self.execute_code(text)
        self.assertTrue(result['passed'], result)
        self.assertEqual((self.snapshot / 'probe.py').read_text(), text)
        self.assertFalse((self.output / 'source').exists())

    def test_real_timeout(self):
        result = self.execute_code('import time\ntime.sleep(60)\n', seconds=.3)
        self.assertFalse(result['passed'])
        self.assertEqual(result['commands'][0]['interrupted'], 'timeout')
        self.assertLess(result['elapsed_seconds'], 3)

    def test_real_pause_kills_worker(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.execute_code, 'import time\ntime.sleep(60)\n')
            deadline = time.monotonic() + 3
            while not (self.output / 'command-0.log').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.stop.touch()
            result = future.result(timeout=5)
        self.assertFalse(result['passed'])
        self.assertIn('stopped', result['error'])

    def test_nonzero_exit_fails(self):
        result = self.execute_code('raise SystemExit(7)\n')
        self.assertFalse(result['passed'])
        self.assertEqual(result['commands'][0]['returncode'], 7)

    def test_unknown_role_rejected(self):
        with self.assertRaises(ValueError):
            worker.execute('api', self.snapshot, self.output, self.stop, time.monotonic() + 5)


if __name__ == '__main__':
    unittest.main()
