"""Reproduce frozen signal cases and matched native body trend observations."""
import argparse
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time

from interoceptive_trends import InteroceptiveTrends, InteroceptiveBody, source_fingerprints
from neuropelvic_body import NeuroPelvicBody
from persistent_embodiment_v1 import instant
from synthetic_fixture import prepare_defaults, synthetic_body

ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT/'evidence/interoceptive_trends/protocol.json'


def signal_cases(protocol):
    p = protocol['signal_trials']
    results = []
    for seed in range(p['seeds'][0], p['seeds'][1] + 1):
        for condition, sign in [('stable', 0), ('up', 1), ('down', -1)]:
            rng, monitor = random.Random(seed), InteroceptiveTrends()
            changes = {key: [] for key in p['baseline']}
            for i in range(1, p['samples'] + 1):
                values = {key: value + rng.gauss(0, p['noise_sd'][key]) +
                          (sign * p['step'][key] if i >= p['change_at_sample'] else 0)
                          for key, value in p['baseline'].items()}
                result = monitor.observe(event_id=str(i), time_s=i, values=values)
                for key, channel in result['channels'].items():
                    if channel['direction']:
                        changes[key].append(dict(sample=i, direction=channel['direction']))
            early = {k: [x for x in v if x['sample'] < p['change_at_sample']] for k, v in changes.items()}
            delay = {k: next((x['sample'] - p['change_at_sample'] for x in v
                             if x['sample'] >= p['change_at_sample']), None) for k, v in changes.items()}
            results.append(dict(seed=seed, condition=condition, changes=changes,
                                pre_change_detections=early, detection_delay_samples=delay))
    stable = [r for r in results if r['condition'] == 'stable']
    steps = [r for r in results if r['condition'] != 'stable']
    summary = dict(trials=len(results), samples=len(results) * p['samples'],
        stable_false_detections=sum(len(v) for r in stable for v in r['changes'].values()),
        pre_change_false_detections=sum(len(v) for r in steps for v in r['pre_change_detections'].values()),
        step_channels=len(steps) * 2,
        detected_step_channels=sum(d is not None for r in steps for d in r['detection_delay_samples'].values()),
        maximum_detection_delay_samples=max((d for r in steps for d in r['detection_delay_samples'].values() if d is not None), default=None),
        all_directions_correct=all(x['direction'] == r['condition'] for r in steps
                                   for v in r['changes'].values() for x in v))
    summary['accepted'] = (summary['stable_false_detections'] == 0 and
        summary['pre_change_false_detections'] == 0 and summary['detected_step_channels'] == summary['step_channels'] and
        summary['maximum_detection_delay_samples'] <= 20 and summary['all_directions_correct'])
    return dict(summary=summary, trials=results)


def make_request(body, i, p):
    neuro = None
    if i >= p['initial_observe_seconds']:
        neuro = dict(source_id='frozen-interoceptive-trend-fixture', kind='declared_simulated_input',
            start=i == p['initial_observe_seconds'], intensity=p['neuro_intensity'],
            rhythm=p['neuro_rhythm'], breath_cue=p['breath_cue'], attention=p['attention'])
    return dict(event_id='trend-' + str(i+1),
        at_utc=(instant(body.bridge.body.owner.wall_utc) + timedelta(seconds=1)).isoformat(),
        duration_s=1., neuro=neuro, expected_revision=body.bridge.revision)


def cold_step(source, target):
    value = json.loads(source.read_text())
    body = InteroceptiveBody.restore(value['checkpoint'])
    receipt = body.cycle(**value['request'])
    target.write_text(json.dumps(dict(receipt=receipt, checkpoint=body.checkpoint()), sort_keys=True, allow_nan=False))


