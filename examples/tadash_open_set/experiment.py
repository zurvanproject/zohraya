"""Reproducible prospective evaluation; 'calibrate' must precede 'evaluate'."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import random

from examples.tadash_interoception.sensory import Stimulus, AfferentFrame, trial, transduce
from examples.tadash_interoception.state import observe, digest
from .open_set import (ALPHA, CALIBRATION_SEEDS, VALIDATION_SEEDS, FINAL_SEEDS,
                       HISTORICAL_SEEDS, MODEL_SHA, SelectiveDecoder, calibrate,
                       comparison, frozen_decoder, known_rows, decide, action_cost)


def _pulsed_unknown(seed):
    """Independent held-out mixture: two offset channels with alternating pulses."""
    rng = random.Random(seed + 90673)
    region = rng.choice(('left_palm', 'right_palm'))
    intensity = rng.uniform(.25, .9)
    frames = []
    for i in range(16):
        t = i / 10
        if .2 <= t < 1.2:
            mechanical = intensity * (.75 if (i % 4) < 2 else .05)
            thermal = intensity * .55 * (1 - math.exp(-(t - .2 + .1) / .25))
            vibration = intensity * (.32 if i % 3 else .8)
        else:
            mechanical, thermal, vibration = 0., 0., 0.
        values = []
        for region_name in ('left_palm', 'right_palm'):
            coupling = 1 if region_name == region else .08
            values.extend(max(-2., min(2., coupling * z + rng.gauss(0, .075)))
                          for z in (mechanical, thermal, vibration))
        frames.append(AfferentFrame(t + .1, tuple(values)))
    truth = {'occurred': True, 'location': region, 'type': 'pulsed_mixture', 'intensity': intensity}
    return {'seed': seed, 'features': observe(tuple(frames)).features(),
            'condition': 'pulsed_unknown', 'truth': truth}


def final_episode(seed):
    if seed not in FINAL_SEEDS: raise ValueError('outside locked prospective split')
    if seed < 850500:
        stimulus, truth, _, condition = trial(seed)
        return {'seed': seed, 'features': observe(transduce(stimulus, seed=seed + 1777)).features(),
                'condition': condition, 'truth': truth}
    if seed < 850600:
        rng = random.Random(seed + 1044)
        loc = rng.choice(('left_palm', 'right_palm'))
        noise = rng.uniform(.10, .25)
        stimulus = Stimulus(loc, 0., .8, 9., 'none', noise, .2)
        truth = {'occurred': False, 'location': 'none', 'type': 'none', 'intensity': 0.}
        return {'seed': seed, 'features': observe(transduce(stimulus, seed=seed + 1777)).features(),
                'condition': 'quiet_absent_high_noise', 'truth': truth}
    return _pulsed_unknown(seed)


def _write_new(path, obj):
    with Path(path).open('x', encoding='utf-8') as out:
        json.dump(obj, out, indent=2, sort_keys=True, allow_nan=False)
        out.write('\n')


def preflight():
    sets = [set(s) for s in HISTORICAL_SEEDS] + [set(CALIBRATION_SEEDS),
                                                  set(VALIDATION_SEEDS), set(FINAL_SEEDS)]
    for i, a in enumerate(sets):
        for b in sets[i+1:]:
            assert a.isdisjoint(b), 'held-out seed overlap'
    assert len(known_rows(range(810000, 810005))) == 4


def calibrate_to(directory):
    preflight()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    base = frozen_decoder()
    calibration = calibrate(base)
    _write_new(directory / 'calibration.json', calibration)
    gate = SelectiveDecoder(base, calibration)
    validation = known_rows(VALIDATION_SEEDS)
    summary = comparison(validation, base, gate)
    report = {'schema': 'tadash.open-set.known-validation.v1',
              'calibration_sha256': calibration['sha256'], 'model_sha': MODEL_SHA,
              'split': 'known-only threshold validation; not final test',
              'novel_validation_rows': 0, 'metrics': summary}
    _write_new(directory / 'known_validation.json', report)
    return report


def evaluate_to(calibration_path, directory):
    preflight()
    calibration = json.loads(Path(calibration_path).read_text(encoding='utf-8'))
    base = frozen_decoder()
    gate = SelectiveDecoder(base, calibration)  # checks fingerprint and settings
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    rows = [final_episode(s) for s in FINAL_SEEDS]
    # Model sees features ONLY. Persist predictions before opening truth record.
    previous = '0' * 64
    records = []
    with (directory / 'events.jsonl').open('x', encoding='utf-8') as stream:
        for row in rows:
            prediction = asdict(base.predict(row['features']))
            selection = asdict(gate.infer(row['features']))
            for stage, fields in (('prediction', {'original': prediction, 'selective': selection}),
                                  ('reveal', {'truth': row['truth'], 'condition': row['condition']})):
                event = {'seed': row['seed'], 'stage': stage, 'previous': previous, **fields}
                event['sha256'] = digest(event)
                stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + '\n')
                stream.flush()
                previous = event['sha256']
            records.append({'seed': row['seed'], 'prediction': prediction, 'selection': selection,
                            'truth': row['truth'], 'condition': row['condition']})
    summary = comparison(rows, base, gate)
    result = {'schema': 'tadash.open-set.holdout.v1', 'model_sha': MODEL_SHA,
              'calibration_sha256': calibration['sha256'],
              'heldout_episode_seeds': [FINAL_SEEDS.start, FINAL_SEEDS.stop - 1],
              'n': len(rows), 'frozen_threshold_alpha': ALPHA,
              'observer_chain_tail': previous,
              'metrics': summary,
              'scope': 'synthetic offline episode-wise evaluation; no PR196 runtime action integration',
              'counterfactual_cost_scope': 'illustrative authored action policy and loss; not real task utility',
              'sources': {'original': 'PR195 exact frozen fingerprint and procedural generator',
                          'external_shift': 'independently authored pulsed mixture and high-noise absent fixtures'},
              'model_weights_unchanged': base.fingerprint() == MODEL_SHA,
              'no_main_merge_or_production_deploy': True}
    result['sha256'] = digest(result)
    _write_new(directory / 'summary.json', result)
    _write_new(directory / 'predictions.json', records)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    cmd_cal = commands.add_parser('calibrate')
    cmd_cal.add_argument('--output', required=True, type=Path)
    cmd_eval = commands.add_parser('evaluate')
    cmd_eval.add_argument('--calibration', required=True, type=Path)
    cmd_eval.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'calibrate':
        result = calibrate_to(args.output)
    else:
        result = evaluate_to(args.calibration, args.output)
    print(json.dumps(result['metrics'] if 'metrics' in result else result, indent=2, sort_keys=True))


if __name__ == '__main__': main()
