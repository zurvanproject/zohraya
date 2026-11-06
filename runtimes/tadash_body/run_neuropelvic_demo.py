"""Run matched coupled/ablated body trajectories using generated defaults only."""
import argparse
from copy import deepcopy
import csv
from datetime import timedelta
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from synthetic_fixture import prepare_defaults, synthetic_body
from persistent_embodiment_v1 import instant
from neuropelvic_body import NeuroPelvicBody, fingerprints


def run(*, output, seconds=20, isolated=True):
    if isolated:
        # Work in a fresh tree so generated defaults never replace user state.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory(prefix='tadash-neuropelvic-') as directory:
            root = Path(directory) / 'runtime'
            shutil.copytree(Path(__file__).resolve().parent, root,
                ignore=shutil.ignore_patterns('__pycache__', 'trained_circuit.json',
                                              'initial_affect.json', '*.sqlite*', '*.db'))
            result = subprocess.run([sys.executable, str(root / Path(__file__).name),
                '--output', str(output.resolve()), '--seconds', str(seconds),
                '--isolated-child'], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return json.loads(result.stdout)
    prepare_defaults()
    template = synthetic_body()
    started = time.monotonic()
    rows, summaries = [], {}
    for name, coupling in [('coupled', True), ('ablated', False)]:
        body = NeuroPelvicBody(deepcopy(template), coupling=coupling)
        for index in range(seconds):
            neuro = dict(source_id='synthetic-neuropelvic-demo', kind='declared_simulated_input',
                         start=index == 0, intensity=.95, rhythm=.70, breath_cue=.8, attention=.7)
            record = body.cycle(event_id='demo-' + str(index + 1),
                at_utc=(instant(body.body.owner.wall_utc) + timedelta(seconds=1)).isoformat(),
                duration_s=1., neuro=neuro, expected_revision=body.revision)
            rows.append(dict(scenario=name, elapsed_s=index + 1,
                phase=record['neuropelvic']['phase'], peaks=record['peak_count'],
                sidecar_arousal=record['neuropelvic']['arousal'],
                sidecar_pelvic_tone=record['neuropelvic']['pelvic_tone'],
                source_body_time_s=record['body_feedback']['sampled_at_body_s'],
                native_RR=record['after_body']['RR'], native_HR=record['after_body']['HR'],
                native_muscle_tone=record['after_body']['muscle_tone'],
                native_pain=record['after_body']['pain'],
                native_balance=record['after_body']['balance'],
                requested_action=record['requested_action'], actual_action=record['selected_action'],
                achieved_slow_breath_ticks=record['achieved_slow_breath_ticks'],
                energy_error_J=record['audit']['energy_error_J'],
                water_error_L=record['audit']['water_error_L'], owner_ticks=record['owner_ticks']))
        checkpoint = body.checkpoint()
        resumed = NeuroPelvicBody.restore(json.loads(json.dumps(checkpoint, sort_keys=True)))
        assert resumed.checkpoint() == checkpoint
        summaries[name] = dict(peak_count=body.model.peak_count,
            final_neuropelvic=record['neuropelvic'], final_body=record['after_body'],
            events=body.model.events, json_roundtrip=True, simulated_seconds=seconds,
            native_owner_ticks=sum(r['owner_ticks'] for r in rows if r['scenario'] == name))
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'traces.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    coupled = [r for r in rows if r['scenario'] == 'coupled']
    ablated = [r for r in rows if r['scenario'] == 'ablated']
    slow = [r for r in coupled if r['actual_action'] == 'slow_breath']
    comparison = dict(
        actual_slow_breath_cycles=len(slow),
        achieved_slow_breath_ticks=sum(r['achieved_slow_breath_ticks'] for r in coupled),
        min_native_RR_coupled=min(r['native_RR'] for r in coupled),
        min_native_RR_ablated=min(r['native_RR'] for r in ablated),
        final_native_RR_delta=coupled[-1]['native_RR'] - ablated[-1]['native_RR'],
        final_native_HR_delta=coupled[-1]['native_HR'] - ablated[-1]['native_HR'],
        final_native_muscle_tone_delta=coupled[-1]['native_muscle_tone'] - ablated[-1]['native_muscle_tone'],
        maximum_energy_error_J=max(r['energy_error_J'] for r in rows),
        maximum_water_error_L=max(r['water_error_L'] for r in rows))
    acceptance = dict(
        exactly_one_peak_each=all(s['peak_count'] == 1 for s in summaries.values()),
        final_sidecar_restored=all(s['final_neuropelvic']['phase'] == 'baseline' for s in summaries.values()),
        coupling_changes_native_respiration=comparison['min_native_RR_coupled'] < comparison['min_native_RR_ablated'],
        actual_slow_breath_was_executed=comparison['achieved_slow_breath_ticks'] > 0,
        native_ticks_not_duplicated=all(s['native_owner_ticks'] == seconds * 10 for s in summaries.values()),
        conservation=comparison['maximum_energy_error_J'] < 5e-5 and comparison['maximum_water_error_L'] < 1e-8)
    result = dict(schema='tadash-neuropelvic-evaluation/1',
        fixture='generated deterministic V2 defaults; seven-second warm-up excluded',
        body_baseline_commit='97ae493d72bb83525582d672c09e4b853b18a808',
        wrapper_source_fingerprints=fingerprints(), python=sys.version, platform=platform.platform(),
        execution_wall_seconds=time.monotonic() - started, scenarios=summaries,
        comparison=comparison, acceptance=acceptance,
        feedback_latency='previous simulator snapshot; at most one 1-second wrapper cycle',
        new_physical_stock=False, empirical_validation=False, external_model_api_used=False,
        full_pelvic_floor_actuator=False,
        limitation='Native body remains the existing reduced 195 kg solver; this is not the 78 kg MuJoCo atlas.')
    (output / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if not all(acceptance.values()):
        raise RuntimeError('coupled demonstration acceptance failed: ' + str(acceptance))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=int, default=20)
    p.add_argument('--isolated-child', action='store_true', help=argparse.SUPPRESS)
    args = p.parse_args()
    if not 20 <= args.seconds <= 60:
        p.error('seconds must be between 20 and 60')
    if args.output.exists() and any(args.output.iterdir()):
        p.error('output directory must be empty')
    print(json.dumps(run(output=args.output, seconds=args.seconds,
                         isolated=not args.isolated_child), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
