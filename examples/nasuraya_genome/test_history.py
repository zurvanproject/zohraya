from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .chromosomes import digest
from .history import append, create, demo, verify
from .traits import BODY, ROOT, baseline, checkpoint, express, mutate


def edit(value=1.02):
    return dict(chromosome='P09A', locus='P09.L010', value=value)


def add(history, value=1.02):
    return append(history, [edit(value)], reason='Synthetic proposal',
                  expected_head_sha256=history['payload']['head_sha256'])


def rehash(history):
    """Rehash every link to test semantic replay, not only checksum detection."""
    p = history['payload']
    head = p['root']['sha256']
    for record in p['events']:
        record['payload']['parent_event_sha256'] = head
        record['sha256'] = digest(record['payload'])
        head = record['sha256']
    p['head_sha256'] = head
    history['sha256'] = digest(p)
    return history


class HistoryTests(unittest.TestCase):
    def test_replays_exact_genotype_and_protects_external_layers(self):
        start = create()
        history = demo()
        expected = mutate(baseline(), [edit()], expected_revision=0)
        expected = mutate(expected, [dict(chromosome='P08B', locus='P08.L010', value=5.)],
                          expected_revision=1)
        self.assertEqual(verify(history), expected)
        before, after = express(baseline()), express(expected)
        for key in ('identity_and_face', 'learned_layer', 'native_baseline'):
            self.assertEqual(before[key], after[key])
        self.assertFalse(after['compatibility']['native_apply_allowed'])
        self.assertEqual(start, create())

    def test_same_revision_foreign_head_cannot_append(self):
        left, right = add(create(), 1.01), add(create(), 1.02)
        self.assertEqual(verify(left)['revision'], verify(right)['revision'])
        before = deepcopy(left)
        with self.assertRaisesRegex(ValueError, 'foreign'):
            append(left, [edit()], reason='Test',
                   expected_head_sha256=right['payload']['head_sha256'])
        self.assertEqual(left, before)

    def test_invalid_reason_or_edit_is_atomic(self):
        history = create()
        before = deepcopy(history)
        for reason in ('', '   ', None, True):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                append(history, [edit()], reason=reason,
                       expected_head_sha256=history['payload']['head_sha256'])
        with self.assertRaises(ValueError):
            add(history, 10.)
        self.assertEqual(history, before)

    def test_rehashed_changed_edits_and_forged_result_are_rejected(self):
        for target in ('edits', 'result', 'parent'):
            history = demo()
            e = history['payload']['events'][0]['payload']
            if target == 'edits':
                e['edits'][0]['value'] = 1.01
            elif target == 'parent':
                e['parent_genotype_sha256'] = '0' * 64
            else:
                e['result']['payload']['phenotype']['compatibility']['native_apply_allowed'] = True
                e['result']['sha256'] = digest(e['result']['payload'])
            with self.subTest(target=target), self.assertRaises(ValueError):
                verify(rehash(history))

    def test_rehashed_omission_reorder_and_duplicate_are_rejected(self):
        for target in ('omit', 'reverse', 'duplicate'):
            history = demo()
            events = history['payload']['events']
            if target == 'omit':
                del events[0]
            elif target == 'reverse':
                events.reverse()
            else:
                events.insert(1, deepcopy(events[0]))
            with self.subTest(target=target), self.assertRaises(ValueError):
                verify(rehash(history))

    def test_arbitrary_root_and_extra_fields_are_rejected(self):
        history = create()
        history['payload']['root'] = checkpoint(mutate(baseline(), [edit()], expected_revision=0))
        with self.assertRaisesRegex(ValueError, 'root'):
            verify(rehash(history))
        history = demo()
        history['payload']['events'][0]['payload']['user_approval'] = True
        with self.assertRaises(ValueError):
            verify(rehash(history))

    def test_result_copy_cannot_mutate_history_and_checksum_is_checked(self):
        history = demo()
        saved = deepcopy(history)
        verify(history)['chromosomes'].clear()
        self.assertEqual(history, saved)
        history['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify(history)

    def test_file_roundtrip_in_fresh_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            command = [sys.executable, '-m', 'examples.nasuraya_genome.history']
            subprocess.run(command + ['--demo-output', str(path)], cwd=ROOT, check=True)
            completed = subprocess.run(command + ['--verify', str(path)], cwd=ROOT,
                                       check=True, capture_output=True, text=True)
            result = json.loads(completed.stdout)
            self.assertEqual(result['revision'], 2)
            self.assertEqual(result['events'], 2)
            self.assertEqual(result['genotype_sha256'], digest(verify(demo())))
            self.assertFalse(result['native_apply_allowed'])
            forbidden = BODY / 'genome-history-forbidden-test.json'
            self.assertFalse(forbidden.exists())
            rejected = subprocess.run(command + ['--demo-output', str(forbidden)], cwd=ROOT,
                                      capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('native runtime destinations are forbidden', rejected.stderr)
            self.assertFalse(forbidden.exists())
            original = path.read_bytes()
            duplicate = subprocess.run(command + ['--demo-output', str(path)], cwd=ROOT,
                                       capture_output=True, text=True)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
