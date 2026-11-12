"""Prospective synthetic benchmark. Never adapts on the locked test set."""
from dataclasses import asdict
import argparse
import json
import math
from pathlib import Path
import platform
import random
import statistics
import time
import tracemalloc

from .sensory import LOCATIONS, TYPES, CONDITIONS, trial, transduce
from .state import InternalState, observe, digest
from .model import CLASSES, Decoder, Prediction
from .integration import DiosObserver, correction_gate, action_pressure, select_route

SPLITS = {'train': range(710000, 710280), 'diagnosis': range(720000, 720140),
          'validation': range(730000, 730140), 'test': range(750000, 750500)}


def dataset(split, *, memory=True, attention=True, seeds=None):
    rows = []
    for seed in SPLITS[split] if seeds is None else seeds:
        stimulus, truth, label, condition = trial(seed, training=split == 'train')
        frames = transduce(stimulus, seed=seed + 1777)
        start = time.perf_counter()
        state = observe(frames, memory=memory, attention=attention)
        elapsed = (time.perf_counter() - start) * 1000
        # Cold continuation at a fixed tick, independent of episode labels.
        half = InternalState(memory_enabled=memory, attention_enabled=attention)
        for frame in frames[:8]: half.step(frame)
        half = InternalState.restore(json.loads(json.dumps(half.checkpoint())))
        for frame in frames[8:]: half.step(frame)
        rows.append({'features': state.features(), 'truth': truth, 'label': label,
                     'condition': condition, 'state_sha': state.checkpoint()['sha256'],
                     'seed': seed, 'load': state.load, 'attention': state.attention,
                     'action_pressure': action_pressure(state),
                     'memory_consistent': half.checkpoint() == state.checkpoint(),
                     'state_ms': elapsed})
    return rows


def training_rows(rows):
    return [(r['features'], 'none' if not r['truth']['occurred'] else
             r['truth']['location'] + ':' + r['truth']['type'], r['truth']['intensity'])
            for r in rows if r['truth']['type'] != 'compound']


def known_only(rows, predictions=None):
    """Evaluator-only novelty firewall for every fitting/selection operation."""
    if predictions is None:
        return [r for r in rows if r['truth']['type'] != 'compound']
    pairs = [(r, p) for r, p in zip(rows, predictions) if r['truth']['type'] != 'compound']
    return [r for r, _ in pairs], [p for _, p in pairs]


def metrics(rows, predictions):
    n = len(rows)
    positive = sum(r['truth']['occurred'] for r in rows)
    negative = n - positive
    false_positive = sum(p.occurred and not r['truth']['occurred'] for r, p in zip(rows, predictions))
    false_negative = sum(not p.occurred and r['truth']['occurred'] for r, p in zip(rows, predictions))
    brier = sum((p.probability - r['truth']['occurred']) ** 2 for r, p in zip(rows, predictions)) / n
    ece = 0.
    for bin_id in range(10):
        pairs = [(p.probability, r['truth']['occurred']) for r, p in zip(rows, predictions)
                 if min(9, int(p.probability * 10)) == bin_id]
        if pairs:
            ece += abs(sum(x-y for x, y in pairs)) / n
    return {'n': n, 'positive': positive, 'negative': negative,
            'accuracy': 1 - (false_positive + false_negative) / n,
            'fpr': false_positive / negative if negative else None,
            'fnr': false_negative / positive if positive else None,
            'location_accuracy': sum(r['truth']['occurred'] and p.location == r['truth']['location']
                                     for r, p in zip(rows, predictions)) / positive if positive else None,
            'type_accuracy': sum(r['truth']['occurred'] and p.stimulus_type == r['truth']['type']
                                 for r, p in zip(rows, predictions)) / positive if positive else None,
            'intensity_mae': sum(abs(p.intensity - r['truth']['intensity']) for r, p in zip(rows, predictions)) / n,
            'brier': brier, 'ece10': ece,
            'novelty_flag_rate': sum(p.novelty_uncertain for p in predictions) / n,
            'memory_consistency': sum(r['memory_consistent'] for r in rows) / n}


def predict_rows(model, rows, *, observer=None, prefix=''):
    predictions, durations = [], []
    fingerprint = model.fingerprint()
    for row in rows:
        start = time.perf_counter()
        prediction = model.predict(row['features'])
        durations.append((time.perf_counter() - start) * 1000)
        if observer:
            identity = prefix + ':' + str(row['seed'])
            observer.commit_prediction(identity, prediction, model_sha=fingerprint, state_sha=row['state_sha'])
            observer.reveal(identity, row['truth'])
        predictions.append(prediction)
    return predictions, statistics.mean(durations)


def grouped_metrics(rows, predictions):
    result = {'all': metrics(rows, predictions), 'conditions': {}}
    for condition in CONDITIONS:
        pairs = [(r, p) for r, p in zip(rows, predictions) if r['condition'] == condition]
        if pairs:
            result['conditions'][condition] = metrics([r for r, _ in pairs], [p for _, p in pairs])
    return result


