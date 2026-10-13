"""Frozen, controlled comparison: native loop versus bounded self-maintenance.

Both arms use the same source-pinned synthetic UnifiedBody and starting fixture.
No API, actuator, private checkpoint, or biological measurements.
"""
from pathlib import Path
import json

from .host import BodyLoop
from .self_maintenance import SelfMaintenance


class DeliberateProcessStop(RuntimeError):
    pass


def compact(receipt):
    return {
        'requested': receipt['requested_action'],
        'actual': receipt['actual_action'],
        'vetoed': receipt['requested_action'] != receipt['actual_action'],
        'status': receipt['status'],
        'checkpoint_sha256': receipt['self_model_after']['checkpoint_sha256']
    }


def paired_case(output, fixture):
    """Two decisions per condition; close/reopen the SQLite between decisions."""
    baseline_db = output / ('baseline-' + fixture + '.sqlite')
    supervised_db = output / ('supervised-' + fixture + '.sqlite')

    with BodyLoop.start(baseline_db, fixture=fixture, mode='bounded', max_actions=2) as body:
        baseline_initial = body.observe()
        first_base = compact(body.step(decision_id='baseline-1'))
    with BodyLoop(baseline_db) as body:
        baseline_reopen_sha = body.status()['self_model']['checkpoint_sha256']
        body.observe()
        second_base = compact(body.step(decision_id='baseline-2'))
        base_remaining = body.status()['actions_remaining']

    with BodyLoop.start(supervised_db, fixture=fixture, mode='bounded', max_actions=2) as body:
        managed_initial = body.observe()
        if baseline_initial['checkpoint_sha256'] != managed_initial['checkpoint_sha256']:
            raise AssertionError('unequal starting body checkpoints')
        supervisor = SelfMaintenance(body, goal_id='paired-'+fixture, target_cycles=2)
        native_step = body.step
        committed_first = []
        def stop_after_commit(**kwargs):
            receipt = native_step(**kwargs)
            committed_first.append(compact(receipt))
            raise DeliberateProcessStop('injected stop after native commit, before supervisor receipt')
        body.step = stop_after_commit
        try:
            supervisor.run()
        except DeliberateProcessStop:
            pass
        if len(committed_first) != 1:
            raise AssertionError('injected stop did not commit exactly one native cycle')

    with BodyLoop(supervised_db) as body:
        before_restart = body.status()
        if before_restart['completed_cycles'] != 1:
            raise AssertionError('restart did not retain the first native cycle')
        supervisor = SelfMaintenance(body, goal_id='paired-'+fixture, target_cycles=2)
        final = supervisor.run()
        after_restart = body.status()
        verified_again = supervisor.run()
        if verified_again['completed_cycles'] != 2 or after_restart['completed_cycles'] != 2:
            raise AssertionError('bounded goal was replayed or incompletely recovered')
        if final['status'] != 'completed' or final['completed_cycles'] != 2:
            raise AssertionError('goal not completed')
        supervised_receipts = [
            {'requested': row['requested_action'], 'actual': row['actual_action'],
             'vetoed': row['vetoed'], 'checkpoint_sha256': row['after_sha']}
            for row in final['history']
        ]
        if supervised_receipts[0]['checkpoint_sha256'] != committed_first[0]['checkpoint_sha256']:
            raise AssertionError('recovery altered first committed effect')
        supervised_remaining = after_restart['actions_remaining']

    return {
        'fixture': fixture, 'initial_checkpoint_equal': True,
        'baseline': {'first': first_base, 'second': second_base,
                     'restart_retained_first': baseline_reopen_sha == first_base['checkpoint_sha256'],
                     'actions_remaining': base_remaining,
                     'veto_count': sum(row['vetoed'] for row in (first_base, second_base))},
        'supervised': {'first': supervised_receipts[0], 'second': supervised_receipts[1],
                       'restart_retained_first': before_restart['self_model']['checkpoint_sha256'] == committed_first[0]['checkpoint_sha256'],
                       'actions_remaining': supervised_remaining,
                       'veto_count': sum(row['vetoed'] for row in supervised_receipts),
                       'completed_cycles': final['completed_cycles'],
                       'identity_version': final['identity_version'],
                       'extra_actions_after_duplicate_resume': verified_again['completed_cycles'] - final['completed_cycles']},
    }


def run_benchmark(output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    scenarios = [paired_case(out, fixture) for fixture in ('normal', 'sleep')]
    a, b = scenarios
    # Concrete fixture-specific assertions, not an unconstrained statistical claim.
    if a['baseline']['first']['requested'] != 'walk' or a['supervised']['first']['requested'] != 'walk':
        raise AssertionError('normal-fixture parity changed')
    if b['baseline']['first']['requested'] != 'walk' or b['supervised']['first']['requested'] != 'observe':
        raise AssertionError('sleep-pressure preferrence contrast missing')
    if b['baseline']['veto_count'] <= b['supervised']['veto_count']:
        raise AssertionError('no reduction in motion veto requests in sleep fixture')
    if not all(case[arm]['restart_retained_first'] for case in scenarios for arm in ('baseline', 'supervised')):
        raise AssertionError('checkpoint lost across restart')
    if not all(case[arm]['actions_remaining'] == 0 for case in scenarios for arm in ('baseline', 'supervised')):
        raise AssertionError('persistent action budget mismatch')
    report = {
        'schema': 'nasuraya-frozen-paired-benchmark/1',
        'scope': '2 manually specified deterministic synthetic fixtures, not a blinded or external benchmark',
        'endpoint': 'native action requests and veto rate, not calibrated safety, intelligence or consciousness',
        'scenarios': scenarios,
        'difference_in_veto_count_sleep': b['baseline']['veto_count'] - b['supervised']['veto_count'],
        'api_calls': 0, 'live_biology': False,
        'no_duplicate_effect_after_restart': True,
    }
    (out / 'paired_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
    return report
