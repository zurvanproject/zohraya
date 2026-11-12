"""Finite evidence -> persistent memory -> Rolyel recommendation integration.

Uses existing pinned project modules unchanged. No remote commands, publishing,
model API, production ledger or automatic agent loop. Only a caller-chosen
research SQLite file is written. All suggestions remain unexecuted.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'tools/fourway_evidence_gate_v02.py': '6e7006d888da9a435d7c4eac337e3f20a3771954',
    'tools/public_ci_witness.py': 'deb45948d97a0fa1fcacc56bfaacc762d5c5d6fc',
    'examples/nasuraya_research/epistemic_revision_v01.py': 'eaae3765c53eab12ee948158263b3f28763168bd',
    'examples/nasuraya_research/rolyel_v01.py': '021c752d3cb403211888acb395cd913558249d36',
    'runtimes/tadash_body/decision_core.py': 'abe1cd3c0d32e3591432345b92ab48fc49c4275b',
}


def verify_sources(root: Path = ROOT) -> None:
    for relative, expected in PINS.items():
        raw = (root / relative).read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
        if actual != expected:
            raise ValueError('source_pin_mismatch:' + relative)


verify_sources()
from tools import fourway_evidence_gate_v02 as gate
from examples.nasuraya_research.epistemic_revision_v01 import Evidence, EvidenceLedger
from examples.nasuraya_research.rolyel_v01 import Check, Route, rotate
from runtimes.tadash_body.decision_core import Action, Consequence
from tools.dios_decision_consistency_audit import audit_decision

SCHEMA = 'nasuraya.integrated-research-cycle/0.1'
SCOPES = {'public_observation', 'synthetic_test'}
KEYS = ('inventory_receipt', 'failure_receipt', 'conflicting_evidence', 'request_observed')
POST_REQUEST = 6775464507
POST_JOB = 'nasu_moltbook_vina_reply'
POST_COMMAND = ('nasu: run 48b1f6ad92c24275dea9cba951e232b62b3dbb9c '
                'nasu_moltbook_vina_reply '
                '54eb55a4b7ac64674788a01856874ede4c203c4ae75fba16a4489996e3791b2d')


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


def publication_observation(comments: list[dict]) -> dict:
    """Read only the exact queued request; owner identity is not a host signature."""
    candidates = [c for c in comments if gate.owner_comment(c)]
    requests = [c for c in candidates if c['id'] == POST_REQUEST and c['body'].strip() == POST_COMMAND]
    result = {'request_id': POST_REQUEST, 'publication_confirmed': False}
    if len(requests) != 1:
        return dict(result, state='REQUEST_UNVERIFIED')
    replies = []
    for c in candidates:
        body = c['body'].strip()
        related = gate.REQ_ID_RE.search(body)
        if not related or int(related.group(1)) != POST_REQUEST:
            continue
        match = gate.REPLY_RE.fullmatch(body)
        if not match or match.group(2) != POST_JOB or c['id'] <= POST_REQUEST:
            return dict(result, state='CONFLICT')
        replies.append((c['id'], match.group(3)))
    if not replies:
        return dict(result, state='QUEUED_NO_RECEIPT')
    if len(replies) != 1:
        return dict(result, state='CONFLICT')
    reply_id, raw = replies[0]
    # Never equate a posted owner-account string with independently visible content.
    state = 'OWNER_ACCOUNT_REPORTED_NEEDS_PUBLIC_CHECK'
    if raw in gate.FAILURES or raw == 'OK EXPIRED_NO_WRITE' or raw.startswith('OK FAIL='):
        state = 'REPORTED_FAILURE_OR_EXPIRY'
    return dict(result, state=state, reply_id=reply_id)


def observe(ci: dict, bridge: dict) -> dict:
    report = gate.reconcile(ci, bridge)
    report['queued_moltbook_publication'] = publication_observation(bridge['comments'])
    return report


def facts(report: dict) -> dict[str, str]:
    state = report['vps']['atlas_phase1']['state']
    return dict(zip(KEYS, (
        'A' if state == 'REPORTED_INVENTORY' else 'B',
        'A' if state == 'REPORTED_FAILURE' else 'B',
        'A' if state in ('CONFLICT', 'REVIEW_REQUIRED', 'REQUEST_UNVERIFIED') else 'B',
        'B' if state == 'REQUEST_UNVERIFIED' else 'A',
    )))


def recommendation(values: dict[str, str], evidence_root: str) -> dict:
    """Consume RECALLED facts, not a direct network reply or a model's narrative."""
    inv, fail, conflict, requested = [values[k] == 'A' for k in KEYS]
    relevant = {
        'inspect_bridge_readonly': requested and not (inv or fail or conflict),
        'review_atlas_inventory_readonly': inv and not (fail or conflict),
        'review_job_failure_readonly': fail and not conflict,
        'resolve_evidence_conflict_readonly': conflict or not requested,
        'resend_atlas_command': False,
        'publish_moltbook_again': False,
    }
    routes = []
    for name, applicable in relevant.items():
        external = name in ('resend_atlas_command', 'publish_moltbook_again')
        action = Action(name, (Consequence(1.0, 0.01, benefit=0.8, confidence=1.0),),
                        respect=0.8, honesty=0.8, balance=0.8, dignity=0.8,
                        compassion=0.8, disharmony=0.05)
        routes.append(Route(action, 0.9, 'Preserve the whole-body goal without duplicate work.',
                            (Check('consistent_observation', True, evidence_root),
                             Check('applicable', applicable, evidence_root)),
                            changes_external_state=external, approval_verified=False))
    chosen = rotate('Whole-body project continuity with accountable evidence',
                    'resend_atlas_command', routes,
                    ('consistent_observation', 'applicable'))
    return {'selected_route': chosen.selected_route,
            'rejected_routes': {a.route_id: list(a.failed_gates)
                                for a in chosen.assessments if not a.eligible},
            'execution_performed': False,
            'scores_are_authored_not_learned': True}


