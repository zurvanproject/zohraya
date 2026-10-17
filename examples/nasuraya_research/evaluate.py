"""Reproducible, finite integration check using fresh synthetic bodies only."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import platform
import tempfile

from .adapters import digest, geometry, monitoring_stats, project_trajectory, sensory_sample
from .integrity import ROOT, verify_sources


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def native_sources():
    root = ROOT.parents[1] / 'runtimes' / 'tadash_body'
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*.py')}


def collect(pressures, split, protocol):
    from examples.nasuraya_self_model.evaluate import fixture, request
    sequences, hashes, receipts = [], [], []
    for i, pressure in enumerate(pressures):
        body = fixture(pressure)
        hashes.append(body.checkpoint()['sha256'])
        sequence = []
        for t in range(protocol['ticks_per_sequence']):
            sequence.append(sensory_sample(body))
            q = request(body, f'{split}-{i}-{t}', protocol['duration_s'])
            receipt = body.cycle(**q)
            receipts.append(dict(event_id=receipt['event_id'], sha256=digest(receipt),
                requested=q['requested'], actual=receipt['owner']['selected_action'],
                physical_model_valid=receipt['owner']['physical_model_valid']))
        sequences.append(sequence)
    return sequences, hashes, receipts


def trajectory_events(rows):
    """Offline projection of measured decisions, NOT a live RoboRSI agent run."""
    events = []
    def add(kind, payload, turn=None):
        seq = len(events)+1
        events.append(dict(event_id=f'native-{seq}', seq=seq, run_id='native-admission-pilot',
            agent_id='nasuraya-local', turn_id=turn, type=kind, payload=payload))
    add('run_start', {'scope': 'offline projection of existing native trial records'})
    for index, row in enumerate(rows):
        turn = f'trial-{index}'
        add('turn_start', {'case_id': row['case_id'], 'arm': row['arm']}, turn)
        add('body_decision', {'choice': row['final_choice'], 'probability': row['probability']}, turn)
        add('body_result', {k: row[k] for k in ('actual_action', 'receipt_sha256', 'shadow_admitted')}, turn)
        add('turn_end', {'status': 'completed'}, turn)
    add('run_end', {'status': 'completed'})
    return events


def run(output, *, with_tensor=False):
    verify_sources()
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol_raw = (ROOT/'protocol.json').read_bytes()
    protocol = json.loads(protocol_raw)
    write(out/'frozen-protocol.json', protocol)
    before_native = native_sources()
    from examples.nasuraya_self_model.run_metacognitive import evaluate
    # Reuse existing frozen decision/experience engine. No parallel replacement.
    with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
        result = evaluate(Path(temporary)/'native-control')
    monitoring = {}
    for arm in result['arms']:
        rows = [r for r in result['rows'] if r['arm'] == arm]
        inputs = [dict(correct=r['shadow_admitted'],
                       keep_withdraw='KEEP' if r['attempted'] else 'WITHDRAW') for r in rows]
        monitoring[arm] = monitoring_stats(inputs)
        correct = [r for r in rows if r['shadow_admitted']]
        wrong = [r for r in rows if not r['shadow_admitted']]
        independent = (100*sum(r['attempted'] for r in correct)/len(correct) -
                       100*sum(r['attempted'] for r in wrong)/len(wrong)) if correct and wrong else None
        if monitoring[arm]['wd'] != independent:
            raise ValueError('independent withdrawal-count comparison')
    write(out/'native-trials.json', result)
    events = trajectory_events(result['rows'])
    projection = project_trajectory(events)
    if projection != project_trajectory(events+[events[-1]]):
        raise ValueError('projection counted duplicate event')
    if projection['summary']['n_turns'] != len(result['rows']):
        raise ValueError('projection lost turns')
    write(out/'trajectory.json', projection)
    (out/'trajectory.jsonl').write_text(''.join(json.dumps(e, sort_keys=True)+'\n' for e in events))
    summary = dict(schema=protocol['schema'], python=platform.python_version(),
        protocol_sha256=hashlib.sha256(protocol_raw).hexdigest(),
        upstream_lock_sha256=hashlib.sha256((ROOT/'upstream-lock.json').read_bytes()).hexdigest(),
        native_cases=result['held_out_cases'], native_policy_trials=result['paired_policy_trials'],
        training_test_hashes_disjoint=result['training_test_initial_hashes_disjoint'],
        held_out_memory_unchanged=result['counts_unchanged'], cold_decision_resume_equal=result['cold_resume_equal'],
        monitoring=monitoring, trajectory_turns=projection['summary']['n_turns'],
        duplicate_event_counts_once=True, model_api_calls=0, tensor_status='not_requested',
        canonical_user_state_used=False, automatic_activation=False,
        scope=protocol['scope'])
    if with_tensor:
        import torch
        from examples.nasuraya_self_model.evaluate import fixture
        from .predictive import train_observer, infer_observer, weight_state
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        geometries = [geometry(fixture(p), yaw) for p in protocol['held_out_pressures']
                      for yaw in (0., .7, -1.2)]
        write(out/'geometry.json', geometries)
        train, train_hashes, train_receipts = collect(protocol['training_pressures'], 'train', protocol)
        held, held_hashes, held_receipts = collect(protocol['held_out_pressures'], 'held', protocol)
        if set(train_hashes) & set(held_hashes):
            raise ValueError('train/test body overlap')
        write(out/'sensory-data.json', dict(train=train, held_out=held,
            training_initial_native_sha256=train_hashes, held_out_initial_native_sha256=held_hashes,
            receipts=train_receipts+held_receipts, geometry_features_are_camera_data=False))
        comparisons = []
        for seed in protocol['seeds']:
            model, trained = train_observer(train, seed=seed, steps=protocol['training_steps'])
            write(out/f'sensory-weights-{seed}.json', dict(config=__import__(
                'examples.nasuraya_research.predictive', fromlist=['config']).config(),
                state=weight_state(model), training=trained))
            measures = [dict(prior=infer_observer(model, s, iterations=0),
                             posterior=infer_observer(model, s, iterations=protocol['er_iterations'])) for s in held]
            prior = sum(x['prior']['mean_q_mse'] for x in measures)/len(measures)
            posterior = sum(x['posterior']['mean_q_mse'] for x in measures)/len(measures)
            comparisons.append(dict(training=trained, prior_mean_q_mse=prior,
                posterior_mean_q_mse=posterior, improved_reconstruction=posterior<prior,
                measures=measures))
        write(out/'sensory-comparisons.json', comparisons)
        summary.update(tensor_status='executed_cpu', torch=torch.__version__, cuda_used=False,
            geometry_checks=len(geometries), max_roundtrip_error_m=max(g['max_roundtrip_error_m'] for g in geometries),
            sensory_native_cycles=len(train_receipts)+len(held_receipts),
            sensory_train_test_hashes_disjoint=True,
            sensory_comparisons=[{k:v for k,v in r.items() if k!='measures'} for r in comparisons],
            predicted_action_vectors_executed=0,
            sensory_interpretation=protocol['predvla_measure'])
    summary['native_python_sources_unchanged'] = before_native == native_sources()
    if not summary['native_python_sources_unchanged']:
        raise ValueError('native source changed during pilot')
    write(out/'summary.json', summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--with-tensor', action='store_true')
    args = parser.parse_args()
    run(args.output, with_tensor=args.with_tensor)
