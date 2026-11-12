"""Evaluator-owned continuous streams. Truth never enters the numeric decoder.

Develop and test are separate commands. Whole-stream splits prevent overlapping
windows from crossing the training/validation/test boundary.
"""
from collections import defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

from examples.tadash_interoception.sensory import AfferentFrame, Stimulus, transduce, LOCATIONS, TYPES
from examples.tadash_interoception.state import InternalState, observe, digest, canonical
from examples.tadash_interoception.model import Decoder, Prediction, CLASSES
from examples.tadash_interoception.integration import DiosObserver, correction_gate
from examples.tadash_interoception.evaluate import metrics as episode_metrics
from .adapters import MODEL, MODEL_SHA

SPLITS = {'train': tuple(range(1000000, 1000016)), 'diagnosis': tuple(range(1010000, 1010008)),
          'validation': tuple(range(1020000, 1020008)), 'test': tuple(range(1030000, 1030024)),
          'novel': tuple(range(1040000, 1040008))}
VARIANTS = {'full': (True, True), 'no_memory': (False, True), 'no_attention': (True, False)}
TEMPERATURES = (.25, .5, 1., 2., 4.)
TICKS = 640


def generate(seed, *, novel=False, ticks=TICKS):
    """Reuse the PR195 transducer, cropping its event envelope to active ticks.

    Each stream consists of quiet gaps (0..2 s) and 0.1..1 s events. Unknown
    compounds occur only in the dedicated novel streams. Noise also occurs
    during quiet gaps, so the observer cannot infer occurrence from noise onset.
    """
    rng = random.Random(seed)
    condition = ('clean', 'noisy', 'misleading')[seed % 3]
    noise = rng.uniform(.10, .25) if condition == 'noisy' else .025
    samples = []
    while len(samples) < ticks:
        for _ in range(rng.randint(0, 20)):
            samples.append((tuple(max(-2., min(2., rng.gauss(0, noise))) for _ in range(6)), None))
        location = rng.choice(LOCATIONS)
        kind = 'compound' if novel and rng.random() < .4 else rng.choice(TYPES)
        duration = rng.choice((.1, .3, .6, 1.))
        intensity = rng.uniform(.18, 1.)
        stimulus = Stimulus(location, intensity, duration, rng.uniform(1, 39), kind, noise, 0.)
        raw = transduce(stimulus, seed=rng.randrange(2**31))[:round(duration * 10)]
        samples.extend((frame.values, (location, kind, intensity)) for frame in raw)
    return samples[:ticks], condition


def rows(seeds, *, variant='full', novel=False, ticks=TICKS):
    memory, attention = VARIANTS[variant]
    result = []
    for seed in seeds:
        samples, condition = generate(seed, novel=novel, ticks=ticks)
        state = InternalState(memory_enabled=memory, attention_enabled=attention)
        resumed = None
        for index, (values, _) in enumerate(samples):
            frame = AfferentFrame((index + 1) / 10, values)
            state.step(frame)
            if resumed is not None: resumed.step(frame)
            if index == ticks // 2 - 1:
                resumed = InternalState.restore(json.loads(canonical(state.checkpoint())))
            if index < 15 or (index + 1) % 4: continue
            active = [x for _, x in samples[index-11:index+1] if x is not None]
            families = {(r, k) for r, k, _ in active}
            one = len(families) == 1
            location, kind = next(iter(families)) if one else ('mixed', 'mixed') if families else ('none', 'none')
            truth = {'occurred': bool(active), 'location': location, 'type': kind,
                     'intensity': statistics.mean(x[2] for x in active) if active else 0.,
                     'classifiable': one and kind in TYPES,
                     'novel_present': any(k == 'compound' for _, k in families)}
            visible = location + ':' + kind if active else 'none'
            if condition == 'misleading':
                visible = random.Random(seed * 1000 + index).choice([x for x in CLASSES if x != visible])
            # A fair reset comparator receives the same final 1.6 s raw history.
            recent = tuple(AfferentFrame((j+1)/10, value) for j, (value, _) in
                           enumerate(samples[index-15:index+1]))
            reset = observe(recent, memory=memory, attention=attention)
            result.append({'seed': seed, 'tick': index + 1, 'condition': condition,
                'features': state.features(), 'reset_features': reset.features(), 'truth': truth,
                'label': visible, 'state_sha': state.checkpoint()['sha256'],
                'memory_consistent': resumed is None or resumed.checkpoint() == state.checkpoint(),
                'load': state.load})
    return result


