import tempfile
import unittest
import wave
from pathlib import Path
from setar_practice import plan_events, practice, render_audio, target_frequency


class SetarPracticeTests(unittest.TestCase):
    def test_microtone_is_halfway_between_e_flat_and_e(self):
        # E koron from C: 350 cents, halfway between Eb (+300) and E (+400).
        import math
        self.assertAlmostEqual(1200 * math.log2(target_frequency(3.5) / target_frequency(3)), 50, places=6)

    def test_stroke_alternation(self):
        strokes = [e['right_index_stroke'] for e in plan_events()]
        self.assertTrue(all(a != b for a, b in zip(strokes, strokes[1:])))

    def test_three_pass_feedback_reduces_error(self):
        report = practice()
        self.assertEqual([x['pass'] for x in report['passes']], [1, 2, 3])
        initial = report['passes'][0]['metrics']
        last = report['passes'][-1]['metrics']
        for name in ('onset_mae_ms', 'intonation_mae_cents', 'attack_mae'):
            self.assertLess(last[name], initial[name], name)

    def test_render_audio_nonempty(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'one.wav'
            render_audio(practice(), out)
            with wave.open(str(out), 'rb') as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getframerate(), 22050)
                self.assertGreater(w.getnframes(), 22050 * 10)
            self.assertGreater(out.stat().st_size, 44100)


if __name__ == '__main__':
    unittest.main()