def develop(directory, observer, *, memory=True, attention=True, prefix='full', seed_sets=None):
    """The full three-run correction process; test data is inaccessible here."""
    def data(split):
        return dataset(split, memory=memory, attention=attention,
                       seeds=None if seed_sets is None else seed_sets[split])
    train, diagnosis, validation = data('train'), data('diagnosis'), data('validation')
    baseline = Decoder(training_rows(train))
    observer.emit('execute', run=1, variant=prefix, baseline_sha=baseline.fingerprint())
    diagnosed, _ = predict_rows(baseline, diagnosis, observer=observer, prefix=prefix + '/run1')
    diagnosed_metrics = metrics(diagnosis, diagnosed)
    errors = [{'seed': r['seed'], 'condition': r['condition'], 'truth': r['truth'],
               'prediction': asdict(p)} for r, p in zip(diagnosis, diagnosed)
              if p.occurred != r['truth']['occurred'] or p.stimulus_type != r['truth']['type']]
    observer.emit('evaluate', run=1, variant=prefix, metrics=diagnosed_metrics,
                  likely_causes=['sensor_noise_and_distribution_shift', 'unknown_compound_not_in_class_set'],
                  causes_are_hypotheses=True, errors=len(errors))
    candidate = Decoder(training_rows(train + diagnosis))
    # Select confidence on prior committed predictions, never on test outcomes.
    calibration_rows, calibration_predictions = known_only(diagnosis, diagnosed)
    temperatures = (.5, 1., 2., 4.)
    scores = []
    for temperature in temperatures:
        adjusted = []
        for p in calibration_predictions:
            probability = 1 / (1 + math.exp(-math.log(p.probability/(1-p.probability))/temperature))
            adjusted.append(Prediction(p.occurred, probability, p.location, p.stimulus_type,
                                       p.intensity, p.confidence, p.novelty_uncertain))
        scores.append((metrics(calibration_rows, adjusted)['brier'], temperature))
    candidate = candidate.with_temperature(min(scores)[1])
    observer.emit('execute', run=2, variant=prefix, candidate_sha=candidate.fingerprint())
    base_val, _ = predict_rows(baseline, validation, observer=observer, prefix=prefix + '/validation_base')
    cand_val, _ = predict_rows(candidate, validation, observer=observer, prefix=prefix + '/validation_candidate')
    gate_rows, base_gate = known_only(validation, base_val)
    _, cand_gate = known_only(validation, cand_val)
    gate = correction_gate(directory / prefix, metrics(gate_rows, base_gate), metrics(gate_rows, cand_gate))
    selected = candidate if gate['accepted'] else baseline
    observer.emit('self_correct', run=2, variant=prefix, baseline_sha=baseline.fingerprint(),
                  candidate_sha=candidate.fingerprint(), selected_sha=selected.fingerprint(), gate=gate)
    record = {'diagnosis': diagnosed_metrics, 'errors': errors, 'temperature_trials': scores,
              'gate': gate, 'old_sha': baseline.fingerprint(), 'candidate_sha': candidate.fingerprint(),
              'selected_sha': selected.fingerprint(), 'rollback_available': True,
              'train_count': len(baseline.examples), 'candidate_count': len(candidate.examples),
              'calibration_seeds': [r['seed'] for r in calibration_rows],
              'acceptance_seeds': [r['seed'] for r in gate_rows],
              'novel_cases_used_for_fitting_or_selection': 0}
    return baseline, selected, record


def baseline_prediction(row, mode):
    if mode == 'oracle':
        truth = row['truth']
        return Prediction(truth['occurred'], float(truth['occurred']), truth['location'],
                          truth['type'], truth['intensity'], 1., truth['type'] == 'compound')
    if mode == 'random':
        rng = random.Random(row['seed'] + 8821)
        detected = rng.random() >= .5
        return Prediction(detected, .5, rng.choice(LOCATIONS) if detected else 'none',
                          rng.choice(TYPES) if detected else 'none', rng.random() if detected else 0., .5, False)
    label = row['label']
    detected = label != 'none'
    location, kind = label.split(':') if detected else ('none', 'none')
    return Prediction(detected, .99 if detected else .01, location, kind,
                      .59 if detected else 0., .99, False)