def scores(data, predictions):
    out = episode_metrics(data, predictions)
    eligible = [(r, p) for r, p in zip(data, predictions) if r['truth']['classifiable']]
    out['classifiable_windows'] = len(eligible)
    out['location_accuracy'] = (sum(p.location == r['truth']['location'] for r, p in eligible) / len(eligible)
                                if eligible else None)
    out['type_accuracy'] = (sum(p.stimulus_type == r['truth']['type'] for r, p in eligible) / len(eligible)
                            if eligible else None)
    novel = [(r, p) for r, p in zip(data, predictions) if r['truth']['novel_present']]
    out['novel_windows'] = len(novel)
    out['novel_uncertainty_recall'] = sum(p.novelty_uncertain for _, p in novel) / len(novel) if novel else None
    out['streams'] = len({r['seed'] for r in data})
    return out


def stratified(data, predictions):
    out = {'all': scores(data, predictions), 'conditions': {}}
    for name in ('clean', 'noisy', 'misleading'):
        indices = [i for i, r in enumerate(data) if r['condition'] == name]
        if indices: out['conditions'][name] = scores([data[i] for i in indices], [predictions[i] for i in indices])
    return out


def legacy(variant='full'):
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != MODEL_SHA: raise ValueError('legacy model mismatch')
    row = json.loads(gzip.decompress(MODEL.read_bytes()))[variant]
    return Decoder([(tuple(x), k, y) for x, k, y in row['examples']], temperature=row['temperature'])


def fit(data):
    if any(r['seed'] >= 10000 and r['seed'] not in SPLITS['train'] for r in data):
        raise ValueError('fitting requires training stream IDs')
    if any(r['truth']['novel_present'] for r in data):
        raise ValueError('novel streams cannot enter fitting')
    groups = defaultdict(list)
    for row in data:
        truth = row['truth']
        if truth['novel_present'] or truth['occurred'] and not truth['classifiable']: continue
        label = truth['location'] + ':' + truth['type'] if truth['occurred'] else 'none'
        groups[label].append((row['features'], label, truth['intensity']))
    rng = random.Random(9817)
    for group in groups.values(): rng.shuffle(group)
    selected = []
    while len(selected) < 256 and any(groups.values()):
        for label in CLASSES:
            if groups[label] and len(selected) < 256: selected.append(groups[label].pop())
    return Decoder(selected)


def predict(model, data, *, observer=None, prefix='', reset=False):
    result = []
    for row in data:
        # Closed numeric API: no label, split, seed, time, truth or condition.
        prediction = model.predict(tuple(row['reset_features' if reset else 'features']))
        if observer is not None:
            identity = f'{prefix}:{row["seed"]}:{row["tick"]}'
            observer.commit_prediction(identity, prediction, model_sha=model.fingerprint(), state_sha=row['state_sha'])
            observer.reveal(identity, row['truth'])
        result.append(prediction)
    return result


def encode(model):
    return {'examples': model.examples, 'temperature': model.temperature, 'sha256': model.fingerprint()}


def decode(row):
    model = Decoder([(tuple(x), k, y) for x, k, y in row['examples']], temperature=row['temperature'])
    if model.fingerprint() != row['sha256']: raise ValueError('continuous model fingerprint mismatch')
    return model


def write(path, value, *, compressed=False):
    raw = (canonical(value) + '\n').encode()
    with Path(path).open('xb') as stream:
        stream.write(gzip.compress(raw, mtime=0) if compressed else raw)


def implementation():
    root = Path(__file__).resolve().parents[2]
    files = [f'examples/nasuraya_runtime/{name}.py' for name in
             ('stream_study','adapters','session','native','reconsider')]
    files += [f'examples/tadash_interoception/{name}.py' for name in
              ('sensory','state','model','evaluate','integration')]
    files += [f'examples/dios_nous/{name}.py' for name in ('cognition','integration','dissent')]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}


