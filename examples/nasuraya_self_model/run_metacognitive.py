"""Frozen, deterministic knowing/doing challenge on synthetic native bodies."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .evaluate import fixture, request, prepare_defaults
from .monitor import SelfModel, snapshot, ROOT, digest
from .metacognitive_control import ControlTrial, ControlJournal, ARMS, sources
from persistent_embodiment_v1 import atomic_json

PROTOCOL = Path(__file__).with_name('metacognitive_protocol.json')


def admitted(receipt):
    return (receipt['owner']['selected_action'] == 'walk' and
            receipt['owner']['physical_model_valid'])


def train(path, pressures):
    model = SelfModel.create(path)
    hashes = []
    for index, pressure in enumerate(pressures):
        body = fixture(pressure)
        hashes.append(body.checkpoint()['sha256'])
        q = request(body, f'train:{index}')
        model.begin(body, q)
        model.finish(q['event_id'], body, body.cycle(**q))
    return model, hashes


def summarize(rows):
    out = {}
    for arm in ARMS:
        values = [r for r in rows if r['arm'] == arm]
        n = len(values)
        attempts = sum(r['attempted'] for r in values)
        failures = sum(r['attempted'] and not r['shadow_admitted'] for r in values)
        probabilities = [r for r in values if r['probability'] is not None]
        out[arm] = dict(cases=n, attempted=attempts, deferred=n-attempts,
            attempt_coverage=attempts/n, failed_attempts=failures,
            failed_attempts_per_case=failures/n,
            failures_conditional_on_attempts=failures/attempts if attempts else None,
            deferred_admissible=sum(not r['attempted'] and r['shadow_admitted'] for r in values),
            brier=sum((r['probability']-int(r['shadow_admitted']))**2 for r in probabilities)/len(probabilities)
                if probabilities else None,
            read_only_refreshes=sum(r['read_only_refreshes'] for r in values),
            total_owner_time_s=sum(r['owner_time_s'] for r in values),
            total_fuel_debit_J=sum(r['fuel_debit_J'] for r in values))
    return out


def cold(saved, output):
    trial = ControlTrial.restore(json.loads(Path(saved).read_text()))
    atomic_json(output, dict(checkpoint_sha256=trial.checkpoint()['sha256'],
                             decision=trial.decision(), native_actions_executed=0))


def evaluate(output):
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL.read_text())
    atomic_json(out/'frozen-protocol.json', protocol)
    prepare_defaults()
    model, train_hashes = train(out/'self-model.sqlite', protocol['training_sleep_pressure'])
    frozen = model.verify()
    atomic_json(out/'training-state.json', frozen)
    rows, cases, test_hashes = [], [], set()
    cold_done = False
    for pressure in protocol['held_out_sleep_pressure']:
        base = fixture(pressure)
        old_observation = snapshot(base)
        prelude = request(base, f'prelude:{pressure}', protocol['initial_observation_age_s'])
        prelude.update(requested='observe', external={})
        base.cycle(**prelude)
        for duration in protocol['held_out_duration_s']:
            for intervention in protocol['held_out_interventions']:
                case_id = f'case-{len(cases):02d}'
                initial = base.checkpoint()
                test_hashes.add(initial['sha256'])
                q = request(base, case_id, duration)
                if intervention == 'zero_friction':
                    q['external']['native'] = dict(friction=dict(L=0., R=0.))
                trial_dir = out/case_id
                trial_dir.mkdir()
                # Plan every arm before measuring any matching walk outcome.
                plans = {}
                for arm in ARMS:
                    body = type(base).restore(initial)
                    trial = ControlTrial.start(body, model, q, old_observation, arm=arm)
                    saved = trial.checkpoint()
                    atomic_json(trial_dir/f'{arm}-before.json', saved)
                    plans[arm] = trial
                plan_hashes = {a: t.checkpoint()['sha256'] for a, t in plans.items()}
                if not cold_done:
                    subprocess.run([sys.executable, '-m', 'examples.nasuraya_self_model.run_metacognitive',
                        'cold', '--saved', str(trial_dir/'control-before.json'),
                        '--output', str(out/'cold-resume.json')], cwd=ROOT, check=True)
                    resumed = json.loads((out/'cold-resume.json').read_text())
                    assert resumed == dict(checkpoint_sha256=plan_hashes['control'],
                        decision=plans['control'].decision(), native_actions_executed=0)
                    cold_done = True
                shadow = type(base).restore(initial)
                shadow_receipt = shadow.cycle(**q)
                label = admitted(shadow_receipt)
                atomic_json(trial_dir/'shadow-receipt.json', shadow_receipt)
                cases.append(dict(case_id=case_id, pressure=pressure, duration_s=duration,
                    intervention=intervention, initial_native_sha256=initial['sha256'],
                    decision_checkpoint_sha256=plan_hashes, shadow_admitted=label,
                    shadow_receipt_sha256=digest(shadow_receipt)))
                for arm, trial in plans.items():
                    decision = trial.decision()
                    attempted = decision['choice'] == 'request_walk'
                    before_time = trial.body.owner.physical.state.time_s
                    before_fuel = trial.body.owner.owner.body.state.fuel_J
                    journal = ControlJournal.create(trial_dir/f'{arm}.sqlite', trial)
                    receipt = None
                    if attempted:
                        receipt = journal.step(event_id=q['event_id'], expected_head=plan_hashes[arm])
                        trial = journal.load()
                        # Independent execution from the same initial checkpoint.
                        assert receipt == shadow_receipt
                    else:
                        assert journal.load().body.checkpoint() == initial
                    rows.append(dict(case_id=case_id, arm=arm, attempted=attempted,
                        initial_choice=trial.contract['initial_decision']['choice'],
                        final_choice=decision['choice'], reasons=decision['reasons'],
                        probability=decision['probability'], shadow_admitted=label,
                        current_restrictions=snapshot(type(base).restore(initial))['audit']['walking_restrictions'],
                        context_samples=decision['report']['inferred']['samples'] if decision['report'] else None,
                        read_only_refreshes=int(trial.contract['fresh_observation'] is not None),
                        actual_action=receipt['owner']['selected_action'] if receipt else None,
                        physical_model_valid=receipt['owner']['physical_model_valid'] if receipt else None,
                        owner_time_s=trial.body.owner.physical.state.time_s-before_time,
                        fuel_debit_J=before_fuel-trial.body.owner.owner.body.state.fuel_J,
                        checkpoint_sha256=trial.checkpoint()['sha256'],
                        receipt_sha256=digest(receipt) if receipt else None))
    assert model.verify() == frozen
    assert not set(train_hashes) & test_hashes
    native_files = ROOT/'runtimes/tadash_body'
    result = dict(schema=protocol['schema'], protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        sources=sources(), training_episodes=len(train_hashes), held_out_cases=len(cases),
        paired_policy_trials=len(rows), shadow_label_trials=len(cases),
        counts_unchanged=True, training_test_initial_hashes_disjoint=True,
        cold_resume_equal=cold_done, fixed_prior_brier=.25,
        arms=summarize(rows), cases=cases, rows=rows,
        native_import_manifest_sha256=hashlib.sha256((native_files/'IMPORT_PROVENANCE.json').read_bytes()).hexdigest(),
        no_live_model_api=True, identity_or_native_equations_modified=False,
        scope=protocol['scope'])
    atomic_json(out/'results.json', result)
    print(json.dumps(dict(held_out_cases=len(cases), paired_policy_trials=len(rows),
                         arms=result['arms']), indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('evaluate', 'cold'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--saved')
    args = parser.parse_args()
    if args.mode == 'cold':
        cold(args.saved, args.output)
    else:
        evaluate(args.output)
