"""Reproduce the router decision from archived PR #78 evidence, offline only."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import audit_paired_comparison as audit
from . import paired_comparison as p, prediction_router as router, self_model_step as m, session as s

SOURCE_COMMIT = '90b16750a36af6980dad24fedd7a0896bf631a76'
EXPIRES_AT = '2026-10-30T00:00:00+00:00'


def current_scope_sha256():
    """Bind future validation to local predictor/config and verified body sources."""
    root = Path(__file__).resolve().parents[2]
    files = [Path(module.__file__) for module in (p, m, s, router)]
    for directory in ('runtimes/tadash_body', 'examples/nasuraya_body_loop'):
        files.extend(path for path in (root / directory).rglob('*')
                     if path.is_file() and path.suffix in ('.py', '.json', '.zip'))
    return s.digest({str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(set(files))})


def evaluate(*, as_of):
    if as_of.tzinfo is None:
        raise ValueError('timezone-aware assessment time required')
    root = s.ROOT / 'results'
    state = json.loads((root / 'paired-comparison.json').read_text())
    prior = json.loads((root / 'self-model-step.json').read_text())
    verified = audit.audit(state, prior)
    ticket = json.loads((s.ROOT / 'paired-authorization.json').read_text())
    if ticket != dict(session='paired-cost-comparison', total_max_usd=1, prior_commit=p.PRIOR,
                      contract_sha256=s.digest(p.CONTRACT)):
        raise ValueError('existing authorization changed')
    scope = current_scope_sha256()
    history = copy.deepcopy(state['calibration'])
    scores, rows = [], []
    for number, round_ in enumerate(state['rounds'], 1):
        # Route all forecasts BEFORE exposing this round's receipts to scoring.
        result = router.route_predictions(round_['before'], history, scope_sha256=scope)
        forecasts = {value['id']: value for value in result['predictions']}
        for record in round_['records']:
            forecast = forecasts[record['id']]
            actual = m.minimum(record['receipt']['self_model_after'])
            score = p.score(forecast, actual, record['receipt']['actual_action'])
            if score != record['scores']['nearest_episode']:
                raise ValueError('default router diverged from preserved memory baseline')
            scores.append(score)
            rows.append(dict(round=number, id=record['id'], forecast=forecast, score=score))
        for record in round_['records']:
            o = record['observation']
            history.append(dict(id=o['id'], fixture=o['fixture'], duration_s=o['duration_s'],
                                observed=o['observed'], actual_metrics=m.minimum(record['receipt']['self_model_after']),
                                actual_action=record['receipt']['actual_action']))
    action_correct = sum(score['action_correct'] for score in scores)
    memory = verified['assessment']['nearest_episode']['metric_mae']
    api = verified['assessment']['api']['metric_mae']
    reserved = state['total_reserved_micro_usd']
    return dict(
        schema='nasuraya-router-offline-assessment/1', assessed_at=as_of.isoformat(),
        evidence_source_commit=SOURCE_COMMIT, evidence_sha256=s.digest(state), scope_sha256=scope,
        policy=router.POLICY, policy_sha256=s.digest(router.POLICY),
        evidence_kind='retrospective replay; not independent validation or measured new improvement',
        archived_audit_status=verified['status'], historical_assessment=verified['assessment'],
        historical_rounds=verified['rounds'],
        historical_api_numeric_gain=dict(absolute=memory-api, relative=(memory-api)/memory),
        router_replay=dict(n=len(rows), metric_mae=sum(score['metric_mae'] for score in scores)/len(scores),
                           action_correct=action_correct, new_api_calls=0, incremental_estimated_micro_usd=0),
        numeric_gate=router.evaluate_numeric_evidence(None, scope_sha256=scope),
        authorization=dict(
            expires_at_exclusive=EXPIRES_AT,
            within_time_window=datetime(2026, 10, 23, tzinfo=timezone.utc) <= as_of < datetime.fromisoformat(EXPIRES_AT),
            experiment_status=state['status'], completed_calls=len(state['calls']), call_ceiling=2,
            remaining_calls=0, total_reserved_micro_usd=reserved,
            unreserved_shared_cap_micro_usd=s.CAP-reserved,
            note='remaining dollar headroom is not authorization to repeat a completed two-call experiment'),
        costs=dict(historical_incremental_estimated_micro_usd=verified['incremental_estimated_micro_usd'],
                   historical_total_estimated_micro_usd=verified['total_estimated_micro_usd'],
                   scope='token estimate, not invoice; reservations are not charges'),
        decision='memory_first_no_more_paid_calls_under_current_completed_authorization',
        next_step='freeze independent lineage-grouped holdouts; improve memory offline; reassess on fresh validation',
        live_execution_supported=False, body_policy_changed=False, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=datetime.fromisoformat, default=datetime.now(timezone.utc))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = evaluate(as_of=args.as_of)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(encoded)
        print(json.dumps({key: result[key] for key in ('decision', 'router_replay', 'numeric_gate')}, indent=2))
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
