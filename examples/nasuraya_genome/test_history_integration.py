"""Main integration: old format, external boundaries and native isolation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .chromosomes import digest
from .history import append, demo, verify_json
from .test_history import edit, rehash
from .traits import BODY, ROOT, body_sources


class HistoryIntegrationTests(unittest.TestCase):
    def test_pr66_format_and_digest_remain_compatible(self):
        # Generated with history.py at 1e6b36ba45c9046b0ceef4fd44441fc1151994f8.
        saved = demo()
        self.assertEqual(saved['sha256'],
                         '47c1e940018cd07fd6662e22edd0ec93786f0a58867622e04fd1c94937301067')
        genotype = verify_json(json.dumps(saved))
        self.assertEqual(digest(genotype),
                         '22dd3ac68a1542f1da285b45444a8e90412e58af7b75486343b4d3488ed0c52e')
        self.assertEqual(genotype['version'], '0.1.0')

    def test_unknown_versions_fail_closed_after_rehashing(self):
        for target in ('history', 'root_checkpoint', 'root_genotype',
                       'result_checkpoint', 'result_genotype'):
            saved = demo()
            if target == 'history':
                saved['payload']['schema'] = 'nasuraya.genome.proposal-history/2'
            else:
                checkpoint = (saved['payload']['root'] if target.startswith('root')
                              else saved['payload']['events'][0]['payload']['result'])
                record = checkpoint['payload']
                if target.endswith('genotype'):
                    record = record['genotype']
                record['version'] = '0.2.0'
                checkpoint['sha256'] = digest(checkpoint['payload'])
            rehash(saved)
            raw = json.dumps(saved)
            with self.subTest(target=target), self.assertRaises(ValueError):
                verify_json(raw)
            self.assertEqual(json.dumps(saved), raw)

    def test_cli_rejects_nested_ambiguity_and_typed_results_without_writes(self):
        saved = demo()
        valid = json.dumps(saved)
        cases = {
            'nested_duplicate': valid.replace('"reason":', '"reason":"discarded","reason":', 1),
            'escaped_duplicate': valid.replace('"reason":', '"\\u0072eason":"discarded","reason":', 1),
        }
        for field in ('permission', 'allele'):
            bad = deepcopy(saved)
            result = bad['payload']['events'][0]['payload']['result']
            if field == 'permission':
                result['payload']['phenotype']['compatibility']['native_apply_allowed'] = 0
            else:
                result['payload']['genotype']['chromosomes']['P01A']['P01.L000'] = True
            result['sha256'] = digest(result['payload'])
            cases[field] = json.dumps(rehash(bad))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            for name, raw in cases.items():
                path.write_text(raw, encoding='utf-8')
                before = path.read_bytes()
                result = subprocess.run(
                    [sys.executable, '-m', 'examples.nasuraya_genome.history', '--verify', str(path)],
                    cwd=ROOT, capture_output=True, text=True)
                with self.subTest(case=name):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('duplicate JSON key' if 'duplicate' in name else 'result', result.stderr)
                    self.assertEqual(path.read_bytes(), before)

    def test_source_drift_rejects_history_without_migration(self):
        raw = json.dumps(demo())
        phenotype, contact = body_sources()
        contact['mass_kg'] += 1
        with patch('examples.nasuraya_genome.traits.body_sources', return_value=(phenotype, contact)):
            with self.assertRaisesRegex(ValueError, 'drift'):
                verify_json(raw)

    def test_history_success_and_failure_do_not_change_native_state(self):
        def snapshot():
            return {str(p.relative_to(BODY)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in BODY.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

        files_before = snapshot()
        sys.path.insert(0, str(BODY))
        try:
            import unified_body_v2  # Retained native import-path bootstrap.
            from posture_step import PostureLoop
            body = PostureLoop()  # Fresh synthetic body; no live ledger is opened.
            state_before = deepcopy(body.checkpoint())
            saved = demo()
            original = deepcopy(saved)
            candidate = append(saved, [edit(1.01)], reason='Integration test proposal',
                               expected_head_sha256=saved['payload']['head_sha256'])
            verify_json(json.dumps(candidate))
            with self.assertRaises(ValueError):
                verify_json('{"sha256":"discarded",' + json.dumps(saved)[1:])
            with self.assertRaises(ValueError):
                append(saved, [edit(1.02)], reason='Stale proposal', expected_head_sha256='0' * 64)
            self.assertEqual(saved, original)
            self.assertIs(candidate['payload']['events'][-1]['payload']['result']['payload']
                          ['phenotype']['compatibility']['native_apply_allowed'], False)
            self.assertEqual(body.checkpoint(), state_before)
            self.assertEqual(snapshot(), files_before)
        finally:
            sys.path.remove(str(BODY))


if __name__ == '__main__':
    unittest.main()
