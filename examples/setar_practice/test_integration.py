"""Offline checkpoint, sensor and bounded-continuation contract tests."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from examples.setar_practice import engine as e
from examples.setar_practice.skill import SetarSkill, checkpoint, read_controller, sha, validate_controller


class SetarIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.skill = SetarSkill()

    def test_bundled_seed_and_count(self):
        status = self.skill.status()
        self.assertEqual(status['total_updates'], 2860)
        self.assertEqual(status['new_updates'], 0)
        self.assertEqual(status['calibration_nodes'], 18)

    def test_exact_calibration_retained(self):
        raw = json.loads(self.skill.parent.read_text())
        for name in ('pitch_cents', 'timing_s', 'attack_gain'):
            self.assertEqual(getattr(self.skill.controller, name), raw[name])

    def test_known_node_and_unseen_target(self):
        ctl = self.skill.controller
        self.assertEqual(ctl.correction(1, 2.), (ctl.pitch_cents['1:2'], 'measured_node'))
        self.assertEqual(ctl.correction(1, 6.5)[1], 'interpolated_unmeasured_target')

    def test_outside_range_not_extrapolated(self):
        self.assertEqual(self.skill.controller.correction(1, 12.), (0., 'outside_calibrated_range'))

    def test_evaluation_read_only(self):
        original = asdict(self.skill.controller)
        digest = sha(self.skill.parent)
        result = self.skill.evaluate()
        self.assertEqual(result['summary']['notes'], 120)
        self.assertTrue(result['checkpoint_unchanged'])
        self.assertEqual(original, asdict(self.skill.controller))
        self.assertEqual(digest, sha(self.skill.parent))

    def test_roundtrip_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            path.write_text(json.dumps(checkpoint(self.skill.controller, self.skill.parent_sha256)))
            recovered = read_controller(path)
            self.assertEqual(asdict(recovered), asdict(self.skill.controller))
            self.assertEqual(recovered.correction(2, 6.5), self.skill.controller.correction(2, 6.5))

    def test_training_excludes_holdout(self):
        events = [event for episode in range(60) for event in e.exercise(episode)[1]]
        self.assertEqual(len(events), 1460)
        self.assertTrue(set(event['semitones'] for event in events).isdisjoint(e.HOLDOUT_FRETS))

    def test_holdout_update_rejected(self):
        with self.assertRaises(ValueError):
            self.skill.controller.observe(e.make_event(0, 1, 6.5), {'valid': True})

    def test_sensor_rejects_silence_and_noise(self):
        self.assertFalse(e.sensor(e.np.zeros(e.SR))['valid'])
        for seed in range(8):
            self.assertFalse(e.sensor(e.np.random.default_rng(seed).normal(0, .01, e.SR))['valid'])

    def test_sensor_rejects_malformed_audio(self):
        for audio in ([], [float('nan')]*e.SR, [float('inf')]*e.SR, [[0.]*e.SR]):
            self.assertFalse(e.sensor(audio)['valid'])

    def test_failed_observation_cannot_train(self):
        ctl = copy.deepcopy(self.skill.controller)
        old = asdict(ctl)
        ctl.observe(e.make_event(0, 1, 2), {'valid': False})
        self.assertEqual(ctl.pitch_cents, old['pitch_cents'])
        self.assertEqual(ctl.updates, 0)
        self.assertEqual(ctl.rejected_observations, old['rejected_observations'] + 1)

    def test_nan_and_out_of_range_calibration_rejected(self):
        for value in (float('nan'), float('inf'), 101., True):
            state = asdict(self.skill.controller)
            state['pitch_cents']['1:2'] = value
            with self.assertRaises(ValueError):
                validate_controller(state)

    def test_invalid_counters_rejected(self):
        for value in (-1, True, 2.4):
            state = asdict(self.skill.controller)
            state['inherited_updates'] = value
            with self.assertRaises(ValueError):
                validate_controller(state)

    def test_unknown_checkpoint_and_inconsistent_total(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.json'
            data = checkpoint(self.skill.controller, self.skill.parent_sha256)
            data['total_updates'] += 1
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                SetarSkill(path)
            data['schema'] = 'another.skill'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                SetarSkill(path)

    def test_no_output_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'keep.txt'
            marker.write_text('keep')
            with self.assertRaises(FileExistsError):
                self.skill.practice(temp, episodes=1)
            self.assertEqual(marker.read_text(), 'keep')

    def test_invalid_episode_budgets(self):
        with tempfile.TemporaryDirectory() as temp:
            for episodes in (0, 61, True, 1.5):
                with self.assertRaises(ValueError):
                    self.skill.practice(Path(temp) / 'unused', episodes=episodes)
            self.assertFalse((Path(temp) / 'unused').exists())

    def test_parent_mutation_detected_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'seed.json'
            path.write_bytes(self.skill.parent.read_bytes())
            skill = SetarSkill(path)
            path.write_text(path.read_text() + ' ')
            with self.assertRaises(ValueError):
                skill.practice(Path(temp) / 'unused', episodes=1)
            self.assertFalse((Path(temp) / 'unused').exists())

    def test_restart_adds_counts_once(self):
        with tempfile.TemporaryDirectory() as temp:
            one, two = Path(temp) / 'one', Path(temp) / 'two'
            before = sha(self.skill.parent)
            first = self.skill.practice(one, episodes=1)
            self.assertEqual(first['new_updates'], 18)
            self.assertEqual(first['total_updates'], 2878)
            self.assertFalse(first['ten_minutes_wall_clock_verified'])
            cold = subprocess.run([sys.executable, '-m', 'examples.setar_practice', 'status',
                '--checkpoint', str(one / 'checkpoint.json')], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(cold.stdout)['total_updates'], 2878)
            restarted = SetarSkill(one / 'checkpoint.json')
            second = restarted.practice(two, episodes=1, seed=567891)
            self.assertEqual(second['inherited_updates'], 2878)
            self.assertEqual(second['total_updates'], 2896)
            self.assertEqual(before, sha(self.skill.parent))
            self.assertEqual(len((two / 'events.jsonl').read_text().splitlines()), 18)

    def test_interruption_marked_not_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'interrupted'
            with patch.object(e, 'render_observe', side_effect=RuntimeError('injected failure')):
                with self.assertRaises(RuntimeError):
                    self.skill.practice(out, episodes=1)
            status = json.loads((out / 'status.json').read_text())
            self.assertEqual(status['state'], 'failed_or_interrupted')
            self.assertFalse(status['replay_automatically'])
            self.assertFalse((out / 'summary.json').exists())

    def test_cli_requires_explicit_timing(self):
        result = subprocess.run([sys.executable, '-m', 'examples.setar_practice',
            'practice', '--output-dir', '/tmp/unused_setar_contract_path'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('explicit', result.stderr)

    def test_no_side_effect_on_import(self):
        with tempfile.TemporaryDirectory() as temp:
            # The package itself is inert; heavy dependencies are optional until the skill is selected.
            root = str(Path(__file__).resolve().parents[2])
            result = subprocess.run([sys.executable, '-c',
                f'import sys; sys.path.insert(0, {root!r}); import examples.setar_practice'],
                cwd=temp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