def bootstrap(rows, base, full):
    rng = random.Random(748001)
    acc = [int(p.occurred == r['truth']['occurred']) - int(b.occurred == r['truth']['occurred'])
           for r, b, p in zip(rows, base, full)]
    brier = [(p.probability-r['truth']['occurred'])**2 - (b.probability-r['truth']['occurred'])**2
             for r, b, p in zip(rows, base, full)]
    draws = [[], []]
    for _ in range(2000):
        indices = [rng.randrange(len(rows)) for _ in rows]
        for target, values in zip(draws, (acc, brier)):
            target.append(sum(values[i] for i in indices) / len(indices))
    return {key: {'delta': statistics.mean(values), 'descriptive_95ci': [sorted(draw)[49], sorted(draw)[1949]]}
            for key, values, draw in zip(('accuracy', 'brier'), (acc, brier), draws)}


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def run(directory, *, include_test=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    observer = DiosObserver(directory / 'observer.jsonl')
    models, records, rollbacks = {}, {}, {}
    for name, memory, attention in (('full', True, True), ('no_memory', False, True), ('no_attention', True, False)):
        base, selected, record = develop(directory, observer, memory=memory, attention=attention, prefix=name)
        models[name] = selected
        rollbacks[name] = {'examples': base.examples, 'temperature': base.temperature, 'sha256': base.fingerprint()}
        records[name] = record
        if name == 'full': models['no_correction'] = base
    # Frozen before dataset('test') can be called. Contains rollback model data.
    frozen = {name: {'examples': model.examples, 'temperature': model.temperature,
                     'sha256': model.fingerprint()} for name, model in models.items()}
    write_json(directory / 'frozen_models.json', frozen)
    write_json(directory / 'rollback_models.json', rollbacks)
    observer.emit('models_frozen', sha256=digest(frozen))
    report = {'schema': 'tadash.interoception.experiment.v1', 'python': platform.python_version(),
              'protocol': 'TADASH_INTEROCEPTION_CONFIRMATION_2026-11-12.md',
              'split_ranges': {key: [r.start, r.stop-1] for key, r in SPLITS.items()},
              'corrections': records, 'test_executed': include_test,
              'frozen_model_sha': digest(frozen), 'subjective_experience_established': False}
    if include_test:
        predictions = {}
        report['models'] = {}
        for name, memory, attention in (('full', True, True), ('no_correction', True, True),
                                        ('no_memory', False, True), ('no_attention', True, False)):
            rows = dataset('test', memory=memory, attention=attention)
            observer.emit('execute', run=3, variant=name, adaptation_enabled=False)
            pred, cost = predict_rows(models[name], rows, observer=observer, prefix=name + '/test')
            report['models'][name] = grouped_metrics(rows, pred)
            actions = [select_route({'energy': 70, 'heat': 30}, r['action_pressure']).selected_route for r in rows]
            report['models'][name]['behavior'] = {
                'recover_rate': actions.count('recover') / len(actions),
                'quiet_reference_action': 'process_job',
                'scope': 'authored_policy_selections_on_test_states_not_measured_task_benefit',
                'recover_rate_by_condition': {c: sum(a == 'recover' for a, r in zip(actions, rows) if r['condition'] == c) /
                    sum(r['condition'] == c for r in rows) for c in CONDITIONS}}
            report['models'][name]['cost'] = {'mean_prediction_ms': cost,
                         'mean_state_ms': statistics.mean(r['state_ms'] for r in rows)}
            predictions[name] = pred
        # The same full-state test episodes feed the comparison baselines.
        rows = dataset('test')
        for name in ('random', 'visible_label', 'oracle'):
            pred = []
            start = time.perf_counter()
            for row in rows:
                p = baseline_prediction(row, name)
                observer.commit_prediction(name + ':' + str(row['seed']), p, model_sha=name, state_sha='not_used')
                observer.reveal(name + ':' + str(row['seed']), row['truth'])
                pred.append(p)
            report['models'][name] = grouped_metrics(rows, pred)
            report['models'][name]['cost'] = {'mean_prediction_and_logging_ms': (time.perf_counter()-start)*1000/len(rows)}
            predictions[name] = pred
        report['paired_change'] = bootstrap(rows, predictions['no_correction'], predictions['full'])
        report['trial_predictions'] = [{'seed': r['seed'], 'condition': r['condition'], 'truth': r['truth'],
              'predictions': {name: asdict(pred[i]) for name, pred in predictions.items()}} for i, r in enumerate(rows)]
        tracemalloc.start()
        for row in rows[:20]: models['full'].predict(row['features'])
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        report['decoder_peak_traced_bytes_20_predictions'] = peak
        observer.emit('evaluate', run=3, metrics={key: value['all'] for key, value in report['models'].items()},
                      corrections_on_test=0)
    report['observer'] = {'events': observer.sequence, 'errors_including_novel': observer.errors, 'tail': observer.tail}
    observer.close()
    write_json(directory / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-test', action='store_true')
    args = parser.parse_args()
    report = run(args.output, include_test=args.include_test)
    print(json.dumps({'test_executed': report['test_executed'], 'gates': {
        k: v['gate']['accepted'] for k, v in report['corrections'].items()}, 'models': {
        k: v['all'] for k, v in report.get('models', {}).items()}}, indent=2))


if __name__ == '__main__': main()
