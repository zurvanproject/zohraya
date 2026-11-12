"""Open-set regression/guardrail checks; no numeric claim based on a test leak."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from examples.tadash_interoception.sensory import trial
from .experiment import preflight, calibrate_to, evaluate_to, final_episode
from .open_set import (ALPHA, CALIBRATION_SEEDS, MODEL_SHA, SelectiveDecoder,
                       calibrate, frozen_decoder, known_rows, Selection, decide)


class OpenSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = frozen_decoder()
        cls.frozen = calibrate(cls.base)
        cls.gate = SelectiveDecoder(cls.base, cls.frozen)

    def test_exact_frozen_decoder(self):
        self.assertEqual(self.base.fingerprint(), MODEL_SHA)
        self.assertEqual(len(self.base.examples), 392)

    def test_no_novel_calibration_and_no_seed_overlap(self):
        preflight()
        rows = known_rows(CALIBRATION_SEEDS)
        self.assertEqual(len(rows), 640)
        self.assertTrue(all(r['truth']['type'] != 'compound' for r in rows))

    def test_numeric_only_api(self):
        features = known_rows(range(810000,810004))[0]['features']
        with self.assertRaises(TypeError): self.gate.infer(features, truth={'type':'compound'})
        with self.assertRaises(ValueError): self.gate.infer({'features': features})

    def test_immutable_decoder_and_calibration_tamper_detection(self):
        before = self.base.fingerprint()
        self.gate.infer(known_rows(range(810000,810004))[0]['features'])
        self.assertEqual(before, self.base.fingerprint())
        bad = dict(self.frozen)
        bad['alpha'] = .01
        with self.assertRaises(ValueError): SelectiveDecoder(self.base, bad)

    def test_abstention_yields_observe_only(self):
        a = Selection(True, 'unknown', 'unknown', True, 'out_of_known_support', .01, .99, False)
        self.assertEqual(decide(a), 'observe')
        self.assertEqual(decide(Selection(False, 'none','none',False,'quiet',None,1.,False)), 'continue')

    def test_reproducible_known_fit(self):
        self.assertEqual(self.frozen, calibrate(self.base))

    def test_heldout_generation_is_repeatable(self):
        for seed in (850000,850504,850650):
            self.assertEqual(final_episode(seed), final_episode(seed))

    def test_frozen_pipeline_reproduces_all_records(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            calibrate_to(p/'fit')
            a=evaluate_to(p/'fit'/'calibration.json', p/'a')
            b=evaluate_to(p/'fit'/'calibration.json', p/'b')
            self.assertEqual(a,b)
            self.assertEqual((p/'a'/'events.jsonl').read_bytes(), (p/'b'/'events.jsonl').read_bytes())
            self.assertEqual(a['model_sha'], MODEL_SHA)
            self.assertEqual(a['n'], 700)
            self.assertEqual(a['metrics']['unknown'], 200)
            self.assertEqual(a['metrics']['none'], 200)
            self.assertEqual(a['metrics']['known'], 300)


if __name__ == '__main__': unittest.main()
