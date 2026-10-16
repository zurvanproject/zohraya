"""Real SQLite transitions with disposable fixtures; no external effects."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from .store import Store

START = '2026-10-16T10:22:23Z'
DUE = '2026-10-17T10:22:23Z'


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'fixture.sqlite'
        self.store = Store.create(self.path, START)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_exact_threshold_and_early_attempt_rolls_back(self):
        with self.assertRaisesRegex(ValueError, 'recent_contact'):
            self.store.apply('claim', 'early', '2026-10-17T10:22:22Z', 'first')
        self.assertEqual(self.store.status(DUE)['request_count'], 0)
        self.store.apply('claim', 'on_time', DUE, 'first')
        self.assertEqual(self.store.status(DUE)['run_count'], 1)

    def test_exact_request_replays_after_restart_without_new_transition(self):
        first = self.store.apply('claim', 'request_1', DUE, 'first')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.apply('claim', 'request_1', DUE, 'first'), first)
        self.assertEqual(self.store.status(DUE)['request_count'], 1)

    def test_request_id_binding_is_immutable(self):
        self.store.apply('claim', 'request_1', DUE, 'first')
        with self.assertRaisesRegex(ValueError, 'different parameters'):
            self.store.apply('claim', 'request_1', DUE, 'different')
        self.assertEqual(self.store.status(DUE)['run_count'], 1)

    def test_unresolved_claim_survives_restart_and_never_expires_automatically(self):
        self.store.apply('claim', 'request_1', DUE, 'first')
        self.store.close()
        self.store = Store(self.path)
        later = '2026-11-17T10:22:23Z'
        self.assertEqual(self.store.status(later)['decision']['reason'], 'unresolved_previous_run')
        with self.assertRaises(ValueError): self.store.apply('claim', 'request_2', later, 'second')

    def test_completed_run_id_cannot_be_reused_after_another_run(self):
        self.store.apply('claim', 'c1', DUE, 'first')
        self.store.apply('finish', 'f1', DUE, 'first')
        self.store.apply('claim', 'c2', '2026-10-18T10:22:23Z', 'second')
        self.store.apply('finish', 'f2', '2026-10-18T10:22:23Z', 'second')
        with self.assertRaisesRegex(ValueError, 'historical'):
            self.store.apply('claim', 'c3', '2026-10-19T10:22:23Z', 'first')
        self.assertEqual(self.store.status('2026-10-19T10:22:23Z')['run_count'], 2)

    def test_two_independent_connections_have_one_claim_winner(self):
        barrier = threading.Barrier(2)
        def compete(n):
            store = Store(self.path)
            try:
                barrier.wait(timeout=5)
                try:
                    store.apply('claim', f'request_{n}', DUE, f'run_{n}')
                    return True
                except ValueError:
                    return False
            finally: store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(compete, [1, 2])), [False, True])
        self.assertEqual(self.store.status(DUE)['run_count'], 1)

    def test_pause_keeps_unresolved_run_and_heartbeat_does_not_resume(self):
        self.store.apply('claim', 'c1', DUE, 'first')
        self.store.apply('pause', 'p1', DUE)
        self.store.apply('heartbeat', 'h1', DUE)
        status = self.store.status(DUE)
        self.assertEqual(status['decision']['reason'], 'paused')
        self.assertEqual(status['state']['inflight_run_id'], 'first')

    def test_existing_and_foreign_database_are_not_overwritten(self):
        with self.assertRaises(FileExistsError): Store.create(self.path, START)
        foreign = Path(self.tmp.name)/'foreign.sqlite'
        db = sqlite3.connect(foreign); db.execute('CREATE TABLE important(data TEXT)'); db.close()
        before = hashlib.sha256(foreign.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'not a Continuity'): Store(foreign)
        self.assertEqual(hashlib.sha256(foreign.read_bytes()).hexdigest(), before)

    def test_invalid_clock_and_wrong_finish_preserve_state(self):
        self.store.apply('claim', 'c1', DUE, 'first')
        before = self.store.status(DUE)
        with self.assertRaises(ValueError): self.store.apply('finish', 'f1', DUE, 'wrong')
        with self.assertRaises(ValueError): self.store.apply('heartbeat', 'h1', '2026-10-16T10:22:23Z')
        self.assertEqual(self.store.status(DUE), before)

    def test_missing_control_row_is_rejected_without_reset(self):
        self.store.db.execute('DELETE FROM control')
        with self.assertRaisesRegex(ValueError, 'missing or invalid'):
            Store(self.path)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM control').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
