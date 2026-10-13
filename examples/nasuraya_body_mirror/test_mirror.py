"""Regenerate finite native samples and compare the committed replay data."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from .build import build
from .export import extract_run, export, ROOT


class MirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.runs = Path(cls.temp.name) / 'runs'
        for fixture in ('normal', 'sleep'):
            subprocess.run([sys.executable, '-m', 'examples.nasuraya_body_loop', 'demo',
                            '--fixture', fixture, '--steps', '12', '--max-actions', '12',
                            '--duration-s', '1', '--output-dir', str(cls.runs / fixture)],
                           cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.generated = export(cls.runs, Path(cls.temp.name) / 'fresh.json')
        cls.stored = json.loads((Path(__file__).parent / 'frames.json').read_text())

    def test_all_24_committed_samples_match_new_source_pinned_body_execution(self):
        self.assertEqual(self.stored['runtime_manifest_sha256'],
                         sha256((ROOT / 'runtimes/tadash_body/PUBLIC_FILES_SHA256.json').read_bytes()).hexdigest())
        self.assertEqual(self.stored['design'], self.generated['design'])
        for fixture in ('normal', 'sleep'):
            expected = self.generated['scenarios'][fixture]['frames']
            self.assertEqual(len(expected), 12)
            # Historical full envelopes were intentionally not published.
            # Compare every displayed value; validate fresh envelope hashes in
            # extract_run rather than claiming byte-identical historical state.
            stored = self.stored['scenarios'][fixture]['frames']
            for frame in stored + expected:
                self.assertRegex(frame['checkpoint_sha256'], r'^[0-9a-f]{64}$')
            public_values = lambda frames: [{k: v for k, v in frame.items()
                                            if k != 'checkpoint_sha256'} for frame in frames]
            self.assertEqual(public_values(stored), public_values(expected))
        self.assertGreater(self.generated['scenarios']['normal']['frames'][-1]['walk_steps'], 0)
        sleep = self.generated['scenarios']['sleep']['frames']
        self.assertEqual((sleep[0]['requested'], sleep[0]['actual']), ('walk', 'protect'))
        self.assertEqual((sleep[1]['requested'], sleep[1]['actual']), ('observe', 'observe'))
        self.assertGreater(sleep[1]['recalled'], 0)

    def test_tampered_checkpoint_and_receipt_are_rejected(self):
        folder = Path(self.temp.name) / 'tampered'
        shutil.copytree(self.runs / 'normal', folder)
        original = json.loads((folder / 'decisions.json').read_text())
        changed = deepcopy(original)
        changed['decisions'][0]['actual_outcome']['body_checkpoint']['sha256'] = '0' * 64
        (folder / 'decisions.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): extract_run(folder, 'normal')
        (folder / 'decisions.json').write_text(json.dumps(original))
        events = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
        events[0]['outcome']['decision_id'] = 'wrong'
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
        with self.assertRaisesRegex(ValueError, 'disagree'): extract_run(folder, 'normal')

    def test_html_build_embeds_exact_frames_in_one_non_executable_json_slot(self):
        destination = Path(self.temp.name) / 'mirror.html'
        build(destination)
        html = destination.read_text()
        self.assertNotIn('__MIRROR_DATA__', html)
        slot = re.findall(r'<script type="application/json" id="nm-data">(.*?)</script>', html, re.S)
        self.assertEqual(len(slot), 1)
        self.assertEqual(json.loads(slot[0]), self.stored)


if __name__ == '__main__': unittest.main()
