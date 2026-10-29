"""Frozen, finite evaluation against authoritative software-body outcomes.

This is a constructed temporal holdout on two synthetic body fixtures. It is
neither SAD nor a test of phenomenal consciousness. The contextual estimator
and pooled baseline see exactly the same training receipts; only the former
conditions on the pre-action physical context. No live model is called.
"""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import random

from reflection_cycle import canonical, digest
from .experience import context, metrics
from .host import BodyLoop, executed_body
from .self_knowledge import forecast_action, score_action


CATEGORIES = ('walk', 'observe', 'protect', 'other')
PROTOCOL = {
    'schema': 'nasuraya-self-knowledge-evaluation/1',
    'fixtures': ['normal', 'sleep'],
    'preferences': ['walk', 'observe'],
    'durations_s': [.1, .3],
    'warmup_rounds': 5,
    'holdout_rounds': 3,
    'shuffle_seed': 20261029,
    'order': 'round-major, then fixture, preference, duration in listed order',
    'fit': 'warmup receipts only; frozen for every holdout prediction',
    'baseline': 'same receipts, preference and duration; physical context omitted',
    'negative_control': 'shuffle training contexts within preference/duration groups',
    'scope': 'constructed two-fixture temporal holdout; no novel-world or consciousness claim',
}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def _append(path, value):
    # The forecast is on disk before the simulator is allowed to return an outcome.
    with path.open('a', encoding='utf-8') as stream:
        stream.write(canonical(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def shuffled_contexts(episodes, seed):
    """Preserve outcome/preference/duration marginals; change contexts only."""
    shuffled = deepcopy(episodes)
    groups = {}
    for index, episode in enumerate(shuffled):
        groups.setdefault((episode['preferred'], episode['duration_s']), []).append(index)
    rng = random.Random(seed)
    for indices in groups.values():
        contexts = [shuffled[i]['context'] for i in indices]
        rng.shuffle(contexts)
        for index, ctx in zip(indices, contexts):
            shuffled[index]['context'] = ctx
    return shuffled


def _argmax(distribution):
    # Fixed tie order. Ties are not converted into evidence of knowing an answer.
    return max(CATEGORIES, key=lambda action: distribution[action])


def summarize_trials(rows):
    scored = [row for row in rows if row['scored']]
    supported = [row for row in scored if row['forecast']['samples'] >= 3]
    pooled_supported = [row for row in scored if row['forecast']['pooled_samples'] >= 3]
    mean = lambda values: sum(values) / len(values) if values else None
    actual = lambda row: row['actual_action'] if row['actual_action'] in CATEGORIES else 'other'
    return {
        'attempted': len(rows),
        'scored': len(scored),
        'failed_or_unresolved': len(rows) - len(scored),
        'supported': len(supported),
        'cold': len(scored) - len(supported),
        'coverage': len(supported) / len(scored) if scored else 0.,
        'mean_brier': mean([row['score']['brier'] for row in scored]),
        'mean_pooled_brier': mean([row['score']['pooled_brier'] for row in scored]),
        'mean_shuffled_context_brier': mean([row['shuffled_score']['brier'] for row in scored]),
        'mean_zero_history_brier': mean([row['zero_history_score']['brier'] for row in scored]),
        'supported_mean_brier': mean([row['score']['brier'] for row in supported]),
        'supported_mean_pooled_brier': mean([row['score']['pooled_brier'] for row in supported]),
        'supported_accuracy': mean([int(_argmax(row['forecast']['distribution']) == actual(row))
                                    for row in supported]),
        'pooled_supported': len(pooled_supported),
        'pooled_supported_accuracy': mean([
            int(_argmax(row['forecast']['pooled_distribution']) == actual(row))
            for row in pooled_supported]),
        'observed_outcome_counts': {action: sum(actual(row) == action for row in scored)
                                   for action in CATEGORIES},
        'brier_definition': 'sum over four categories of (probability - one_hot_outcome)^2; lower is better',
    }


def finalize_evaluation(output_dir):
    """Check completed artifacts; correctness never depends on winning a score."""
    output = Path(output_dir)
    summary = json.loads((output / 'summary.json').read_text())
    protocol = json.loads((output / 'protocol.json').read_text())
    training = json.loads((output / 'training.json').read_text())
    predictions = [json.loads(line) for line in (output / 'predictions.jsonl').read_text().splitlines()]
    rows = [json.loads(line) for line in (output / 'trials.jsonl').read_text().splitlines()]
    heldout = [row for row in rows if row['phase'] == 'holdout']
    warmup = [row for row in rows if row['phase'] == 'warmup']
    # Replay only the estimator, never the body. Check both the saved probability
    # vectors against their prior evidence and each saved score against its vector.
    # Reporting uses the re-derived vectors/scores even if an artifact was changed.
    prior, rescored = [], []
    forecasts_match, scores_match, prior_stamps_match = True, True, True
    pairs = (('forecast', 'score'), ('shuffled_forecast', 'shuffled_score'),
             ('zero_history_forecast', 'zero_history_score'))
    for row in rows:
        history = prior if row['phase'] == 'warmup' else training['episodes']
        checked = deepcopy(row)
        prior_stamps_match &= (row['training_sha256'] == digest(history)
                               and row['training_count'] == len(history))
        try:
            kwargs = dict(context=row['context'], preferred=row['preferred'], duration_s=row['duration_s'])
            rebuilt = (forecast_action(history, **kwargs),
                forecast_action(shuffled_contexts(history, PROTOCOL['shuffle_seed']), **kwargs),
                forecast_action([], **kwargs))
            for (forecast_key, score_key), expected_forecast in zip(pairs, rebuilt):
                forecasts_match &= row[forecast_key] == expected_forecast
                checked[forecast_key] = expected_forecast
                if row['scored']:
                    try:
                        scores_match &= row[score_key] == score_action(
                            row[forecast_key], row['actual_action'], source=row['source'])
                    except (KeyError, TypeError, ValueError):
                        scores_match = False
                    checked[score_key] = score_action(expected_forecast,
                        row['actual_action'], source=row['source'])
                else:
                    scores_match &= row[score_key] is None
                    checked[score_key] = None
        except (KeyError, TypeError, ValueError):
            forecasts_match = scores_match = False
            checked['scored'] = False
        rescored.append(checked)
        if row['phase'] == 'warmup' and row['scored']:
            prior.append(dict(id=row['id'], kind='observed_software_outcome',
                context=row['context'], preferred=row['preferred'], duration_s=row['duration_s'],
                actual_action=row['actual_action'], source=row['source']))
    summary['warmup'] = summarize_trials([row for row in rescored if row['phase'] == 'warmup'])
    summary['holdout'] = summarize_trials([row for row in rescored if row['phase'] == 'holdout'])
    score_summary = summary['holdout']
    delta = (score_summary['mean_pooled_brier'] - score_summary['mean_brier']
             if score_summary['scored'] else None)
    summary['heldout_brier_improvement_absolute'] = delta
    summary['context_helped_on_this_constructed_holdout'] = delta is not None and delta > 0
    sessions = len(PROTOCOL['fixtures']) * len(PROTOCOL['preferences']) * len(PROTOCOL['durations_s'])
    expected_training = sessions * PROTOCOL['warmup_rounds']
    expected_holdout = sessions * PROTOCOL['holdout_rounds']
    expected = expected_training + expected_holdout
    training_ids = {row['id'] for row in training['episodes']}
    expected_order = [(round_index, fixture, preferred, duration)
        for round_index in range(PROTOCOL['warmup_rounds'] + PROTOCOL['holdout_rounds'])
        for fixture in PROTOCOL['fixtures'] for preferred in PROTOCOL['preferences']
        for duration in PROTOCOL['durations_s']]
    checks = dict(
        all_native_cycles_completed=summary['actual_native_cycles'] == expected == summary['expected_native_cycles'],
        no_failed_or_unresolved=all(row['scored'] for row in rows)
            and summary['warmup']['failed_or_unresolved'] == summary['holdout']['failed_or_unresolved'] == 0,
        budgets_exhausted=len(summary['budgets_remaining']) == sessions
            and all(value == 0 for value in summary['budgets_remaining'].values()),
        expected_split=len(warmup) == expected_training and len(heldout) == expected_holdout,
        complete_unique_trials=len(rows) == len(predictions) == expected
            and len({row['id'] for row in rows}) == expected,
        forecasts_preserved=len(rows) == len(predictions)
            and all(all(row.get(k) == v for k, v in prediction.items())
                    for prediction, row in zip(predictions, rows)),
        expected_training=len(training['episodes']) == summary['training_receipts'] == expected_training,
        training_is_warmup_only=training_ids == {row['id'] for row in warmup}
            and training_ids.isdisjoint({row['id'] for row in heldout})
            and training['episodes'] == prior,
        frozen_training=training['sha256'] == digest(training['episodes']) == summary['training_sha256']
            and all(row['training_sha256'] == training['sha256']
                    and row['training_count'] == expected_training for row in heldout),
        protocol_preserved=protocol == dict(PROTOCOL, protocol_sha256=digest(PROTOCOL))
            and summary['protocol_sha256'] == digest(PROTOCOL),
        fixed_trial_order=[(row['round'], row['fixture'], row['preferred'], row['duration_s'])
            for row in rows] == expected_order
            and all(row['phase'] == ('warmup' if row['round'] < PROTOCOL['warmup_rounds']
                    else 'holdout') for row in rows),
        scores_match_frozen_forecasts=bool(scores_match),
        forecasts_match_prior_evidence=bool(forecasts_match),
        prior_evidence_stamps_match=bool(prior_stamps_match),
    )
    summary['validation_checks'] = checks
    summary['validation_passed'] = all(checks.values())
    _write(output / 'summary.json', summary)
    return summary


def run_evaluation(output_dir):
    """Execute the predeclared 64 cycles; never tune or refit on heldout outcomes."""
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    protocol = deepcopy(PROTOCOL)
    protocol['protocol_sha256'] = digest(PROTOCOL)
    _write(output / 'protocol.json', protocol)
    training, rows = [], []
    sessions = []
    total_rounds = protocol['warmup_rounds'] + protocol['holdout_rounds']
    with ExitStack() as stack:
        for fixture in protocol['fixtures']:
            for preferred in protocol['preferences']:
                for duration in protocol['durations_s']:
                    name = f'{fixture}-{preferred}-{int(duration * 10)}'
                    loop = stack.enter_context(BodyLoop.start(output / (name + '.sqlite'),
                        fixture=fixture, max_actions=total_rounds))
                    sessions.append((name, fixture, preferred, duration, loop))
        frozen = frozen_hash = None
        for round_index in range(total_rounds):
            is_holdout = round_index >= protocol['warmup_rounds']
            if is_holdout and frozen is None:
                frozen = deepcopy(training)
                frozen_hash = digest(frozen)
                _write(output / 'training.json', dict(episodes=frozen, sha256=frozen_hash))
            history = frozen if is_holdout else training
            for name, fixture, preferred, duration, loop in sessions:
                snapshot = loop.observe()
                ctx = context(metrics(snapshot))
                decision_id = f'{name}-round-{round_index}'
                forecast = forecast_action(history, context=ctx,
                    preferred=preferred, duration_s=duration)
                shuffled = forecast_action(shuffled_contexts(history, protocol['shuffle_seed']),
                    context=ctx, preferred=preferred, duration_s=duration)
                zero = forecast_action([], context=ctx, preferred=preferred, duration_s=duration)
                before = dict(id=decision_id, phase='holdout' if is_holdout else 'warmup',
                    round=round_index, fixture=fixture, preferred=preferred,
                    duration_s=duration, context=ctx,
                    before_checkpoint_sha256=snapshot['checkpoint_sha256'],
                    training_sha256=digest(history), training_count=len(history),
                    forecast=deepcopy(forecast), shuffled_forecast=deepcopy(shuffled),
                    zero_history_forecast=deepcopy(zero))
                _append(output / 'predictions.jsonl', before)
                receipt = loop.step(decision_id=decision_id, duration_s=duration,
                                    preferred_action=preferred)
                record = loop.engine.get(decision_id)
                ran = executed_body(record)
                row = dict(before, scored=ran, actual_action=receipt['actual_action'],
                           receipt_status=receipt['status'])
                if ran:
                    source = 'native-decision://' + decision_id + '/' + digest(record)
                    row.update(score=score_action(forecast, receipt['actual_action'], source=source),
                        shuffled_score=score_action(shuffled, receipt['actual_action'], source=source),
                        zero_history_score=score_action(zero, receipt['actual_action'], source=source),
                        source=source, body_audit=receipt['body_audit'],
                        after_checkpoint_sha256=receipt['self_model_after']['checkpoint_sha256'])
                    if not is_holdout:
                        training.append(dict(id=decision_id, kind='observed_software_outcome',
                            context=ctx, preferred=preferred, duration_s=duration,
                            actual_action=receipt['actual_action'], source=source))
                else:
                    row.update(score=None, shuffled_score=None, zero_history_score=None)
                _append(output / 'trials.jsonl', row)
                rows.append(row)
                if is_holdout and digest(frozen) != frozen_hash:
                    raise AssertionError('heldout data contaminated the frozen training history')
        native_cycles = sum(loop.status()['completed_cycles'] for *_, loop in sessions)
        budgets_remaining = {name: loop.status()['actions_remaining'] for name, *_, loop in sessions}
    warmup = summarize_trials([row for row in rows if row['phase'] == 'warmup'])
    heldout = summarize_trials([row for row in rows if row['phase'] == 'holdout'])
    delta = (heldout['mean_pooled_brier'] - heldout['mean_brier']
             if heldout['scored'] else None)
    summary = dict(schema=protocol['schema'], scope=protocol['scope'],
        protocol_sha256=protocol['protocol_sha256'], training_sha256=frozen_hash,
        training_receipts=len(training), actual_native_cycles=native_cycles,
        expected_native_cycles=len(sessions) * total_rounds,
        budgets_remaining=budgets_remaining, warmup=warmup, holdout=heldout,
        heldout_brier_improvement_absolute=delta,
        context_helped_on_this_constructed_holdout=delta is not None and delta > 0,
        all_forecasts_reserved_before_execution=True, holdout_outcomes_used_for_fitting=False,
        model_api_calls=0, physical_actuator_calls=0,
        limitations=[
            'Only two deterministic synthetic fixture families; no human emotional labels.',
            'Temporal holdout uses subsequent cycles of the same session families, not unseen environments.',
            'Pooled control is a frequency estimator with the same receipts, not another language model.',
            'A shuffled-context control is one fixed permutation, not a significance test.',
            'Lower Brier measures forecasting in this simulator, not subjective awareness or privileged introspection.',
        ])
    _write(output / 'summary.json', summary)
    return finalize_evaluation(output)