def native_cases(protocol, output):
    prepare_defaults()
    template, results, traces = synthetic_body(), {}, []
    p = protocol['native_trials']
    cold_equal, replay_equal = False, False
    for name, coupling in [('coupled', True), ('ablated', False)]:
        plain = NeuroPelvicBody(deepcopy(template), coupling=coupling)
        body = InteroceptiveBody(deepcopy(plain))
        events, kwargs_cache, receipts_cache = [], {}, {}
        matched, native_ticks, paced_ticks = True, 0, 0
        for i in range(p['duration_seconds']):
            kwargs = make_request(body, i, p)
            if name == 'coupled' and i == 40:
                with tempfile.TemporaryDirectory(prefix='tadash-trend-restart-') as tmp:
                    source, target = Path(tmp)/'request.json', Path(tmp)/'result.json'
                    source.write_text(json.dumps(dict(checkpoint=body.checkpoint(), request=kwargs), sort_keys=True, allow_nan=False))
                    subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        '--cold-step', str(source), '--cold-output', str(target)], check=True, capture_output=True, text=True)
                    resumed = json.loads(target.read_text())
            record = body.cycle(**kwargs)
            without_observer = deepcopy(record)
            without_observer.pop('interoception')
            reference = plain.cycle(**kwargs)
            matched &= without_observer == reference and body.bridge.checkpoint() == plain.checkpoint()
            if name == 'coupled' and i == 40:
                cold_equal = resumed['receipt'] == record and resumed['checkpoint'] == body.checkpoint()
            kwargs_cache[i], receipts_cache[i] = kwargs, deepcopy(record)
            if name == 'coupled' and i == 50:
                before = body.checkpoint()
                replay_equal = body.cycle(**kwargs_cache[40]) == receipts_cache[40] and body.checkpoint() == before
            native_ticks += record['owner_ticks']
            paced_ticks += record['achieved_slow_breath_ticks']
            changes = {k: v for k, v in record['interoception']['channels'].items() if v['direction']}
            for key, detail in changes.items():
                events.append(dict(elapsed_s=i+1, channel=key, direction=detail['direction'],
                    value=detail['value'], selected_action=record['selected_action'],
                    achieved_slow_breath_ticks=record['achieved_slow_breath_ticks']))
            traces.append(dict(scenario=name, elapsed_s=i+1, body_time_s=record['body_time_after_s'],
                HR=record['after_body']['HR'], RR=record['after_body']['RR'],
                phase=record['neuropelvic']['phase'], selected_action=record['selected_action'],
                achieved_slow_breath_ticks=record['achieved_slow_breath_ticks'],
                interoception=record['interoception'], audit=record['audit']))
        resumed = InteroceptiveBody.restore(json.loads(json.dumps(body.checkpoint(), sort_keys=True)))
        results[name] = dict(native_ticks=native_ticks, paced_breath_ticks=paced_ticks,
            observer_samples=body.monitor.sample_count, observer_has_no_native_effect=matched,
            json_roundtrip=resumed.checkpoint() == body.checkpoint(), changes=events,
            final_HR=record['after_body']['HR'], final_RR=record['after_body']['RR'])
    acceptance = dict(
        signal_detected_during_paced_respiration=any(e['channel']=='RR' and e['direction']=='down' and
            e['achieved_slow_breath_ticks'] > 0 for e in results['coupled']['changes']),
        observer_preserves_native_state=all(r['observer_has_no_native_effect'] for r in results.values()),
        native_ticks_exact=all(r['native_ticks']==p['duration_seconds']*10 for r in results.values()),
        all_samples_from_native=all(r['observer_samples']==p['duration_seconds'] for r in results.values()),
        json_roundtrip=all(r['json_roundtrip'] for r in results.values()),
        separate_process_continuation=cold_equal, replay_without_observation=replay_equal,
        conservation=all(abs(t['audit']['energy_error_J'])<5e-5 and abs(t['audit']['water_error_L'])<1e-8 for t in traces))
    (output/'native_traces.json').write_text(json.dumps(traces, indent=2, allow_nan=False)+'\n')
    return dict(scenarios=results, acceptance=acceptance,
        total_native_evaluation_cycles=2*p['duration_seconds']*2 + 1,
        total_native_evaluation_ticks=(2*p['duration_seconds']*2 + 1)*10,
        warmup_note='One template warm-up of seven simulated seconds excluded from counts.')


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('evaluation output must be empty')
    protocol = json.loads(PROTOCOL.read_text())
    start = time.monotonic()
    signals = signal_cases(protocol)
    (output/'signal_results.json').write_text(json.dumps(signals, indent=2)+'\n')
    native = native_cases(protocol, output)
    result = dict(schema='tadash-trend-evaluation/1',
        protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(), sources=source_fingerprints(),
        source_baseline='333b42e9c855b071c881c6e6f96870aaae5ecd64',
        river_commit='8d1cfcf1bcb901d8b6c94e4a1454e984eee0642c',
        signal_summary=signals['summary'], native=native, elapsed_wall_s=time.monotonic()-start,
        python=sys.version, platform=platform.platform(), external_model_api_calls=0,
        clinical_validation=False, blinded_validation=False,
        interpretation='Synthetic streaming trend detection; authored signal units and thresholds; optional observer only.')
    result['accepted'] = signals['summary']['accepted'] and all(native['acceptance'].values())
    (output/'evaluation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['accepted'] else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    p.add_argument('--isolated-child', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--cold-step', type=Path, help=argparse.SUPPRESS)
    p.add_argument('--cold-output', type=Path, help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.cold_step:
        cold_step(args.cold_step, args.cold_output)
        return 0
    if args.output is None:
        p.error('--output is required')
    if args.isolated_child:
        return run(args.output.resolve())
    with tempfile.TemporaryDirectory(prefix='tadash-trend-evaluation-') as directory:
        runtime = Path(directory)/'runtime'
        shutil.copytree(ROOT, runtime, ignore=shutil.ignore_patterns('__pycache__', 'trained_circuit.json',
            'initial_affect.json', '*.sqlite*', '*.db'))
        result = subprocess.run([sys.executable, str(runtime/Path(__file__).name),
            '--output', str(args.output.resolve()), '--isolated-child'])
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
