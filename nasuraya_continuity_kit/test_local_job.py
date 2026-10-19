"""Contracts over real SQLite stores; installed crash probes are independent."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from .local_job import LocalJobs, integrity_report
from .store import Store

START = '2026-10-16T10:22:23Z'
DUE = '2026-10-17T10:22:23Z'
LATER = '2026-10-18T10:22:23Z'
RAW = b'["alpha","beta",""]'


class LocalJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'db.sqlite'
        self.store = Store.create(self.path, START)
        self.jobs = LocalJobs(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_report_matches_independent_known_hashes_and_utf8_counts(self):
        raw = '["abc","", "سلام"]'.encode()
        report = self.jobs.run('req', 'run', DUE, raw)['result']
        self.assertEqual(report['record_count'], 3)
        self.assertEqual(report['utf8_bytes'], 11)
        self.assertEqual(report['record_sha256'][:2], [
            'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'])
        self.assertEqual(report['input_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.store.status(DUE)['request_count'], 2)
        self.assertIsNone(self.store.status(DUE)['state']['inflight_run_id'])

    def test_completed_replay_after_restart_never_runs_computation(self):
        first = self.jobs.run('req', 'run', DUE, RAW)
        self.store.close()
        self.store = Store(self.path)
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=AssertionError('duplicate work')):
            self.assertEqual(LocalJobs(self.store).run('req', 'run', DUE, RAW), first)
        self.assertEqual(self.store.status(DUE)['run_count'], 1)

    def test_mutated_input_time_run_or_kind_binding_is_rejected(self):
        self.jobs.run('req', 'run', DUE, RAW)
        for run, now, raw in [('run', DUE, b'[]'), ('other', DUE, RAW), ('run', LATER, RAW)]:
            with self.assertRaisesRegex(ValueError, 'different local parameters'):
                self.jobs.run('req', run, now, raw)

    def test_invalid_input_does_not_consume_budget(self):
        for raw in [b'not-json', b'{}', b'[1]', b'['+b' '*65536+b']', json.dumps(['x'*257]).encode(), json.dumps(['']*257).encode(), b'["\\ud800"]', '[]'.encode('utf-16')]:
            with self.assertRaises((ValueError, UnicodeError)):
                # Validate lone surrogates before claim too.
                self.jobs.run('req', 'run', DUE, raw)
        self.assertEqual(self.store.status(DUE)['run_count'], 0)

    def test_original_time_pause_and_daily_budget_remain_enforced(self):
        with self.assertRaisesRegex(ValueError, 'recent_contact'):
            self.jobs.run('early', 'early', START, RAW)
        self.jobs.run('req', 'run', DUE, RAW)
        with self.assertRaisesRegex(ValueError, 'daily_budget_used'):
            self.jobs.run('req2', 'run2', DUE, RAW)
        self.store.apply('pause', 'pause', LATER)
        with self.assertRaisesRegex(ValueError, 'paused'):
            self.jobs.run('req2', 'run2', LATER, RAW)

    def test_unknown_blocks_exact_retry_new_work_and_legacy_finish(self):
        self.jobs.start('req', 'run', DUE, RAW)
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=AssertionError('reexecuted')):
            with self.assertRaisesRegex(ValueError, 'outcome unknown'):
                self.jobs.run('req', 'run', DUE, RAW)
        with self.assertRaisesRegex(ValueError, 'unresolved_previous_run'):
            self.jobs.run('next', 'next', LATER, RAW)
        with self.assertRaisesRegex(ValueError, 'host reconciliation'):
            self.store.apply('finish', 'bypass', DUE, 'run')
        self.assertIsNone(self.jobs.inspect('run')['result'])

    def test_host_abandon_is_explicit_durable_no_refund_and_never_reexecutes(self):
        self.jobs.start('req', 'run', DUE, RAW)
        with self.assertRaisesRegex(ValueError, 'attestation'):
            self.jobs.abandon('resolve', 'run', DUE, 'host', 'worker reaped')
        result = self.jobs.abandon('resolve', 'run', DUE, 'host', 'worker reaped', True)
        self.assertEqual(result['status'], 'abandoned')
        self.assertIsNone(result['result'])
        self.assertEqual(self.jobs.abandon('resolve', 'run', DUE, 'host', 'worker reaped', True), result)
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=AssertionError()):
            self.assertEqual(self.jobs.run('req', 'run', DUE, RAW), result)
        self.assertEqual(self.store.status(DUE)['decision']['reason'], 'daily_budget_used')
        with self.assertRaises(ValueError): self.jobs.abandon('resolve2', 'run', DUE, 'other', 'changed', True)

    def test_claim_and_input_binding_rollback_together(self):
        self.store.db.execute("CREATE TRIGGER reject_binding BEFORE INSERT ON local_jobs BEGIN SELECT RAISE(ABORT,'injected'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError): self.jobs.run('req', 'run', DUE, RAW)
        self.assertEqual(self.store.status(DUE)['run_count'], 0)
        self.assertEqual(self.store.status(DUE)['request_count'], 0)

    def test_result_and_finish_rollback_together(self):
        self.jobs.start('req', 'run', DUE, RAW)
        with patch.object(self.store, '_apply_in_transaction', side_effect=ValueError('finish failed')):
            with self.assertRaisesRegex(ValueError, 'finish failed'): self.jobs._complete('run', DUE)
        self.assertEqual(self.jobs.inspect('run')['status'], 'running')
        self.assertIsNone(self.jobs.inspect('run')['result'])
        self.assertEqual(self.store.status(DUE)['state']['inflight_run_id'], 'run')

    def test_admission_receipt_without_binding_cannot_be_used_to_execute(self):
        self.store.apply('claim', 'req', DUE, 'run')
        with self.assertRaisesRegex(ValueError, 'no local binding'):
            self.jobs.run('req', 'run', DUE, RAW)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM local_jobs').fetchone()[0], 0)

    def test_maximum_run_id_can_complete(self):
        self.assertEqual(self.jobs.run('req', 'r'*80, DUE, b'[]')['status'], 'completed')

    def test_claim_id_matching_internal_finish_id_completes_and_replays(self):
        request_id = 'local-finish-'+hashlib.sha256(b'run').hexdigest()
        first = self.jobs.run(request_id, 'run', DUE, RAW)
        self.assertEqual(first['status'], 'completed')
        self.store.close()
        self.store = Store(self.path)
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=AssertionError('duplicate work')):
            self.assertEqual(LocalJobs(self.store).run(request_id, 'run', DUE, RAW), first)
        self.assertEqual(self.store.status(DUE)['request_count'], 2)

    def test_finish_receipt_skips_occupied_ids_without_changing_old_receipts(self):
        digest = hashlib.sha256(b'run').hexdigest()
        occupied = ['local-finish-'+digest] + ['local-finish-'+digest[:40]+'-'+str(i) for i in (1, 2)]
        for request_id in occupied:
            self.store.apply('heartbeat', request_id, START)
        old = self.store.db.execute('SELECT id,digest,receipt FROM requests ORDER BY id').fetchall()
        self.assertEqual(self.jobs.run('req', 'run', DUE, RAW)['status'], 'completed')
        for row in old:
            self.assertEqual(self.store.db.execute('SELECT id,digest,receipt FROM requests WHERE id=?', (row[0],)).fetchone(), row)
        finish_id = 'local-finish-'+digest[:40]+'-3'
        receipt = self.store.db.execute('SELECT receipt FROM requests WHERE id=?', (finish_id,)).fetchone()
        self.assertEqual(json.loads(receipt[0])['operation'], 'finish')
        self.assertEqual(self.store.status(DUE)['request_count'], 5)

    def test_finish_id_collision_created_during_computation_is_handled(self):
        request_id = 'local-finish-'+hashlib.sha256(b'run').hexdigest()
        def concurrent_heartbeat(raw):
            other = Store(self.path)
            try: other.apply('heartbeat', request_id, DUE)
            finally: other.close()
            return integrity_report(raw)
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=concurrent_heartbeat):
            self.assertEqual(self.jobs.run('req', 'run', DUE, RAW)['status'], 'completed')
        state = self.store.status(DUE)['state']
        self.assertEqual(state['last_contact_at'], '2026-10-17T10:22:23+00:00')
        self.assertIsNone(state['inflight_run_id'])
        self.assertEqual(self.store.status(DUE)['request_count'], 3)

    def test_concurrent_identical_requests_publish_one_report(self):
        barrier = threading.Barrier(2)
        calls = []
        def report(raw):
            calls.append(1)
            return integrity_report(raw)
        def worker(_):
            store = Store(self.path)
            try:
                jobs = LocalJobs(store)
                barrier.wait(timeout=5)
                try: return jobs.run('req', 'run', DUE, RAW)['status']
                except ValueError as e: return str(e)
            finally: store.close()
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=report):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(worker, [1,2]))
        self.assertIn('completed', results)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.status(DUE)['run_count'], 1)

    def _operator_during_computation(self, operation, contact_time, can_publish):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def report(raw):
            calls.append(1)
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError('operator barrier timed out')
            return integrity_report(raw)
        def worker():
            store = Store(self.path)
            try:
                return LocalJobs(store).run('req', 'run', DUE, RAW)
            finally:
                store.close()
        collision = 'local-finish-'+hashlib.sha256(b'run').hexdigest()
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=report):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(worker)
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    # Different connection, after claim but before publication.
                    self.store.apply(operation, collision, contact_time)
                    old = self.store.db.execute(
                        'SELECT id,digest,receipt FROM requests ORDER BY id').fetchall()
                finally:
                    release.set()
                if can_publish:
                    self.assertEqual(future.result(timeout=5)['status'], 'completed')
                else:
                    with self.assertRaisesRegex(ValueError, 'future control timestamp'):
                        future.result(timeout=5)
        self.assertEqual(len(calls), 1)
        self.store.close()
        self.store = Store(self.path)
        self.jobs = LocalJobs(self.store)
        for row in old:
            self.assertEqual(self.store.db.execute(
                'SELECT id,digest,receipt FROM requests WHERE id=?', (row[0],)).fetchone(), row)
        state = self.store.status(contact_time)['state']
        self.assertEqual(state['enabled'], operation != 'pause')
        self.assertEqual(state['last_contact_at'], contact_time.replace('Z', '+00:00'))
        self.assertEqual(state['last_claimed_at'], DUE.replace('Z', '+00:00'))
        self.assertEqual(state['inflight_run_id'], None if can_publish else 'run')
        with patch('nasuraya_continuity_kit.local_job.integrity_report',
                   side_effect=AssertionError('replay computed a report')):
            if can_publish:
                self.assertEqual(self.jobs.run('req', 'run', DUE, RAW)['status'], 'completed')
            else:
                with self.assertRaisesRegex(ValueError, 'outcome unknown'):
                    self.jobs.run('req', 'run', DUE, RAW)
                self.assertIsNone(self.jobs.inspect('run')['result'])
        self.assertEqual(self.store.status(contact_time)['request_count'], 3 if can_publish else 2)
        self.assertEqual(self.store.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        with self.assertRaises(ValueError):
            self.jobs.run('new', 'new', contact_time, RAW)

    def test_concurrent_pause_collision_preserved_after_publication_and_reopen(self):
        self._operator_during_computation('pause', DUE, True)

    def test_concurrent_heartbeat_collision_preserved_without_refund(self):
        self._operator_during_computation('heartbeat', DUE, True)

    def test_newer_pause_rejects_stale_finish_and_retains_unresolved_claim(self):
        self._operator_during_computation('pause', '2026-10-17T10:22:24Z', False)

    def test_historical_result_replay_does_not_restore_pre_pause_control(self):
        first = self.jobs.run('req', 'run', DUE, RAW)
        self.store.apply('pause', 'pause', LATER)
        before = self.store.status(LATER)
        self.store.close()
        self.store = Store(self.path)
        with patch('nasuraya_continuity_kit.local_job.integrity_report',
                   side_effect=AssertionError('replay computed a report')):
            self.assertEqual(LocalJobs(self.store).run('req', 'run', DUE, RAW), first)
        self.assertEqual(self.store.status(LATER), before)
        self.assertEqual(before['decision']['reason'], 'paused')

    def test_late_worker_cannot_publish_after_host_abandon(self):
        self.jobs.start('req', 'run', DUE, RAW)
        def after_compute(raw):
            other = Store(self.path)
            try: LocalJobs(other).abandon('resolve', 'run', DUE, 'host', 'fixture attestation', True)
            finally: other.close()
            return integrity_report(raw)
        with patch('nasuraya_continuity_kit.local_job.integrity_report', side_effect=after_compute):
            with self.assertRaisesRegex(ValueError, 'already reconciled'): self.jobs._complete('run', DUE)
        self.assertEqual(self.jobs.inspect('run')['status'], 'abandoned')
        self.assertIsNone(self.jobs.inspect('run')['result'])


if __name__ == '__main__': unittest.main()
