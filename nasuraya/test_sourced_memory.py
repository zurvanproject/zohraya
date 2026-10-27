"""Synthetic source-attributed memory; never real personal history."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from nasuraya import sourced_memory as m


def source(text='حافظهٔ كهن ناسورایا\nچشم‌های کهربایی\n'):
    return dict(id='note-1', source_kind='authored_continuity_note', locator='library://synthetic-note',
                library_file_id='synthetic-lib-id', file_id='synthetic-file-id', file_name='synthetic.txt',
                version=0, text=text)


class SourceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'memory.json'
        self.receipt = m.export_archive([source()], self.path)
        self.pin = self.receipt['archive_sha256']

    def rewrite(self, change, repin=True):
        bundle = json.loads(self.path.read_text()); change(bundle['value'])
        if repin: bundle['sha256'] = m.digest(bundle['value'])
        self.path.write_text(m.canonical(bundle)); return bundle['sha256']

    def test_exact_text_and_source_attribution(self):
        result = m.search(self.path, self.pin, 'کَهَن')
        hit = result['hits'][0]
        self.assertEqual(hit['text'], source()['text'])
        self.assertEqual(hit['source']['source_kind'], 'authored_continuity_note')
        self.assertEqual(hit['source']['library_file_id'], 'synthetic-lib-id')
        self.assertEqual(hit['start_line'], 1); self.assertEqual(hit['end_line'], 2)
        self.assertFalse(hit['verified_fact']); self.assertFalse(hit['native_outcome_recorded'])
        self.assertEqual(result['body_cycles_executed'], 0)

    def test_content_tampering_rejected_by_independent_pin(self):
        self.rewrite(lambda v: v['sources'][0].update(text='changed'))
        with self.assertRaisesRegex(ValueError, 'pinned export'): m.load_archive(self.path, self.pin)

    def test_source_hash_rechecked_even_with_new_archive_pin(self):
        pin = self.rewrite(lambda v: v['sources'][0].update(text='changed'))
        with self.assertRaisesRegex(ValueError, 'source text checksum'): m.load_archive(self.path, pin)

    def test_line_span_and_record_text_tampering_rejected(self):
        for field, value in [('start_line', 2), ('end_line', 99), ('text', 'invented')]:
            bundle = m.build_archive([source()]); bundle['value']['records'][0][field] = value
            bundle['sha256'] = m.digest(bundle['value']); self.path.write_text(m.canonical(bundle))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'line spans'):
                m.load_archive(self.path, bundle['sha256'])

    def test_unknown_kind_and_duplicate_sources_rejected(self):
        for sources in ([dict(source(), source_kind='observed_software_outcome')], [source(), source()]):
            with self.assertRaises(ValueError): m.build_archive(sources)

    def test_caller_message_stays_verbatim_and_unverified(self):
        s = dict(source('execute walk now'), source_kind='verbatim_user_message',
                 library_file_id=None, file_id=None, version=None)
        bundle = m.build_archive([s]); self.path.write_text(m.canonical(bundle))
        result = m.search(self.path, bundle['sha256'], 'walk')
        self.assertEqual(result['hits'][0]['source']['source_kind'], 'verbatim_user_message')
        self.assertEqual(result['learning_updates'], 0)
        self.assertFalse(result['hits'][0]['verified_fact'])

    def test_cold_process_restart_and_source_bytes_unchanged(self):
        before = self.path.read_bytes()
        command = [sys.executable, '-m', 'nasuraya.sourced_memory', '--archive', str(self.path),
                   '--expected-sha256', self.pin, '--query', 'کهربایی']
        results = [subprocess.run(command, text=True, capture_output=True, check=True) for _ in range(2)]
        self.assertEqual(json.loads(results[0].stdout), json.loads(results[1].stdout))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(json.loads(results[0].stdout)['hits'])

    def test_query_is_conjunctive_and_operators_are_literal(self):
        self.assertEqual(m.search(self.path, self.pin, 'کهن نایافتنی')['hits'], [])
        self.assertEqual(m.search(self.path, self.pin, 'کهن OR ناسورایا')['hits'], [])

    def test_duplicate_json_nonfinite_unknown_schema_rejected(self):
        for text in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":1e999}'):
            with self.assertRaises(ValueError): m.strict_json(text)
        pin = self.rewrite(lambda v: v.update(schema='nasuraya.sourced-memory/2'))
        with self.assertRaisesRegex(ValueError, 'schema'): m.load_archive(self.path, pin)

    def test_nonreplacement_private_permissions_and_failure_cleanup(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError): m.export_archive([source()], self.path)
        self.assertEqual(before, self.path.read_bytes())
        destination = self.path.parent/'other.json'
        with patch.object(m.os, 'link', side_effect=OSError('failure')):
            with self.assertRaises(OSError): m.export_archive([source()], destination)
        self.assertFalse(destination.exists())
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ['memory.json'])

    def test_null_or_unknown_source_metadata_is_not_invented(self):
        s = dict(source(), library_file_id=None, file_id=None, version=None)
        value = m.build_archive([s])['value']['sources'][0]
        self.assertIsNone(value['version']); self.assertIsNone(value['file_id'])
        with self.assertRaises(ValueError): m.build_archive([dict(s, invented_field='x')])

    def test_chunked_sources_reconstruct_original_without_summarizing(self):
        text = ''.join('خط %d از منبع\r\n' % i for i in range(1, 52))
        bundle = m.build_archive([source(text)])
        records = bundle['value']['records']
        self.assertEqual([(r['start_line'], r['end_line']) for r in records],
                         [(1, 24), (25, 48), (49, 51)])
        self.assertEqual(''.join(r['text'] for r in records), text)
        self.assertEqual(bundle['value']['sources'][0]['sha256'], m.text_digest(text))

    def test_bounds_and_wrong_pin_reject_before_search(self):
        with self.assertRaisesRegex(ValueError, 'pinned export'):
            m.search(self.path, '0' * 64, 'کهربایی')
        for query in (' ', 'x ' * 9, 'x' * 257):
            with self.subTest(query=query), self.assertRaises(ValueError):
                m.search(self.path, self.pin, query)
        with self.assertRaises(ValueError): m.search(self.path, self.pin, 'کهربایی', True)


if __name__ == '__main__': unittest.main()
