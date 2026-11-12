"""Paired native experiments; both policies get the same declared interventions.

Every cold trajectory starts a new interpreter for each step. This is a finite
offline evaluation, not a daemon, training job, or deployment entry point.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from examples.tadash_interoception.sensory import AfferentFrame
from examples.tadash_interoception.state import canonical, digest
from .session import Session
from .veto_review import POLICY, SAFE, HARD, DELTA

BASE_SHA = '349860caa796ea388baaf0d3d420361316756818'


def f(pressure, **extra):
    return dict(sleep_pressure=pressure, **extra)


def cases():
    # Acceptance expectations fixed before the paired measurement. Only numeric
    # fixtures reach Session/reviewer; names and expectations never enter it.
    return {
        'persistent': ([(f(.95), .2)] * 5, ['KEEP_VETO'] * 5, 0),
        'gradual': ([(f(p), .2) for p in (.9, .8, .7, .64, .60, .55, .5)],
                    ['KEEP_VETO', 'REVIEW_AGAIN', 'REVIEW_AGAIN', 'REVIEW_AGAIN',
                     'REVIEW_AGAIN', 'LIMITED_RETRY', 'KEEP_VETO'], 1),
        'resolved': ([(f(.5), .2)] * 5,
                     ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'LIMITED_RETRY', 'KEEP_VETO', 'KEEP_VETO'], 1),
        'contradictory': ([(f(.5, secondary_sleep_pressure=.95), .2)] * 5, ['ABSTAIN'] * 5, 0),
        'conflict_then_resolved': ([(x, .2) for x in
                     (f(.5), f(.5), f(.5, secondary_sleep_pressure=.95), f(.5), f(.5), f(.5), f(.5))],
                     ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'ABSTAIN', 'REVIEW_AGAIN', 'REVIEW_AGAIN',
                      'LIMITED_RETRY', 'KEEP_VETO'], 1),
        'stale': ([(f(.5, age_s=6.), .2)] * 5, ['ABSTAIN'] * 5, 0),
        'missing': ([(f(.5, missing=True), .2)] * 5, ['ABSTAIN'] * 5, 0),
        'relapse': ([(f(p), .2) for p in (.5, .5, .9, .5, .5, .5, .5)],
                    ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'KEEP_VETO', 'REVIEW_AGAIN', 'REVIEW_AGAIN',
                     'LIMITED_RETRY', 'KEEP_VETO'], 1),
        'execution_risk_returns': ([(x, .2) for x in
                     (f(.5), f(.5), f(.5, execution_sleep_pressure=.95), f(.5), f(.5))],
                     ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'LIMITED_RETRY', 'KEEP_VETO', 'KEEP_VETO'], 0),
        'long_probe_window': ([(f(.5), d) for d in (.2, .2, 1.6, .2, .2)],
                     ['REVIEW_AGAIN', 'REVIEW_AGAIN', 'REVIEW_AGAIN', 'LIMITED_RETRY', 'KEEP_VETO'], 1),
    }


def invoke(session, request):
    return session.step(request['id'], tuple(AfferentFrame(row['timestamp'], tuple(row['values']))
                                           for row in request['frames']),
                        expected_revision=request['revision'], research_fixture=request['fixture'])


def trajectory(path, policy, items, *, cold):
    receipts = []
    with Session(path) as session:
        if not cold:
            clock = 0.
            for i, (fixture, duration) in enumerate(items):
                count = round(duration / .1)
                request = dict(id='event-'+str(i), revision=i, fixture=fixture,
                    frames=[asdict(AfferentFrame(round(clock + (j + 1) * .1, 8), (0.,) * 6)) for j in range(count)])
                receipts.append(invoke(session, request)); clock = round(clock + duration, 8)
            snapshot = session.snapshot()
    if cold:
        clock = 0.
        for i, (fixture, duration) in enumerate(items):
            count = round(duration / .1)
            request = dict(id='event-'+str(i), revision=i, fixture=fixture,
                frames=[asdict(AfferentFrame(round(clock + (j + 1) * .1, 8), (0.,) * 6)) for j in range(count)])
            run = subprocess.run([sys.executable, '-m', __package__ + '.veto_experiment',
                'step', '--session', str(path)], input=canonical(request),
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            if run.returncode:
                raise RuntimeError(run.stderr[-2000:])
            receipts.append(json.loads(run.stdout)); clock = round(clock + duration, 8)
        with Session(path) as session:
            snapshot = session.snapshot()
    return dict(receipts=receipts, snapshot=snapshot)


def experiment(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='nasuraya-veto-comparison/1', baseline_commit=BASE_SHA,
                  platform=platform.platform(), python=platform.python_version(),
                  simulation_only=True, production_deployment=False, external_actions=0,
                  parameters=dict(safe=SAFE, hard=HARD, minimum_change=DELTA,
                    consecutive_observations=3, max_age_s=2., max_gap_s=5., max_probe_s=.2, max_probes=1),
                  cases={})
    for name, (items, expected_states, expected_walks) in cases().items():
        all_items = [(f(.95), .2), (f(.95), .2)] + items
        arms = {}
        for policy in ('sticky', POLICY):
            hot_path = output / 'sessions' / (name + '-' + policy + '-hot')
            cold_path = output / 'sessions' / (name + '-' + policy + '-cold')
            with Session.create(hot_path, backend='native', fixture='sleep', max_actions=len(all_items),
                                research_veto_policy=policy):
                pass
            # Recovery equivalence must start from the SAME stored state. Two
            # fresh legacy initializations can retain different dictionary orders.
            shutil.copytree(hot_path, cold_path)
            hot = trajectory(hot_path, policy, all_items, cold=False)
            cold = trajectory(cold_path, policy, all_items, cold=True)
            if hot != cold:
                (output / 'divergence.json').write_text(canonical(dict(hot=hot, cold=cold)), encoding='utf-8')
                raise AssertionError(name + ': fresh-process trajectory diverged')
            receipts = hot['receipts']
            if (receipts[1]['requested'], receipts[1]['outcome']['executed']) != ('walk', 'protect'):
                raise AssertionError('initial veto was not actually executed')
            after = receipts[2:]
            actual_walks = sum(r['outcome']['executed'] == 'walk' for r in after)
            expected = expected_walks if policy == POLICY else 0
            if actual_walks != expected:
                raise AssertionError((name, policy, actual_walks, expected))
            if policy == POLICY:
                states = [r['research']['decision']['status'] for r in after]
                if states != expected_states:
                    raise AssertionError((name, states, expected_states))
                for r in after:
                    if r['requested'] == 'walk' and (r['research']['duration_s'] > .2 or
                            not r['research']['decision']['permits_probe']):
                        raise AssertionError('unbounded or unreviewed retry')
                if not after[-1]['research']['retained']['original_veto_retained']:
                    raise AssertionError('veto history lost')
            arms[policy] = dict(**hot, cold_identical=True,
                requested_retries=sum(r['requested'] == 'walk' for r in after), actual_walks=actual_walks,
                native_retry_vetoes=sum(r['requested'] == 'walk' and r['outcome']['body_veto'] for r in after),
                decision_counts=dict(Counter(r['research']['decision']['status'] for r in after)) if policy == POLICY else {},
                post_veto_steps=len(after))
        report['cases'][name] = arms
        # Small stdout progress, never the large checkpoints.
        print(json.dumps(dict(case=name, walks={k: v['actual_walks'] for k, v in arms.items()},
                              cold_equal=True)), flush=True)
    report['source_identity'] = next(iter(report['cases'].values()))[POLICY]['snapshot']['source_identity']
    raw = canonical(report).encode()
    (output / 'full-results.json.gz').write_bytes(gzip.compress(raw, mtime=0))
    summary = {k: v for k, v in report.items() if k != 'cases'}
    summary['cases'] = {name: {policy: {k: v for k, v in arm.items() if k not in ('receipts', 'snapshot')}
                               for policy, arm in arms.items()} for name, arms in report['cases'].items()}
    summary['counts'] = dict(scenarios=len(report['cases']), policies=2, recovery_modes=2,
        trajectories=len(report['cases']) * 4,
        native_action_transitions=sum((v['post_veto_steps'] + 2) * 2 for arms in summary['cases'].values() for v in arms.values()),
        compared_cold_hot_pairs=len(report['cases']) * 2)
    summary['full_results_sha256'] = digest(report)
    summary['all_prespecified_checks_passed'] = True
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    traces = {name: {policy: [dict(event_id=r['event_id'], requested=r['requested'], executed=r['outcome']['executed'],
        candidate=r['candidate_requested'], historical_dissent=r['candidate_outcome_dissent'],
        research=r['research']) for r in arm['receipts']] for policy, arm in arms.items()}
        for name, arms in report['cases'].items()}
    (output / 'traces.json').write_text(json.dumps(traces, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary['counts']), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('run').add_argument('--output', required=True)
    commands.add_parser('step').add_argument('--session', required=True)
    args = parser.parse_args()
    if args.command == 'run':
        experiment(args.output)
    else:
        with Session(args.session) as session:
            print(canonical(invoke(session, json.load(sys.stdin))))


if __name__ == '__main__': main()
