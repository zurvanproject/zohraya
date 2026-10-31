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
            self.assertEqual(db.execute('SELECT count(*) FROM jobs WHERE status="completed"').fetchone()[0], 6)
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
        counts = {'active': 0, 'peak': 0, 'started': 0}
        def overlap(*args):
            with lock:
                counts['active'] += 1
                counts['started'] += 1
                index = counts['started']
                counts['peak'] = max(counts['peak'], counts['active'])
            # Only the first PAIR must overlap. The fifth worker has no peer
            # at max_workers=2; forcing it into a two-party barrier is a test bug.
            if index <= 2:
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

    def test_review_rejects_any_paid_model_receipt(self):
        receipts = {role: {'passed': True, 'network_syscalls_denied': True,
            'model_api_calls': 0, 'commands': [{'returncode': 0,
                'interrupted': None, 'network_syscalls_denied': True}]}
            for role in worker.ROLES}
        self.assertTrue(engine.review(receipts)['passed'])
        receipts['self_model']['model_api_calls'] = 1
        review = engine.review(receipts)
        self.assertFalse(review['passed'])
        self.assertTrue(any('paid model' in item for item in review['reasons']))

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



class SelfModelMetricsTests(unittest.TestCase):
    """The new worker must not confuse a passing protocol with a positive effect."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        (self.output / 'self_model').mkdir()
        names = (
            'all_native_cycles_completed', 'no_failed_or_unresolved',
            'budgets_exhausted', 'expected_split', 'complete_unique_trials',
            'forecasts_preserved', 'expected_training', 'training_is_warmup_only',
            'frozen_training', 'protocol_preserved', 'fixed_trial_order',
            'scores_match_frozen_forecasts', 'forecasts_match_prior_evidence',
            'prior_evidence_stamps_match',
        )
        self.summary = {
            'schema': 'nasuraya-self-knowledge-evaluation/1',
            'validation_passed': True,
            'validation_checks': {name: True for name in names},
            'actual_native_cycles': 64, 'expected_native_cycles': 64,
            'training_receipts': 40,
            'warmup': {'attempted': 40, 'scored': 40},
            'holdout': {'attempted': 24, 'scored': 24, 'supported': 24,
                        'failed_or_unresolved': 0, 'mean_brier': .18,
                        'mean_pooled_brier': .31,
                        'mean_shuffled_context_brier': .5,
                        'mean_zero_history_brier': .75},
            'all_forecasts_reserved_before_execution': True,
            'holdout_outcomes_used_for_fitting': False,
            'model_api_calls': 0, 'physical_actuator_calls': 0,
            'heldout_brier_improvement_absolute': .13,
            'context_helped_on_this_constructed_holdout': True,
        }

    def audit(self):
        (self.output / 'self_model/summary.json').write_text(json.dumps(self.summary))
        return worker.metrics('self_model', self.output)

    def test_accepts_frozen_holdout_with_negative_controls(self):
        result = self.audit()
        self.assertEqual(result['native_cycles'], 64)
        self.assertAlmostEqual(result['pooled_minus_context_brier'], .13)
        self.assertTrue(result['context_helped_on_constructed_holdout'])
        self.assertIn('not consciousness', result['scope'])

    def test_negative_improvement_is_reported_not_hidden(self):
        self.summary['holdout']['mean_brier'] = .4
        self.summary['heldout_brier_improvement_absolute'] = -.09
        self.summary['context_helped_on_this_constructed_holdout'] = False
        result = self.audit()
        self.assertAlmostEqual(result['pooled_minus_context_brier'], -.09)
        self.assertFalse(result['context_helped_on_constructed_holdout'])

    def test_fail_closed_when_integrity_or_boundaries_change(self):
        for name, update in (
            ('validation', lambda s: s['validation_checks'].update(frozen_training=False)),
            ('fitting', lambda s: s.update(holdout_outcomes_used_for_fitting=True)),
            ('api', lambda s: s.update(model_api_calls=1)),
            ('sample', lambda s: s['holdout'].update(scored=23)),
            ('delta', lambda s: s.update(heldout_brier_improvement_absolute=.7)),
            ('nan', lambda s: s['holdout'].update(mean_brier=float('nan'))),
        ):
            with self.subTest(name=name):
                original = json.loads(json.dumps(self.summary))
                update(self.summary)
                with self.assertRaises(ValueError):
                    self.audit()
                self.summary = original


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

    def test_self_model_fixture_file_cap_does_not_expand_log_or_other_agents(self):
        command = worker.commands('self_model', Path('/tmp/test-fixture'))[0]
        self.assertEqual(worker.file_size_limit(command), 16 * 1024 * 1024)
        self.assertEqual(worker.MAX_LOG, 2 * 1024 * 1024)
        for other in ('body', 'memory', 'genome', 'research'):
            self.assertEqual(worker.file_size_limit(
                worker.commands(other, Path('/tmp/test-fixture'))[0]), worker.MAX_LOG)
        self.assertEqual(worker.file_size_limit(['-m', 'unknown.module', 'self-knowledge-eval']),
                         worker.MAX_LOG)

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
