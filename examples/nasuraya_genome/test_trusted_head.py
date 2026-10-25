from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .chromosomes import digest
from .history import append, create, demo, verify, verify_json
from .test_history import edit, rehash
from .traits import BODY, ROOT


# Fixed before the implementation; obtained from the unchanged #66 demonstration.
TRUSTED_HEAD = '02d534bbbd1ec3204eb848b0ccaa4f16bb4edbfb6cc889d717cc9091680eb455'


class TrustedHeadTests(unittest.TestCase):
    def test_matching_anchor_preserves_legacy_history_and_genotype(self):
        saved = demo()
        before = json.dumps(saved, sort_keys=True)
        self.assertEqual(saved['payload']['head_sha256'], TRUSTED_HEAD)
        self.assertEqual(digest(verify_json(before, expected_head_sha256=TRUSTED_HEAD)),
                         '22dd3ac68a1542f1da285b45444a8e90412e58af7b75486343b4d3488ed0c52e')
        self.assertEqual(verify(saved, expected_head_sha256=TRUSTED_HEAD), verify(saved))
        self.assertEqual(json.dumps(saved, sort_keys=True), before)
        root = create()
        self.assertEqual(verify(root, expected_head_sha256=root['payload']['head_sha256'])['revision'], 0)

    def test_valid_shortened_prefixes_are_rejected_against_the_trusted_head(self):
        for length in (0, 1):
            saved = demo()
            del saved['payload']['events'][length:]
            rehash(saved)
            raw = json.dumps(saved)
            self.assertEqual(verify_json(raw)['revision'], length)
            with self.subTest(length=length), self.assertRaisesRegex(ValueError, 'trusted head'):
                verify_json(raw, expected_head_sha256=TRUSTED_HEAD)
            self.assertEqual(json.dumps(saved), raw)

    def test_coherent_reason_rewrite_is_rejected_even_with_identical_genotype(self):
        saved = demo()
        saved['payload']['events'][0]['payload']['reason'] = 'Coherently rewritten declared reason'
        rehash(saved)
        self.assertEqual(digest(verify(saved)), digest(verify(demo())))
        with self.assertRaisesRegex(ValueError, 'trusted head'):
            verify(saved, expected_head_sha256=TRUSTED_HEAD)

    def test_same_revision_fork_and_unaccepted_extension_are_rejected(self):
        fork = create()
        for value in (1.01, 1.02):
            fork = append(fork, [edit(value)], reason='Different valid proposal branch',
                          expected_head_sha256=fork['payload']['head_sha256'])
        current = demo()
        extension = append(current, [edit(1.01)], reason='Not yet accepted by the host',
                           expected_head_sha256=TRUSTED_HEAD)
        self.assertEqual(verify(fork)['revision'], verify(current)['revision'])
        self.assertEqual(verify(extension)['revision'], 3)
        for saved in (fork, extension):
            with self.subTest(revision=verify(saved)['revision']), self.assertRaisesRegex(ValueError, 'trusted head'):
                verify(saved, expected_head_sha256=TRUSTED_HEAD)

    def test_invalid_anchor_values_are_not_silently_ignored(self):
        raw = json.dumps(demo())
        for value in ('', True, 0, [], {}, 'a' * 63, 'a' * 65, 'g' * 64, TRUSTED_HEAD.upper(),
                      ' ' + TRUSTED_HEAD, TRUSTED_HEAD + '\n'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'expected_head_sha256'):
                verify_json(raw, expected_head_sha256=value)

    def test_matching_anchor_never_bypasses_strict_json_or_replay(self):
        raw = json.dumps(demo())
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            verify_json('{"sha256":"discarded",' + raw[1:], expected_head_sha256=TRUSTED_HEAD)
        saved = demo()
        saved['payload']['events'][0]['payload']['result']['payload']['phenotype']['compatibility']['native_apply_allowed'] = 0
        saved['sha256'] = digest(saved['payload'])
        with self.assertRaises(ValueError):
            verify(saved, expected_head_sha256=TRUSTED_HEAD)

    def test_cli_reports_verification_scope_and_never_overwrites_input(self):
        command = [sys.executable, '-m', 'examples.nasuraya_genome.history']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            path.write_text(json.dumps(demo()), encoding='utf-8')
            before = path.read_bytes()
            for options, anchored in (([], False), (['--expected-head-sha256', TRUSTED_HEAD], True)):
                result = subprocess.run(command + ['--verify', str(path)] + options,
                                        cwd=ROOT, capture_output=True, text=True, check=True)
                receipt = json.loads(result.stdout)
                self.assertIs(receipt['trusted_head_matched'], anchored)
                self.assertEqual(receipt['head_sha256'], TRUSTED_HEAD)
                self.assertIs(receipt['native_apply_allowed'], False)
            for anchor in ('0' * 64, '', 'bad'):
                result = subprocess.run(command + ['--verify', str(path), '--expected-head-sha256', anchor],
                                        cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
            self.assertEqual(path.read_bytes(), before)
            output = Path(tmp) / 'must-not-be-created.json'
            result = subprocess.run(command + ['--demo-output', str(output), '--expected-head-sha256', TRUSTED_HEAD],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_anchored_success_and_failure_leave_body_and_files_unchanged(self):
        def snapshot():
            return {str(p.relative_to(BODY)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in BODY.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

        before = snapshot()
        sys.path.insert(0, str(BODY))
        try:
            import unified_body_v2
            from posture_step import PostureLoop
            body = PostureLoop()  # Synthetic, no live ledger is opened.
            state = deepcopy(body.checkpoint())
            saved = demo()
            original = deepcopy(saved)
            verify(saved, expected_head_sha256=TRUSTED_HEAD)
            with self.assertRaises(ValueError):
                verify(saved, expected_head_sha256='0' * 64)
            self.assertEqual(saved, original)
            self.assertEqual(body.checkpoint(), state)
            self.assertEqual(snapshot(), before)
        finally:
            sys.path.remove(str(BODY))


if __name__ == '__main__':
    unittest.main()
