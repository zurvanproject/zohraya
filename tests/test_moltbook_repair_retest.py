import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import test_moltbook_memory_decisions as public
import test_moltbook_native_feedback as native
import test_moltbook_recovery as recovery


job = public.module('moltbook_repair_retest')


def exercise(memory, experiment, installation):
    context = native.m.source_context(memory)
    engine = native.m.load_engine(installation)
    with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network connection')) as network:
        result = job.run(experiment, memory, context, recovery.m, native.m, public.m, engine)
        network.assert_not_called()
    return result


def file_digests(paths):
    return {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}


def completed_native_receipts(root):
    records = {}
    for path in root.rglob('*'):
        if path.suffix not in {'.sqlite', '.sqlite3', '.db'}:
            continue
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            has_decisions = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone()
            if has_decisions:
                records[path.relative_to(root)] = db.execute(
                    "SELECT id,record FROM decisions WHERE status='complete' ORDER BY id"
                ).fetchall()
    return records


class RepairRetest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = native.native_fixture()
        cls.engine = native.m.load_engine(cls.installation)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.memory = Path(tmp.name) / 'Nasuraya/PublicMemoryV1'
        public.c.capture(self.memory, public.page([public.comment()]))
        public.m.compare(self.memory, public.page([public.comment()]))
        self.context = native.m.source_context(self.memory)
        suffix = self.context['decision_sha256'][:16]
        self.prior = self.memory / 'RecoveryLabV1' / suffix
        self.lab = self.memory / 'RepairRetestV1' / suffix
        # An additional public comment makes the verified replacement distinguishable from the old snapshot.
        payload = public.page([public.comment(), public.comment('later', 'visitor')])
        self.prior_result = recovery.m.run(self.prior, self.memory, self.context, native.m,
                                           public.m, self.engine, payload)
        self.assertTrue(self.prior_result['success'])

    def run_job(self):
        return exercise(self.memory, self.lab, self.installation)

    def protected_paths(self):
        return [self.memory / 'anchor.json', self.memory / 'episodes.sqlite3',
                *(p for p in self.prior.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm')))]

    def test_verifying_repaired_copy_changes_the_next_free_choice(self):
        paths = self.protected_paths()
        before = file_digests(paths)
        result = self.run_job()
        self.assertTrue(result['success'])
        self.assertEqual(result['before'], 'recheck_source')
        self.assertEqual(result['control'], 'recheck_source')
        self.assertEqual(result['after'], 'use_cached')
        self.assertEqual(result['cold'], 'use_cached')
        self.assertEqual(result['validated_sha256'], self.prior_result['rows']['memory'][1]['actual']['sha256'])
        self.assertNotEqual(result['validated_sha256'], self.context['observation_sha256'])
        self.assertEqual(file_digests(paths), before)

    def test_new_process_replays_sealed_result_without_reexecuting_the_experiment(self):
        first = self.run_job()
        self.assertFalse(first['replay'])
        before = completed_native_receipts(self.lab)
        self.assertTrue(any(before.values()))
        child = ('import json,sys; from pathlib import Path; from test_moltbook_repair_retest import exercise; '
                 'print(json.dumps(exercise(*(Path(x) for x in sys.argv[1:]))))')
        completed = subprocess.run([sys.executable, '-c', child, str(self.memory), str(self.lab), str(self.installation)],
                                   cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
                                   check=True, timeout=20)
        replay = json.loads(completed.stdout)
        self.assertTrue(replay['replay'])
        self.assertEqual(dict(replay, replay=False), first)
        self.assertEqual(completed_native_receipts(self.lab), before)

    def test_tampered_refetched_data_cannot_authorize_local_trust(self):
        (self.prior / 'refetched.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_job()
        self.assertFalse((self.lab / 'completed' / 'result.json').exists())

    def test_resealed_but_mismatched_source_is_rejected(self):
        replacement = recovery.m.unseal(self.prior, 'refetched')
        replacement['nodes'][0]['content'] += ' an edit after recovery'
        recovery.m.seal(self.prior, 'refetched', replacement)
        with self.assertRaises(ValueError):
            self.run_job()
        self.assertFalse((self.lab / 'completed' / 'result.json').exists())

    def test_replay_checks_the_result_seal(self):
        self.run_job()
        (self.lab / 'completed' / 'result.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_job()

    def test_replay_rechecks_the_native_recovery_source(self):
        self.run_job()
        with closing(sqlite3.connect(self.prior / 'memory.sqlite3')) as db, db:
            row = db.execute("SELECT record FROM decisions WHERE id='memory-2'").fetchone()
            changed = json.loads(row[0])
            changed['actual_outcome']['sha256'] = '0' * 64
            db.execute("UPDATE decisions SET record=? WHERE id='memory-2'", (json.dumps(changed),))
        with self.assertRaises(ValueError):
            self.run_job()


if __name__ == '__main__':
    unittest.main()
