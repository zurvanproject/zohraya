from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from examples.nasuraya_agent_loop.local import Journal, State, ToolHost, run_local
from .sensory import Stimulus, AfferentFrame, transduce, trial
from .state import InternalState, observe, digest
from .model import Decoder
from .integration import DiosObserver, SensoryPolicy, correction_gate, action_pressure
from .evaluate import dataset, training_rows, metrics, predict_rows, SPLITS, baseline_prediction, known_only


def sample(kind='mechanical', intensity=.8, noise=.025):
    return Stimulus('left_palm', 0. if kind == 'none' else intensity, .8, 13., kind, noise, .2)


class SensoryTests(unittest.TestCase):
    def test_all_modalities_and_no_stimulus(self):
        rows = [transduce(sample(k), seed=5) for k in ('none', 'mechanical', 'thermal', 'vibration', 'compound')]
        self.assertTrue(all(len(r) == 16 for r in rows))
        self.assertEqual(len({str(r) for r in rows}), 5)

    def test_noise_and_seed_replay(self):
        self.assertEqual(transduce(sample(), seed=17), transduce(sample(), seed=17))
        self.assertNotEqual(transduce(sample(), seed=17), transduce(sample(), seed=18))

    def test_invalid_stimulus_fields(self):
        for field, value in (('intensity', float('nan')), ('noise', float('inf')), ('duration', 0),
                             ('timestamp', -1), ('frequency', True), ('location', 'unknown')):
            with self.subTest(field=field), self.assertRaises(ValueError): replace(sample(), **{field: value})
        with self.assertRaises(ValueError): replace(sample(), stimulus_type='none')

    def test_frame_is_numeric_and_closed(self):
        with self.assertRaises(ValueError): AfferentFrame(.1, (0.,)*5)
        with self.assertRaises(ValueError): AfferentFrame(.1, (float('nan'),)*6)
        self.assertEqual(set(asdict(transduce(sample(), seed=1)[0])), {'timestamp', 'values'})

    def test_frequency_and_duration_change_afferents(self):
        base = sample('vibration')
        self.assertNotEqual(transduce(base, seed=1), transduce(replace(base, frequency=6.2), seed=1))
        self.assertNotEqual(transduce(base, seed=1), transduce(replace(base, duration=.4), seed=1))

    def test_spatial_localization_not_single_constant(self):
        a = observe(transduce(sample(), seed=1)).features()
        b = observe(transduce(replace(sample(), location='right_palm'), seed=1)).features()
        self.assertGreater(a[0], a[3])
        self.assertGreater(b[3], b[0])


class StateTests(unittest.TestCase):
    def test_stable_memory_after_afferent_ceases(self):
        state = observe(transduce(sample(noise=0), seed=1))
        self.assertGreater(max(state.features()), max(state.sensory))
        self.assertGreater(state.load, 0.)
        self.assertGreater(state.prediction_error, 0.)

    def test_memory_ablation(self):
        frames = transduce(sample(), seed=9)
        full, off = observe(frames), observe(frames, memory=False)
        self.assertGreater(max(full.features()), max(off.features()))
        self.assertGreater(action_pressure(full), action_pressure(off))

    def test_attention_ablation(self):
        frames = transduce(sample(), seed=9)
        full, off = observe(frames), observe(frames, attention=False)
        self.assertNotEqual(full.features(), off.features())
        self.assertEqual(off.attention, [1., 1.])

    def test_nonmonotonic_time_cannot_mutate(self):
        state = InternalState()
        frame = AfferentFrame(.1, (0.,)*6)
        state.step(frame)
        before = state.checkpoint()
        with self.assertRaises(ValueError): state.step(frame)
        self.assertEqual(before, state.checkpoint())

    def test_cold_continuation(self):
        frames = transduce(sample(), seed=4)
        prefix = observe(frames[:8])
        restored = InternalState.restore(prefix.checkpoint())
        for frame in frames[8:]: restored.step(frame)
        self.assertEqual(restored.checkpoint(), observe(frames).checkpoint())

    def test_corruption_and_forged_shape_rejected(self):
        envelope = observe(transduce(sample(), seed=1)).checkpoint()
        envelope['state']['load'] += .1
        with self.assertRaises(ValueError): InternalState.restore(envelope)
        envelope['state']['sensory'] = [0.]
        envelope['sha256'] = digest(envelope['state'])
        with self.assertRaises(ValueError): InternalState.restore(envelope)

    def test_checkpoint_has_no_aliases(self):
        state = observe(transduce(sample(), seed=1))
        restored = InternalState.restore(state.checkpoint())
        restored.sensory[0] = 0.
        self.assertNotEqual(restored.sensory, state.sensory)

    def test_fresh_process_restore(self):
        state = observe(transduce(sample(), seed=1))
        code = 'import json,sys; from examples.tadash_interoception.state import InternalState; print(json.dumps(InternalState.restore(json.load(sys.stdin)).checkpoint()))'
        proc = subprocess.run([sys.executable, '-c', code], input=json.dumps(state.checkpoint()),
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout), state.checkpoint())


class DecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = dataset('train', seeds=range(100, 160))
        cls.model = Decoder(training_rows(cls.rows))

    def test_predict_is_label_blind(self):
        features = self.rows[0]['features']
        with self.assertRaises(TypeError): self.model.predict(features, label='mechanical')
        with self.assertRaises(ValueError): self.model.predict({'features': features, 'truth': 'none'})
        self.assertEqual(self.model.predict(features), self.model.predict(features))

    def test_misleading_label_does_not_change_prediction(self):
        row = dict(self.rows[0])
        before = self.model.predict(row['features'])
        row.update(label='right_palm:thermal', truth={'occurred': not row['truth']['occurred']})
        self.assertEqual(self.model.predict(row['features']), before)

    def test_predictions_are_bounded_and_model_frozen(self):
        before = self.model.fingerprint()
        for row in dataset('validation', seeds=range(300, 320)):
            p = self.model.predict(row['features'])
            for v in (p.probability, p.intensity, p.confidence): self.assertTrue(0 <= v <= 1)
        self.assertEqual(before, self.model.fingerprint())

    def test_novel_not_in_training(self):
        rows = dataset('diagnosis', seeds=range(500, 550))
        entries = training_rows(rows)
        self.assertLess(len(entries), len(rows))
        self.assertTrue(all('compound' not in label for _, label, _ in entries))

    def test_novel_excluded_from_calibration_and_acceptance(self):
        rows = dataset('diagnosis', seeds=range(500, 550))
        predictions = [baseline_prediction(r, 'oracle') for r in rows]
        filtered, aligned = known_only(rows, predictions)
        self.assertEqual(len(filtered), 40)
        self.assertEqual(len(aligned), 40)
        self.assertTrue(all(r['truth']['type'] != 'compound' for r in filtered))
        self.assertEqual(filtered, known_only(rows))

    def test_loadable_rollback_restores_exact_model(self):
        raw = json.loads(json.dumps({'examples': self.model.examples, 'temperature': self.model.temperature}))
        restored = Decoder([(tuple(f), k, v) for f, k, v in raw['examples']], temperature=raw['temperature'])
        self.assertEqual(restored.fingerprint(), self.model.fingerprint())
        self.assertEqual(restored.predict(self.rows[0]['features']), self.model.predict(self.rows[0]['features']))

    def test_splits_disjoint(self):
        keys = list(SPLITS)
        for i, a in enumerate(keys):
            for b in keys[i+1:]: self.assertFalse(set(SPLITS[a]) & set(SPLITS[b]))

    def test_metrics_known_errors(self):
        rows = dataset('diagnosis', seeds=range(600, 625))
        predictions = [baseline_prediction(r, 'oracle') for r in rows]
        result = metrics(rows, predictions)
        self.assertEqual(result['accuracy'], 1.)
        self.assertEqual(result['brier'], 0.)
        self.assertEqual(result['intensity_mae'], 0.)

    def test_visible_label_baseline_fails_misleading(self):
        rows = dataset('diagnosis', seeds=range(600, 625))
        subset = [r for r in rows if r['condition'] == 'misleading']
        self.assertTrue(all(baseline_prediction(r, 'visible_label').stimulus_type != r['truth']['type'] or
                            baseline_prediction(r, 'visible_label').location != r['truth']['location'] for r in subset))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def test_prediction_before_truth_and_hash_chain(self):
        row = dataset('train', seeds=[5])[0]
        observer = DiosObserver(self.path / 'observer.jsonl')
        with self.assertRaises(ValueError): observer.reveal('x', row['truth'])
        prediction = baseline_prediction(row, 'oracle')
        observer.commit_prediction('x', prediction, model_sha='fixture', state_sha=row['state_sha'])
        observer.reveal('x', row['truth'])
        with self.assertRaises(ValueError): observer.commit_prediction('x', prediction, model_sha='f', state_sha='f')
        observer.close()
        events = [json.loads(line) for line in (self.path / 'observer.jsonl').read_text().splitlines()]
        self.assertEqual([e['kind'] for e in events], ['prediction', 'revealed_outcome'])
        self.assertEqual(events[1]['previous'], events[0]['sha256'])
        for event in events:
            claimed = event.pop('sha256')
            self.assertEqual(claimed, digest(event))

    def test_dios_rejects_and_then_revises(self):
        base = {'brier': .1, 'accuracy': .9}
        first = correction_gate(self.path, base, {'brier': .2, 'accuracy': .9})
        self.assertFalse(first['accepted'])
        second = correction_gate(self.path, base, {'brier': .05, 'accuracy': .9}, phase=2)
        self.assertTrue(second['accepted'])
        self.assertTrue(second['dios']['evidence_review']['revised'])

    def test_accuracy_regression_blocks_update(self):
        gate = correction_gate(self.path, {'brier': .1, 'accuracy': .9}, {'brier': .05, 'accuracy': .8})
        self.assertFalse(gate['accepted'])

    def test_actual_host_action_changes_without_text(self):
        states = []
        for kind in ('none', 'mechanical'):
            state = observe(transduce(sample(kind, intensity=.95), seed=183))
            policy = SensoryPolicy(state, self.path / kind)
            host = ToolHost(State(70, 30, 2), Journal(), max_actions=1)
            result = run_local(host, policy, max_steps=1)
            self.assertEqual(result['actions_used'], 1)
            states.append(result['final_state'])
        self.assertNotEqual(states[0], states[1])
        self.assertEqual(states[0]['completed_jobs'], 1)
        self.assertEqual(states[1]['completed_jobs'], 0)

    def test_agent_reports_internal_uncertainty(self):
        state = observe(transduce(sample(), seed=12))
        policy = SensoryPolicy(state, self.path)
        model = Decoder(training_rows(dataset('train', seeds=range(2000, 2040))))
        report = policy.introspect(model)
        self.assertEqual(report['inference'], asdict(model.predict(state.features())))
        self.assertTrue(0 <= report['detection_uncertainty'] <= .5)
        self.assertEqual(report['memory_frames'], 12)
        self.assertNotIn('truth', report)

    def test_sticky_stop_and_observe_only_host(self):
        state = observe(transduce(sample(), seed=1))
        policy = SensoryPolicy(state, self.path)
        host = ToolHost(State(70, 30, 2), Journal(), mode='observe')
        result = run_local(host, policy, max_steps=1)
        self.assertEqual(result['actions_used'], 0)
        policy.stop()
        restored = SensoryPolicy(state, self.path)
        with self.assertRaises(ValueError): restored.choose({'energy': 70, 'heat': 30})

    def test_underlying_host_protection_remains(self):
        policy = SensoryPolicy(observe(transduce(sample('none'), seed=1)), self.path)
        host = ToolHost(State(20, 80, 2), Journal(), max_actions=1)
        result = run_local(host, policy, max_steps=1)
        self.assertEqual(result['final_state']['completed_jobs'], 0)
        self.assertGreater(result['final_state']['energy'], 20)

    @unittest.skipUnless(sys.platform == 'linux', 'native fcntl runtime is Linux-only')
    def test_native_source_pinned_body_and_cold_memory(self):
        from .demo import native_demo
        result = native_demo(self.path / 'native')
        self.assertTrue(result['original_sources_unchanged'])
        for name in ('none', 'mechanical', 'sleep_protection'):
            self.assertTrue(result[name]['budget_enforced'])
            self.assertTrue(result[name]['cold_checkpoint_matches'])
            self.assertEqual(result[name]['retained_touch'], result[name]['input_touch'])
            self.assertEqual(result[name]['receipt']['status'], 'complete')
        self.assertEqual(result['none']['receipt']['actual_action'], 'walk')
        self.assertEqual(result['mechanical']['receipt']['actual_action'], 'observe')
        self.assertEqual(result['sleep_protection']['receipt']['actual_action'], 'protect')


if __name__ == '__main__': unittest.main()
