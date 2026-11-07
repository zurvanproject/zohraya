import unittest

import numpy as np

from .__main__ import OVERLAP, SR, WINDOW, analyze


class AuditoryIntegrationTest(unittest.TestCase):
    def test_overlap_raw_results_and_independent_resonan_clock(self):
        n = 2 * WINDOW - OVERLAP + 1
        x = np.arange(n, dtype=np.float32) / n
        calls = []

        def decoder(chunk):
            calls.append(chunk.copy())
            return " woord "  # Stands for raw decoder output, including spacing.

        report = analyze(x, decoder)
        windows = report["windows"]
        self.assertEqual([w["end_sample"] for w in windows], [WINDOW, n - 1, n])
        self.assertEqual(windows[-1]["lexical_status"], "unverified")
        self.assertEqual([w["text"] for w in windows], [" woord "] * 3)
        for i, (chunk, window) in enumerate(zip(calls, windows)):
            start = window["start_sample"]
            np.testing.assert_array_equal(chunk, x[start:window["end_sample"]].astype("<f4"))
            if i:
                self.assertEqual(windows[i - 1]["end_sample"] - start, OVERLAP)
        events = report["resonan_events"]
        self.assertEqual([e["time_s"] for e in events], list(range((n + SR - 1) // SR)))
        self.assertTrue(all(e["content_kind"] == "music" for e in events))
        self.assertTrue(all(e["schema"] == "nasuraya_auditory_resonan_v26_event" for e in events))

    def test_complete_window_no_redundant_tail(self):
        report = analyze(np.zeros(WINDOW, np.float32), lambda chunk: "")
        self.assertEqual(len(report["windows"]), 1)

    def test_silence_keeps_hallucination_for_review(self):
        report = analyze(np.zeros(SR, np.float32), lambda chunk: "sample")
        window, = report["windows"]
        self.assertEqual(window["text"], "sample")
        self.assertIsNone(window["hypothesis"])
        self.assertEqual(window["lexical_status"], "below_pcm16_floor")

    def test_short_audio_empty_asr_is_not_a_hypothesis(self):
        report = analyze(np.full(81, .1, np.float32), lambda chunk: "")
        window, = report["windows"]
        self.assertEqual(window["lexical_status"], "empty")
        self.assertIsNone(window["hypothesis"])
        self.assertEqual(report["resonan_events"][0]["duration_s"], round(81 / SR, 3))

    def test_invalid_input_never_reaches_decoder(self):
        for data in ([], [float("nan")], [[0.1]]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                analyze(data, lambda chunk: self.fail("unexpected decode"))
