from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .chromosomes import digest
from .history import demo, verify, verify_json
from .strict_json import loads
from .traits import ROOT


def rehash_outer(history):
    """Rehash enclosing events while retaining the corrupted result checkpoint."""
    payload = history['payload']
    head = payload['root']['sha256']
    for event in payload['events']:
        event['payload']['parent_event_sha256'] = head
        event['sha256'] = digest(event['payload'])
        head = event['sha256']
    payload['head_sha256'] = head
    history['sha256'] = digest(payload)
    return history


class StrictHistoryTests(unittest.TestCase):
    def test_valid_json_preserves_genotype_and_input(self):
        saved = demo()
        raw = json.dumps(saved, ensure_ascii=False)
        before = deepcopy(saved)
        self.assertEqual(digest(verify_json(raw)), digest(verify(saved)))
        self.assertEqual(saved, before)

    def test_duplicate_checksum_cannot_be_silently_overwritten(self):
        raw = json.dumps(demo())
        ambiguous = '{"sha256":"wrong",' + raw[1:]
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            verify_json(ambiguous)

    def test_duplicate_nested_and_escaped_keys_are_rejected(self):
        for raw in ('{"a":{"value":2,"value":1}}',
                    '{"value":1,"value":1}',
                    '{"value":1,"\\u0076alue":2}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                loads(raw)

    def test_nonfinite_tokens_and_overflow_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e9999', '-1e9999'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'non-finite'):
                loads('{"value":' + value + '}')

    def test_valid_json_types_and_distinct_unicode_keys_are_preserved(self):
        decoded = loads('{"a":false,"b":0,"c":1.0,"d":1,"e":"۱","é":2,"é":3}')
        self.assertIs(type(decoded['a']), bool)
        self.assertIs(type(decoded['b']), int)
        self.assertIs(type(decoded['c']), float)
        self.assertIs(type(decoded['d']), int)
        self.assertEqual((decoded['é'], decoded['é']), (2, 3))

    def test_rehashed_boolean_numeric_result_corruption_is_rejected(self):
        for field in ('permission', 'allele', 'revision', 'integer_to_float'):
            saved = demo()
            result = saved['payload']['events'][0]['payload']['result']['payload']
            if field == 'permission':
                result['phenotype']['compatibility']['native_apply_allowed'] = 0
            elif field == 'allele':
                result['genotype']['chromosomes']['P01A']['P01.L000'] = True
            elif field == 'revision':
                result['genotype']['revision'] = True
            else:
                result['genotype']['chromosomes']['P01A']['P01.L000'] = 1.0
            rehash_outer(saved)
            before = deepcopy(saved)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'result'):
                verify(saved)
            self.assertEqual(saved, before)

    def test_recomputed_nested_hash_does_not_approve_wrong_type(self):
        saved = demo()
        result = saved['payload']['events'][0]['payload']['result']
        result['payload']['genotype']['chromosomes']['P01A']['P01.L000'] = True
        result['sha256'] = digest(result['payload'])
        rehash_outer(saved)
        with self.assertRaisesRegex(ValueError, 'result'):
            verify(saved)

    def test_fresh_process_cli_rejects_duplicate_and_keeps_file(self):
        raw = '{"sha256":"wrong",' + json.dumps(demo())[1:]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'duplicate-history.json'
            path.write_text(raw, encoding='utf-8')
            before = path.read_bytes()
            proc = subprocess.run([sys.executable, '-m', 'examples.nasuraya_genome.history',
                                   '--verify', str(path)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('duplicate JSON key', proc.stderr)
            self.assertEqual(proc.stdout, '')
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
