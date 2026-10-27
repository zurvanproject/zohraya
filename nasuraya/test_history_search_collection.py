"""Bounded cross-session retrieval; synthetic archives and no active import."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.nasuraya_affect import history
from examples.nasuraya_affect.body_dialogue import DialogueBodyBridge
from examples.nasuraya_affect.engine import AffectiveAgent
from examples.nasuraya_body_loop.host import BodyLoop
from nasuraya import history_search_worker as target
from nasuraya.test_history_search import message, ROOT


def entries(*pairs):
    return [dict(archive=str(path), expected_sha256=pin) for path, pin in pairs]


class CollectionSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.folder_a = cls.root/'session-a'; cls.folder_a.mkdir()
        cls.folder_b = cls.root/'session-b'; cls.folder_b.mkdir()
        for folder, text in ((cls.folder_a, 'تعادل در نشست اول'),
                             (cls.folder_b, 'تعادل در نشست دوم')):
            with BodyLoop.start(folder/'body.sqlite', max_actions=1) as body, \
                 AffectiveAgent(folder/'affect.sqlite') as affect:
                DialogueBodyBridge.enable(body, affect).receive(message('shared', text))
        cls.a = cls.root/'a.json'; cls.b = cls.root/'b.json'
        cls.pin_a = history.export_history(cls.folder_a, cls.a)['archive_sha256']
        cls.pin_b = history.export_history(cls.folder_b, cls.b)['archive_sha256']
        # A second snapshot of the same session deliberately overlaps the first.
        with BodyLoop(cls.folder_a/'body.sqlite') as body, \
             AffectiveAgent(cls.folder_a/'affect.sqlite') as affect:
            DialogueBodyBridge(body, affect).receive(message('later', 'حافظه پس از تعادل'))
        cls.a_later = cls.root/'a-later.json'
        cls.pin_a_later = history.export_history(cls.folder_a, cls.a_later)['archive_sha256']
        cls.pairs = entries((cls.a, cls.pin_a), (cls.b, cls.pin_b))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def search(self, pairs=None, query='تعادل', limit=10):
        return target.search_collection(self.pairs if pairs is None else pairs, query, limit)

    def test_same_local_id_in_two_sessions_keeps_both_original_sources(self):
        result = self.search()
        self.assertEqual(result['schema'], target.COLLECTION_SCHEMA)
        self.assertEqual(len(result['hits']), 2)
        self.assertEqual({r['message_id'] for r in result['hits']}, {'shared'})
        self.assertEqual({r['message_text'] for r in result['hits']},
                         {'تعادل در نشست اول', 'تعادل در نشست دوم'})
        self.assertEqual(len({r['historical_id'] for r in result['hits']}), 2)
        for hit in result['hits']:
            self.assertTrue(hit['historical_id'].startswith(hit['archive_sha256']+'/'))
            self.assertEqual(hit['message_source'], 'conversation://shared')
            self.assertEqual(hit['appraisal_kind'], 'caller_authored_interpretation')

    def test_input_order_does_not_change_ranking_or_result(self):
        self.assertEqual(self.search(), self.search(list(reversed(self.pairs))))

    def test_overlapping_snapshots_are_not_merged_or_called_independent(self):
        result = self.search(entries((self.a, self.pin_a), (self.a_later, self.pin_a_later)))
        shared = [r for r in result['hits'] if r['message_id'] == 'shared']
        self.assertEqual(len(shared), 2)
        self.assertEqual(len({r['source_binding_id'] for r in shared}), 1)
        self.assertEqual(len({r['historical_id'] for r in shared}), 2)
        self.assertIn('not independent experiences', result['overlap_policy'])

    def test_one_bad_pin_rejects_whole_request_before_query(self):
        bad = entries((self.a, self.pin_a), (self.b, 'f'*64))
        with patch.object(target, '_matching_rows', side_effect=AssertionError('partial query')):
            with self.assertRaisesRegex(ValueError, 'pinned export'):
                self.search(bad)

    def test_changed_archive_after_pin_rejects_whole_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            damaged = Path(tmp)/'damaged.json'
            snapshot = history.envelope(self.b.read_text())
            snapshot['original_location'] += '-changed'
            damaged.write_text(history.canonical(dict(value=snapshot, sha256=history.digest(snapshot))))
            with self.assertRaisesRegex(ValueError, 'pinned export'):
                self.search(entries((self.a, self.pin_a), (damaged, self.pin_b)))

    def test_duplicate_archive_pin_is_rejected_even_for_another_path(self):
        with patch.object(target, '_bytes', side_effect=AssertionError('read after duplicate')):
            with self.assertRaisesRegex(ValueError, 'duplicate archive SHA'):
                self.search(entries((self.a, self.pin_a), (self.b, self.pin_a)))

    def test_collection_count_and_exact_entry_contract(self):
        for bad in ([], self.pairs*3, None,
                    [dict(self.pairs[0], future=True)],
                    [dict(archive=str(self.a), expected_sha256='wrong')]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                target.search_collection(bad, 'تعادل')

    def test_aggregate_bound_checks_exact_read_bytes_before_indexing(self):
        maximum = self.a.stat().st_size + self.b.stat().st_size - 1
        with patch.object(target, 'MAX_COLLECTION_BYTES', maximum), \
             patch.object(target, '_matching_rows', side_effect=AssertionError('oversized query')):
            with self.assertRaisesRegex(ValueError, '64 MiB'):
                self.search()

    def test_one_archive_collection_uses_explicit_collection_schema(self):
        collection = self.search(entries((self.a, self.pin_a)))
        original = target.search(self.a, self.pin_a, 'تعادل')
        self.assertEqual(original['schema'], target.SCHEMA)
        self.assertEqual(collection['schema'], target.COLLECTION_SCHEMA)
        self.assertNotIn('archives', original)
        self.assertNotIn('archive_sha256', original['hits'][0])
        hit = dict(collection['hits'][0]); hit.pop('archive_sha256'); hit.pop('source_binding_id')
        self.assertEqual(hit, original['hits'][0])

    def test_limit_and_conjunctive_query_remain_bounded(self):
        self.assertEqual(len(self.search(limit=1)['hits']), 1)
        self.assertEqual(self.search(query='تعادل نایافتنی')['hits'], [])
        for bad in (0, 33, True):
            with self.assertRaises(ValueError): self.search(limit=bad)

    def test_no_source_changes_or_actions(self):
        paths = [self.a, self.b, self.a_later,
                 *[p for folder in (self.folder_a, self.folder_b) for p in folder.iterdir() if p.is_file()]]
        before = {str(p): p.read_bytes() for p in paths}
        with patch.object(BodyLoop, 'step', side_effect=AssertionError('body effect')), \
             patch.object(AffectiveAgent, 'step', side_effect=AssertionError('learning effect')):
            self.search()
        self.assertEqual(before, {str(p): p.read_bytes() for p in paths})

    def test_unresolved_status_is_not_promoted(self):
        reports = [history.load_history(self.a, self.pin_a), history.load_history(self.b, self.pin_b)]
        reports[1]['records'][0]['status'] = 'unresolved_do_not_execute'
        with patch.object(target, 'load_history', side_effect=deepcopy(reports)):
            result = self.search()
        hit = next(r for r in result['hits'] if r['archive_sha256'] == self.pin_b)
        self.assertEqual(hit['status'], 'unresolved_do_not_execute')
        self.assertFalse(hit['native_outcome_recorded'])

    def test_cold_collection_cli_and_mismatched_pair_counts(self):
        def call(pairs):
            command = [sys.executable, '-m', 'nasuraya.history_search', '--query', 'تعادل']
            for path, pin in pairs:
                command.extend(['--archive', str(path), '--expected-sha256', pin])
            return subprocess.run(command, cwd=ROOT, env=dict(os.environ), text=True, capture_output=True)
        pairs = [(self.a, self.pin_a), (self.b, self.pin_b)]
        a = call(pairs); b = call(list(reversed(pairs)))
        self.assertEqual(a.returncode, 0, a.stderr+a.stdout)
        self.assertEqual(b.returncode, 0, b.stderr+b.stdout)
        self.assertEqual(json.loads(a.stdout), json.loads(b.stdout))
        single = call(pairs[:1])
        self.assertEqual(single.returncode, 0, single.stderr+single.stdout)
        self.assertEqual(json.loads(single.stdout), target.search(self.a, self.pin_a, 'تعادل'))
        failed = subprocess.run([sys.executable, '-m', 'nasuraya.history_search',
            '--archive', str(self.a), '--archive', str(self.b), '--expected-sha256', self.pin_a,
            '--query', 'تعادل'], cwd=ROOT, env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(failed.returncode, 2)
        self.assertIn('same number', failed.stderr)


if __name__ == '__main__':
    unittest.main()
