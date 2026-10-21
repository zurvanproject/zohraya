"""Explicit sensory-only rerun using a completed local synthetic pilot.

This does not issue a native action. Reusing recorded inputs is not fresh body
execution, and neither input hashes nor this helper authenticate a hostile host.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .adapters import digest, monitoring_stats, project_trajectory
from .evaluate import write
from .integrity import ROOT, verify_sources
from .predictive import config, train_observer, infer_observer, weight_state, restore_observer


def refit(source, output):
    verify_sources()
    import torch
    source, output = Path(source).resolve(), Path(output).resolve()
    # A fixed input set; no executable checkpoint, SQLite, user state or glob.
    names = ('summary.json', 'frozen-protocol.json', 'native-trials.json',
             'trajectory.json', 'trajectory.jsonl', 'geometry.json', 'sensory-data.json')
    raw = {}
    for name in names:
        p = source/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 2*1024*1024:
            raise ValueError('completed bounded regular pilot inputs required')
        raw[name] = p.read_bytes()
    summary, protocol, trials, data = [json.loads(raw[n]) for n in
        ('summary.json', 'frozen-protocol.json', 'native-trials.json', 'sensory-data.json')]
    if (protocol != json.loads((ROOT/'protocol.json').read_text()) or
            summary['protocol_sha256'] != hashlib.sha256((ROOT/'protocol.json').read_bytes()).hexdigest() or
            summary['tensor_status'] != 'executed_cpu' or
            not summary['held_out_memory_unchanged'] or not summary['native_python_sources_unchanged'] or
            len(data['train']) != len(protocol['training_pressures']) or
            len(data['held_out']) != len(protocol['held_out_pressures']) or
            set(data['training_initial_native_sha256']) & set(data['held_out_initial_native_sha256'])):
        raise ValueError('completed matching protocol and disjoint sensory inputs required')
    events = [json.loads(x) for x in raw['trajectory.jsonl'].splitlines()]
    if project_trajectory(events) != json.loads(raw['trajectory.json']):
        raise ValueError('recorded trajectory projection mismatch')
    for arm in trials['arms']:
        rows = [r for r in trials['rows'] if r['arm'] == arm]
        if monitoring_stats([dict(correct=r['shadow_admitted'],
            keep_withdraw='KEEP' if r['attempted'] else 'WITHDRAW') for r in rows]) != summary['monitoring'][arm]:
            raise ValueError('recorded monitoring statistic mismatch')
    output.mkdir(parents=True, exist_ok=False)
    for name in names:
        if name != 'summary.json':
            (output/name).write_bytes(raw[name])
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    comparisons = []
    for seed in protocol['seeds']:
        model, trained = train_observer(data['train'], seed=seed, steps=protocol['training_steps'])
        saved = dict(config=config(), state=weight_state(model), training=trained)
        write(output/f'sensory-weights-{seed}.json', saved)
        restored = restore_observer(json.loads((output/f'sensory-weights-{seed}.json').read_text()))
        measures = [dict(prior=infer_observer(restored, s, iterations=0),
            posterior=infer_observer(restored, s, iterations=protocol['er_iterations'])) for s in data['held_out']]
        prior = sum(x['prior']['mean_q_mse'] for x in measures)/len(measures)
        posterior = sum(x['posterior']['mean_q_mse'] for x in measures)/len(measures)
        comparisons.append(dict(training=trained, prior_mean_q_mse=prior,
            posterior_mean_q_mse=posterior, improved_reconstruction=posterior<prior, measures=measures))
    write(output/'sensory-comparisons.json', comparisons)
    summary['sensory_comparisons'] = [{k:v for k,v in r.items() if k!='measures'} for r in comparisons]
    summary['sensory_refit'] = dict(reason='explicitly freeze action head against sensory-branch gradients',
        source_files={k:hashlib.sha256(v).hexdigest() for k,v in raw.items()},
        native_cycles_executed_this_refit=0, source_native_cycles=summary['sensory_native_cycles'],
        weights_restored_from_json=True)
    write(output/'summary.json', summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    refit(args.source, args.output)
