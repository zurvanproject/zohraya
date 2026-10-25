from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .history import demo
from .pinned_head import load, pin, verify_pinned_json
from .test_history import rehash
from .test_trusted_head import TRUSTED_HEAD
from .traits import BODY, ROOT


class PinnedHeadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.anchor = self.directory / 'trusted-head.json'
        self.command = [sys.executable, '-m', 'examples.nasuraya_genome.pinned_head']

    def test_pins_private_reference_without_allowing_replacement(self):
        self.assertEqual(pin(self.anchor, trusted_head_sha256=TRUSTED_HEAD), TRUSTED_HEAD)
        self.assertEqual(load(self.anchor), TRUSTED_HEAD)
        self.assertEqual(self.anchor.stat().st_mode & 0o077, 0)
        before = self.anchor.read_bytes()
        for head in (TRUSTED_HEAD, '0' * 64):
            with self.assertRaises(FileExistsError):
                pin(self.anchor, trusted_head_sha256=head)
            self.assertEqual(self.anchor.read_bytes(), before)
        self.assertEqual(list(self.directory.iterdir()), [self.anchor])

    def test_invalid_explicit_heads_create_nothing(self):
        for head in (None, True, 0, '', 'bad', 'g' * 64, 'a' * 63, TRUSTED_HEAD.upper()):
            with self.subTest(head=head), self.assertRaises(ValueError):
                pin(self.anchor, trusted_head_sha256=head)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_strict_anchor_schema_and_duplicate_keys(self):
        pin(self.anchor, trusted_head_sha256=TRUSTED_HEAD)
        valid = self.anchor.read_text()
        cases = [valid.replace('"head_sha256":', '"head_sha256":"discarded","head_sha256":'),
                 valid.replace('"head_sha256":', '"\\u0068ead_sha256":"discarded","head_sha256":')]
        for field, value in (('schema', 'nasuraya.genome.pinned-head/2'),
                             ('history_schema', 'nasuraya.genome.proposal-history/2'),
                             ('head_sha256', False), ('approval', True)):
            record = json.loads(valid)
            record[field] = value
            cases.append(json.dumps(record))
        for raw in cases:
            self.anchor.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                load(self.anchor)

    def test_missing_or_corrupt_reference_never_falls_back_to_internal_integrity(self):
        raw = json.dumps(demo())
        with self.assertRaises(FileNotFoundError):
            verify_pinned_json(raw, anchor_path=self.anchor)
        for content in ('', '{', 'null', '{}'):
            self.anchor.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                verify_pinned_json(raw, anchor_path=self.anchor)
            self.assertEqual(self.anchor.read_text(), content)

    def test_pin_and_verify_survive_separate_processes_and_reject_rollback(self):
        subprocess.run(self.command + ['pin', '--anchor', str(self.anchor), '--head', TRUSTED_HEAD],
                       cwd=ROOT, check=True, capture_output=True, text=True)
        history = self.directory / 'candidate.json'
        saved = demo()
        history.write_text(json.dumps(saved))
        original = self.anchor.read_bytes()
        command = self.command + ['verify', '--anchor', str(self.anchor), '--history', str(history)]
        result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['revision'], 2)
        self.assertIs(receipt['trusted_head_matched'], True)
        self.assertIs(receipt['native_apply_allowed'], False)
        saved['payload']['events'].pop()
        history.write_text(json.dumps(rehash(saved)))
        candidate_before = history.read_bytes()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('trusted head', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(self.anchor.read_bytes(), original)
        self.assertEqual(history.read_bytes(), candidate_before)
        self.anchor.unlink()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertFalse(self.anchor.exists())

    def test_native_destinations_and_existing_symlinks_are_preserved(self):
        forbidden = BODY / 'pinned-reference-forbidden-test.json'
        self.assertFalse(forbidden.exists())
        alias = self.directory / 'body-alias'
        alias.symlink_to(BODY, target_is_directory=True)
        for path in (forbidden, alias / forbidden.name):
            with self.assertRaisesRegex(ValueError, 'native runtime'):
                pin(path, trusted_head_sha256=TRUSTED_HEAD)
        self.assertFalse(forbidden.exists())
        existing = self.directory / 'existing.txt'
        existing.write_text('preserve me')
        self.anchor.symlink_to(existing)
        with self.assertRaises(FileExistsError):
            pin(self.anchor, trusted_head_sha256=TRUSTED_HEAD)
        self.assertTrue(self.anchor.is_symlink())
        self.assertEqual(existing.read_text(), 'preserve me')

    def test_competing_initializers_publish_exactly_one_complete_reference(self):
        processes = [subprocess.Popen(self.command + ['pin', '--anchor', str(self.anchor), '--head', head],
                                      cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for head in (TRUSTED_HEAD, '0' * 64)]
        results = [(process.communicate(timeout=20), process.returncode) for process in processes]
        winners = [json.loads(out) for (out, err), code in results if code == 0]
        self.assertEqual(len(winners), 1)
        self.assertEqual(sum(code != 0 for _, code in results), 1)
        self.assertEqual(load(self.anchor), winners[0]['head_sha256'])
        self.assertEqual(list(self.directory.iterdir()), [self.anchor])

    def test_failure_before_publication_leaves_no_partial_reference(self):
        for operation in ('os.link', 'os.fsync'):
            with self.subTest(operation=operation), patch(
                    'examples.nasuraya_genome.pinned_head.' + operation,
                    side_effect=OSError('injected storage failure')):
                with self.assertRaises(OSError):
                    pin(self.anchor, trusted_head_sha256=TRUSTED_HEAD)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_verification_does_not_change_body_or_either_input(self):
        def snapshot():
            return {str(p.relative_to(BODY)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in BODY.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        before = snapshot()
        sys.path.insert(0, str(BODY))
        try:
            import unified_body_v2
            from posture_step import PostureLoop
            body = PostureLoop()
            state = deepcopy(body.checkpoint())
            pin(self.anchor, trusted_head_sha256=TRUSTED_HEAD)
            reference = self.anchor.read_bytes()
            raw = json.dumps(demo())
            self.assertIs(verify_pinned_json(raw, anchor_path=self.anchor)['native_apply_allowed'], False)
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                verify_pinned_json('{"sha256":"discarded",' + raw[1:], anchor_path=self.anchor)
            self.assertEqual(self.anchor.read_bytes(), reference)
            self.assertEqual(body.checkpoint(), state)
            self.assertEqual(snapshot(), before)
        finally:
            sys.path.remove(str(BODY))

    def test_post_publication_sync_failure_requires_inspection_not_replacement(self):
        with patch('examples.nasuraya_genome.pinned_head.os.fsync',
                   side_effect=[None, OSError('directory sync failed')]):
            with self.assertRaises(OSError):
                pin(self.anchor, trusted_head_sha256=TRUSTED_HEAD)
        self.assertEqual(load(self.anchor), TRUSTED_HEAD)
        before = self.anchor.read_bytes()
        with self.assertRaises(FileExistsError):
            pin(self.anchor, trusted_head_sha256='0' * 64)
        self.assertEqual(self.anchor.read_bytes(), before)
        self.assertEqual(list(self.directory.iterdir()), [self.anchor])


if __name__ == '__main__':
    unittest.main()
