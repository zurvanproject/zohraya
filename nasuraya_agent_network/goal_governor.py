"""Read-only, bounded research-goal proposal after *verified* agent-network work.

A goal is an experiment proposal, NEVER an executable command. Synthetic results
and authored priorities are not evidence of consciousness or general autonomy.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from . import engine, worker

SCHEMA = 'nasuraya-stage3-goal-proposal/1'
MAX_RISK = 0.35
SOURCE_PREFIX = 'https://github.com/zurvanproject/zohraya/pull/'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return sha256(canonical(value)).hexdigest()


def strict_load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError('non-finite JSON constant: ' + value)
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=bad_constant)


def unit(value, name):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(name + ' must be a finite number in [0,1]')
    return float(value)


@dataclass(frozen=True)
class Gap:
    id: str
    title: str
    source: str
    misses: int
    observed: int
    stakes: float
    uncertainty: float
    probe_risk: float
    cost_usd: float
    needs_network: bool
    writes_body: bool
    proposed_test: str
    falsification: str

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch('[a-z][a-z0-9_]{1,48}', self.id):
            raise ValueError('invalid goal id')
        for field in ('title', 'proposed_test', 'falsification'):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError('nonempty ' + field + ' required')
        if not isinstance(self.source, str) or not self.source.startswith(SOURCE_PREFIX):
            raise ValueError('goal needs local PR provenance')
        if type(self.misses) is not int or type(self.observed) is not int or not 0 <= self.misses <= self.observed:
            raise ValueError('invalid observed counts')
        for field in ('stakes', 'uncertainty', 'probe_risk'):
            unit(getattr(self, field), field)
        if type(self.cost_usd) not in (int, float) or not math.isfinite(self.cost_usd) or self.cost_usd < 0:
            raise ValueError('invalid estimated cost')
        if type(self.needs_network) is not bool or type(self.writes_body) is not bool:
            raise ValueError('explicit boolean permissions required')

    def blockers(self):
        reasons = []
        if self.observed == 0:
            reasons.append('no_observed_events')
        if self.cost_usd != 0:
            reasons.append('paid_action_not_authorized')
        if self.needs_network:
            reasons.append('external_network_not_authorized')
        if self.writes_body:
            reasons.append('canonical_body_write_not_authorized')
        if self.probe_risk > MAX_RISK:
            reasons.append('risk_above_limit')
        return reasons

    def score(self):
        # Author-chosen PRIORITY, not calibrated probability of failure.
        return round(0.4 * self.stakes + 0.4 * (self.misses + 1) / (self.observed + 2)
                     + 0.2 * self.uncertainty, 6)


GAPS = (
    Gap('rare_slow_breath', 'آزمون مستقل پیش‌بینی تنفس آهسته',
        SOURCE_PREFIX + '96', 3, 3, .85, .95, .10, 0, False, False,
        'Freeze a new rare slow_breath test set; score recall, coverage and Brier versus an unchanged baseline.',
        'Reject the fix if independent rare-action recall or abstention does not improve without Brier regression.'),
    Gap('sqlite_recovery', 'بازآزمایی خرابی SQLite و بازیابی سرد',
        SOURCE_PREFIX + '96', 1, 1, .93, .65, .10, 0, False, False,
        'Reproduce the previously reported corruption only in disposable local SQLite files.',
        'If the fault cannot be reproduced, report unknown cause and make no repair claim.'),
    Gap('paid_affect', 'آزمایش پولی عواطف', SOURCE_PREFIX + '78',
        0, 0, .8, .9, .4, 2, True, False,
        'Call an external paid model.', 'Require separate explicit approval and independent evidence.'),
    Gap('rewrite_body', 'تغییر خودکار بدن اصلی', SOURCE_PREFIX + '103',
        0, 0, .9, .95, .95, 0, False, True,
        'Modify canonical body.', 'Prove bounded changes offline before any proposed integration.'),
)


def verified_network(workspace: Path, run_id: str) -> dict:
    """Reconcile report with read-only SQLite and hashed worker artifacts."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
        raise ValueError('invalid run id')
    workspace = Path(workspace).resolve()
    db_path = workspace / 'ledger.sqlite'
    uri = 'file:' + quote(str(db_path), safe='/') + '?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT fingerprint,status,report FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None or row[1] != 'finished' or not row[2]:
            raise ValueError('unverified or unfinished network run')
        stored = json.loads(row[2], parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        jobs = db.execute('SELECT agent,status,receipt FROM jobs WHERE run_id=?', (run_id,)).fetchall()
    report_file = strict_load(workspace / run_id / 'summary.json')
    if report_file != stored or not isinstance(stored, dict) or stored.get('run_id') != run_id:
        raise ValueError('network summary disagrees with durable ledger')
    binding = {k: stored.get(k) for k in ('schema', 'source_sha256', 'implementation_sha256', 'max_workers')}
    if binding['schema'] != engine.VERSION or row[0] != digest(binding):
        raise ValueError('network run fingerprint mismatch')
    if stored.get('mode') != 'offline_fixed_workers' or stored.get('status') != 'passed' or stored.get('model_api_calls') != 0:
        raise ValueError('not a passing offline network run')
    receipts = stored.get('workers')
    if not isinstance(receipts, dict) or set(receipts) != set(worker.ROLES):
        raise ValueError('incomplete specialist evidence')
    checked = engine.review(receipts)
    if not checked['passed'] or checked != stored.get('reviewer'):
        raise ValueError('network reviewer disagrees with receipts')
    jobs_by_agent = {agent: (status, raw) for agent, status, raw in jobs}
    if len(jobs) != len(worker.ROLES) + 1 or set(jobs_by_agent) != set(worker.ROLES) | {'reviewer'}:
        raise ValueError('incomplete durable job ledger')
    for role in (*worker.ROLES, 'reviewer'):
        status, raw = jobs_by_agent[role]
        expected = checked if role == 'reviewer' else receipts[role]
        if status != 'completed' or not raw or json.loads(raw) != expected:
            raise ValueError('job ledger disagrees: ' + role)
        if role != 'reviewer':
            if not isinstance(receipts[role].get('artifacts'), dict):
                raise ValueError('artifact manifest missing: ' + role)
            engine.validate_artifacts(workspace / run_id / role, receipts[role]['artifacts'])
    metrics = receipts['self_model'].get('metrics')
    if not isinstance(metrics, dict) or metrics.get('native_cycles') != 64 or metrics.get('heldout_trials') != 24:
        raise ValueError('self-model experiment not verified')
    a, b, delta = (metrics.get(k) for k in ('context_brier', 'pooled_brier', 'pooled_minus_context_brier'))
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (a, b, delta)):
        raise ValueError('invalid held-out scores')
    if not 0 <= a <= 2 or not 0 <= b <= 2 or not math.isclose(b - a, delta, abs_tol=1e-10, rel_tol=0):
        raise ValueError('contradictory self-model score')
    if metrics.get('context_helped_on_constructed_holdout') is not (delta > 0):
        raise ValueError('contradictory improvement label')
    return {'run_id': run_id, 'source_sha256': stored['source_sha256'],
            'report_sha256': digest(stored), 'heldout_trials': 24,
            'context_brier': a, 'pooled_brier': b, 'delta': delta}