def develop(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    observer = DiosObserver(directory / 'observer.jsonl')
    frozen = {'schema': 'nasuraya.continuous-models/1', 'splits': SPLITS,
              'implementation': implementation(), 'target_history_ticks': 12, 'query_stride_ticks': 4,
              'stream_ticks': TICKS, 'variants': {}}
    report = {}
    for name in VARIANTS:
        start = time.perf_counter()
        train, diagnostic, validation = [rows(SPLITS[k], variant=name) for k in ('train','diagnosis','validation')]
        base, candidate = legacy(name), fit(train)
        observer.emit('execute', run=1, variant=name, baseline_sha=base.fingerprint())
        bp = predict(base, diagnostic, observer=observer if name == 'full' else None, prefix=name+'/baseline')
        cp = predict(candidate, diagnostic)
        trials = []
        for temperature in TEMPERATURES:
            adjusted = [Prediction(p.occurred, 1/(1+math.exp(-math.log(p.probability/(1-p.probability))/temperature)),
                         p.location, p.stimulus_type, p.intensity, p.confidence, p.novelty_uncertain) for p in cp]
            trials.append((scores(diagnostic, adjusted)['brier'], temperature))
        candidate = candidate.with_temperature(min(trials)[1])
        bv, cv = predict(base, validation), predict(candidate, validation)
        gate = correction_gate(directory/name, scores(validation,bv), scores(validation,cv))
        selected = candidate if gate['accepted'] else base
        frozen['variants'][name] = {'baseline': encode(base), 'candidate': encode(candidate), 'selected': encode(selected),
                                    'accepted': gate['accepted']}
        report[name] = {'diagnosis_baseline': scores(diagnostic,bp), 'temperature_trials': trials,
                        'validation_baseline': scores(validation,bv), 'validation_candidate': scores(validation,cv),
                        'gate': gate, 'train_windows': len(train), 'training_examples': len(candidate.examples),
                        'elapsed_seconds': time.perf_counter()-start}
        observer.emit('self_correct', run=2, variant=name, selected_sha=selected.fingerprint(), accepted=gate['accepted'])
    observer.close()
    frozen['sha256'] = digest(frozen)
    write(directory/'frozen-models.json.gz', frozen, compressed=True)
    write(directory/'development.json', report)
    return report


def cluster_interval(data, base, candidate):
    """Paired bootstrap over whole streams, retaining within-stream dependence."""
    groups = defaultdict(list)
    for r, b, c in zip(data, base, candidate):
        y = r['truth']['occurred']
        groups[r['seed']].append(((c.probability-y)**2-(b.probability-y)**2,
                                int(c.occurred == y)-int(b.occurred == y)))
    pairs = [(statistics.mean(x[0] for x in g), statistics.mean(x[1] for x in g)) for g in groups.values()]
    rng = random.Random(99381); draws = [[], []]
    for _ in range(1000):
        sample = [rng.choice(pairs) for _ in pairs]
        for i in range(2): draws[i].append(statistics.mean(x[i] for x in sample))
    return {name: {'delta': statistics.mean(x[i] for x in pairs),
                   'ci95': [sorted(draws[i])[24], sorted(draws[i])[974]]}
            for i, name in enumerate(('brier', 'accuracy'))}


def test(directory, frozen_path):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(gzip.decompress(Path(frozen_path).read_bytes()))
    expected = frozen.pop('sha256')
    if digest(frozen) != expected or frozen['implementation'] != implementation():
        raise ValueError('frozen evaluator/model identity changed')
    if frozen['splits'] != json.loads(canonical(SPLITS)): raise ValueError('split change after freeze')
    observer = DiosObserver(directory/'observer.jsonl')
    output = {'frozen_sha256': expected, 'splits': SPLITS, 'evaluation_kind': 'first_test_or_explicit_regression',
              'target': 'any active input in last 12 ticks; unambiguous known classes scored separately', 'groups': {}}
    all_predictions = {}
    for group in ('test', 'novel'):
        data = rows(SPLITS[group], novel=group == 'novel')
        start = time.perf_counter()
        base = predict(decode(frozen['variants']['full']['baseline']),data)
        selected = predict(decode(frozen['variants']['full']['selected']),data,
                           observer=observer,prefix=group+'/selected')
        predictions = {'legacy': base, 'full': selected,
                       'reset_legacy': predict(legacy(),data,reset=True)}
        model_data = {}
        for name in ('no_memory', 'no_attention'):
            altered = rows(SPLITS[group], variant=name, novel=group == 'novel')
            predictions[name] = predict(decode(frozen['variants'][name]['selected']),altered)
            model_data[name] = altered
        for name in ('random','always_none','visible_label'):
            pred = []
            for row in data:
                rng = random.Random(row['seed']*1000+row['tick'])
                label = ('none' if rng.random()<.5 else rng.choice(CLASSES[1:])) if name == 'random' else (
                        'none' if name == 'always_none' else row['label'])
                location, kind = label.split(':') if label != 'none' else ('none','none')
                p = .5 if name == 'random' else 0. if name == 'always_none' else .99 if label != 'none' else .01
                pred.append(Prediction(label!='none',p,location,kind,.59 if label!='none' else 0.,.5,False))
            predictions[name] = pred
        output['groups'][group] = {'metrics': {name:stratified(model_data.get(name,data),p) for name,p in predictions.items()},
            'paired_stream_bootstrap':cluster_interval(data,base,selected),
            'all_model_evaluation_seconds':time.perf_counter()-start}
        all_predictions[group] = [{'seed':r['seed'],'tick':r['tick'],'truth':r['truth'],
                'condition':r['condition'],'state_sha':r['state_sha'],
                'predictions':{name:asdict(p[i]) for name,p in predictions.items()}} for i,r in enumerate(data)]
    observer.close()
    write(directory/'report.json', output)
    write(directory/'predictions.json.gz', all_predictions, compressed=True)
    return output


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('develop','test'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frozen',type=Path)
    args=parser.parse_args()
    if args.phase=='develop': develop(args.output)
    elif args.frozen is None: parser.error('test requires a frozen model file')
    else: test(args.output,args.frozen)
    print(json.dumps({'phase':args.phase,'output':str(args.output)}))


if __name__=='__main__': main()