@contextmanager
def single_writer(db: Path):
    """Crash leaves a lock for review. Never silently break an existing lock."""
    lock = Path(str(db) + '.integration-lock')
    lock.mkdir()
    try:
        yield
    finally:
        lock.rmdir()


def setup(memory: EvidenceLedger) -> None:
    memory.conn.execute('CREATE TABLE IF NOT EXISTS integration_batches ('
                        'scope TEXT NOT NULL, seq INTEGER NOT NULL, fingerprint TEXT NOT NULL, '
                        'report_json TEXT NOT NULL, PRIMARY KEY(scope,seq), '
                        'UNIQUE(scope,fingerprint))')
    memory.conn.commit()


def recalled(memory: EvidenceLedger, scope: str) -> dict:
    row = memory.conn.execute('SELECT seq,fingerprint,report_json FROM integration_batches '
                              'WHERE scope=? ORDER BY seq DESC LIMIT 1', (scope,)).fetchone()
    if row is None:
        return {'state': 'NO_COMMITTED_OBSERVATION', 'recommendation': None}
    seq, fingerprint, payload = row
    report = json.loads(payload)
    if digest(report) != fingerprint:
        raise ValueError('stored_observation_integrity_mismatch')
    expected = facts(report)
    values = {}
    for key in KEYS:
        result = memory.resolve(scope, key, seq)
        if (result['latest_epoch'] != seq or result['decision'] != expected[key]
                or result['distinct_sources'] != 1):
            raise ValueError('incomplete_or_inconsistent_memory_batch')
        values[key] = result['decision']
    output = {'state': 'RECALLED', 'sequence': seq, 'fingerprint': fingerprint,
              'input_tier': scope, 'atlas_state': report['vps']['atlas_phase1']['state'],
              'moltbook_state': report['queued_moltbook_publication']['state'],
              'recommendation': recommendation(values, fingerprint),
              'remote_execution_proven': False, 'chatgpt_weights_changed': False}
    proposal = {'selected_route': output['recommendation']['selected_route'],
                'evidence_root': fingerprint,
                'execution_performed': output['recommendation']['execution_performed'],
                'remote_execution_proven': output['remote_execution_proven']}
    audit = audit_decision(report, proposal)
    if audit['status'] != 'PASS':
        raise ValueError('decision_consistency_audit_blocked:' + ','.join(audit['reason_codes']))
    output['decision_consistency_audit'] = audit
    return output


def cycle(db: Path, ci: dict, bridge: dict, seq: int, scope: str) -> dict:
    if scope not in SCOPES or type(seq) is not int or not 0 < seq < 1000000:
        raise ValueError('invalid_scope_or_sequence')
    report = observe(ci, bridge)
    fingerprint = digest(report)
    with single_writer(db), EvidenceLedger(db) as memory:
        setup(memory)
        previous = recalled(memory, scope)
        replay = memory.conn.execute('SELECT seq FROM integration_batches '
                                     'WHERE scope=? AND fingerprint=?',
                                     (scope, fingerprint)).fetchone()
        if replay is not None:
            return dict(previous, schema=SCHEMA, ingestion='REPLAY_IGNORED')
        if seq <= previous.get('sequence', 0):
            raise ValueError('stale_or_conflicting_observation_sequence')
        # Append through the unchanged DIOS module. A durable batch marker is
        # written only after all four facts exist. Partial writes cannot be read
        # as committed observations and an identical retry is idempotent.
        for key, value in facts(report).items():
            item = Evidence(f'{scope}:{seq}:{key}', scope, key, value, seq,
                            'observer:' + fingerprint, 'independent_execution', True)
            memory.append(item)
        with memory.conn:
            memory.conn.execute('INSERT INTO integration_batches VALUES (?,?,?,?)',
                                (scope, seq, fingerprint, canonical(report)))
        after = recalled(memory, scope)
        before_action = (previous.get('recommendation') or {}).get('selected_route')
        after_action = after['recommendation']['selected_route']
        return dict(after, schema=SCHEMA, ingestion='NEW_OBSERVATION',
                    previous_route=before_action, route_changed=before_action != after_action)


def recall(db: Path, scope: str) -> dict:
    if scope not in SCOPES or not db.is_file():
        raise ValueError('missing_research_database_or_invalid_scope')
    with EvidenceLedger(db) as memory:
        setup(memory)
        return recalled(memory, scope)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--recall', action='store_true')
    parser.add_argument('--scope', choices=sorted(SCOPES), default='public_observation')
    parser.add_argument('--sequence', type=int, default=1)
    parser.add_argument('--ci', type=Path, default=ROOT / 'docs/evidence/public-ci-witness-v01/frozen-public-github-runs.json')
    parser.add_argument('--bridge', type=Path, default=ROOT / 'docs/evidence/integrated-cycle-v01/bridge-observation.json')
    args = parser.parse_args()
    try:
        if args.recall:
            result = recall(args.db, args.scope)
        else:
            ci = json.loads(args.ci.read_text(encoding='utf-8'))
            bridge = json.loads(args.bridge.read_text(encoding='utf-8'))
            result = cycle(args.db, ci, bridge, args.sequence, args.scope)
    except (OSError, ValueError) as error:
        print(json.dumps({'schema': SCHEMA, 'state': 'STOP_FOR_REVIEW',
                          'error_type': type(error).__name__, 'execution_performed': False}))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