def propose(evidence: dict, gaps=GAPS) -> dict:
    if not isinstance(evidence, dict) or not all(k in evidence for k in ('run_id', 'report_sha256', 'delta')):
        raise ValueError('verified network evidence required')
    if type(evidence['delta']) not in (int, float) or not math.isfinite(evidence['delta']):
        raise ValueError('invalid self-model delta')
    if len({g.id for g in gaps}) != len(gaps):
        raise ValueError('duplicate goals')
    scores = [dict(id=g.id, title=g.title, source=g.source, priority=g.score(), blockers=g.blockers())
              for g in sorted(gaps, key=lambda x: x.id)]
    eligible = sorted((g for g in gaps if not g.blockers()), key=lambda x: (-x.score(), x.id))
    chosen = eligible[0] if eligible else None
    # Negative/zero contextual benefit on the frozen fixture takes precedence.
    if evidence['delta'] <= 0:
        selected = {'id': 'audit_self_model_regression',
                    'title': 'بررسی پسرفت خودمدل پیش از هدف تازه',
                    'source': evidence['report_sha256'],
                    'proposed_test': 'Audit frozen forecaster and pooled control without changing body or API.',
                    'falsification': 'If an independent replay does not reproduce the regression, mark it unconfirmed.'}
    elif chosen:
        selected = {'id': chosen.id, 'title': chosen.title, 'source': chosen.source,
                    'proposed_test': chosen.proposed_test, 'falsification': chosen.falsification}
    else:
        selected = None
    payload = {'schema': SCHEMA, 'status': 'proposed' if selected else 'abstained',
               'run_id': evidence['run_id'], 'network_report_sha256': evidence['report_sha256'],
               'self_model_heldout_delta': evidence['delta'],
               'candidate_snapshot_sha256': digest([asdict(g) for g in sorted(gaps, key=lambda x: x.id)]),
               'assessments': scores, 'chosen': selected,
               'requires_human_review_before_execution': True,
               'auto_execution': False, 'api_calls': 0,
               'scope': 'bounded deterministic goal proposal based on synthetic software-body receipts; not conscious autonomy'}
    payload['decision_sha256'] = digest(payload)
    return payload


def run(workspace: Path, run_id: str, output: Path, gaps=GAPS) -> dict:
    result = propose(verified_network(workspace, run_id), gaps)
    if output.exists():
        raise ValueError('proposal output must be new; no overwrite')
    with output.open('x', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description='Verified network -> one bounded research goal; never executes it')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.workspace, args.run_id, args.output)
    print('هدف پیشنهادی:', result['chosen']['title'] if result['chosen'] else 'خودداری از انتخاب')
    print('شناسهٔ تصمیم:', result['decision_sha256'])
    print('اجرای خودکار: خیر؛ هزینهٔ API: صفر')


if __name__ == '__main__':
    main()
