"""Bounded deterministic supervisor for a synthetic Tadash body.

Uses the existing BodyLoop gates, native checkpoint, and SQLite ledger.
Not subjective awareness, biological homeostasis, or a new actuator/API.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import re

SCHEMA = 'nasuraya-self-maintenance/1'
PRINCIPLES = ('preserve_center', 'truthful_provenance',
              'honor_body_safety_veto', 'bounded_actions', 'human_oversight')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(',', ':'))


def digest(value):
    return sha256(canonical(value).encode('utf-8')).hexdigest()


def unit(value, name):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(name + ': expected finite synthetic index in [0,1]')
    return float(value)


def plan(snapshot, previous=None):
    """Choose native motion preference from source-linked indices and feedback.

    Confidence below is input-contract confidence, not a calibrated probability.
    """
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('checkpoint_sha256'), str):
        raise ValueError('body checkpoint evidence required')
    s = snapshot.get('minimum_state')
    if not isinstance(s, dict):
        raise ValueError('minimum body state missing')
    v = {k: unit(s.get(k), k) for k in ('energy', 'fatigue', 'pain', 'sleep_pressure', 'balance')}
    t = s.get('temperature')
    if type(t) not in (int, float) or not math.isfinite(t) or not 20 <= t <= 45:
        raise ValueError('temperature outside synthetic scope')
    load = max(v['fatigue'], v['sleep_pressure'])
    integrity = min(v['energy'], v['balance'], 1. - v['pain'])
    reasons = []
    if v['energy'] <= .25: reasons.append('low_energy')
    if v['fatigue'] >= .45: reasons.append('fatigue')
    if v['sleep_pressure'] >= .65: reasons.append('sleep_pressure')
    if v['balance'] <= .35: reasons.append('low_balance')
    if v['pain'] >= .70: reasons.append('pain')
    if not 35.0 <= t <= 39.0: reasons.append('temperature_outlier')
    if previous and previous.get('requested_action') == 'walk' and previous.get('actual_action') != 'walk':
        reasons.append('remembered_motion_veto')
    return {'requested_action': 'observe' if reasons else 'walk',
            'reason_codes': reasons or ['synthetic_indices_in_range'],
            'confidence': 1.0, 'confidence_kind': 'input_contract_validation_not_calibrated_probability',
            'indices': {'energy': v['energy'], 'compute_load_proxy': load,
                        'integrity_proxy': integrity, 'balance': v['balance'],
                        'temperature_c_fixture': float(t)},
            'evidence_checkpoint': snapshot['checkpoint_sha256']}


class MaintenanceBlocked(RuntimeError):
    """Fail closed on uncertainty, tampering or conflicting goals."""


class IdentityContinuity:
    """Append-only versioned computational identity, with hash chain.

    SHA detects accidental damage but cannot prevent a hostile DB rewrite.
    The constitutional principles are frozen in code, not subjective beliefs.
    """
    def __init__(self, db):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS nasu_identity_versions (
            version INTEGER PRIMARY KEY, parent_hash TEXT NOT NULL,
            document TEXT NOT NULL, rationale TEXT NOT NULL,
            evidence TEXT NOT NULL, record_hash TEXT NOT NULL)""")
        if not db.execute('SELECT 1 FROM nasu_identity_versions LIMIT 1').fetchone():
            doc = {'schema': SCHEMA, 'principles': list(PRINCIPLES), 'beliefs': {}}
            self._append(doc, 'initial explicit project constitution', 'design://nasuraya/identity-v01')
        self.verify()

    def _append(self, document, rationale, evidence):
        row = self.db.execute('SELECT version, record_hash FROM nasu_identity_versions ORDER BY version DESC LIMIT 1').fetchone()
        version, parent = ((int(row[0]) + 1, row[1]) if row else (1, 'GENESIS'))
        record = {'version': version, 'parent_hash': parent, 'document': document,
                  'rationale': rationale, 'evidence': evidence}
        self.db.execute('INSERT INTO nasu_identity_versions VALUES (?,?,?,?,?,?)',
                        (version, parent, canonical(document), rationale, evidence, digest(record)))
        return version

    def verify(self):
        parent, version_expected, last = 'GENESIS', 1, None
        for version, prev, raw, rationale, evidence, h in self.db.execute(
                'SELECT * FROM nasu_identity_versions ORDER BY version').fetchall():
            doc = json.loads(raw)
            record = {'version': version, 'parent_hash': prev,
                      'document': doc, 'rationale': rationale, 'evidence': evidence}
            if version != version_expected or prev != parent or doc.get('schema') != SCHEMA or (
                    doc.get('principles') != list(PRINCIPLES)) or not isinstance(doc.get('beliefs'), dict) or digest(record) != h:
                raise MaintenanceBlocked('identity continuity verification failed')
            parent, version_expected, last = h, version_expected + 1, doc
        if last is None:
            raise MaintenanceBlocked('identity history missing')
        return deepcopy(last)

    def revise_belief(self, key, value, *, reason, evidence):
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', key):
            raise ValueError('belief key must be bounded and canonical')
        if key in ('principles', 'schema'):
            raise MaintenanceBlocked('core principle mutation forbidden')
        if not isinstance(value, (str, int, float, bool, type(None))) or (
                isinstance(value, float) and not math.isfinite(value)):
            raise ValueError('belief must be a bounded JSON scalar')
        if isinstance(value, str) and len(value) > 200:
            raise ValueError('belief value too long')
        if not all(isinstance(x, str) and 8 <= len(x.strip()) <= 500 for x in (reason, evidence)):
            raise ValueError('explicit reason and provenance required')
        document = self.verify()
        document['beliefs'][key] = value
        return self._append(document, reason, evidence)

    def revert_to(self, version, *, reason, evidence):
        self.verify()
        if type(version) is not int:
            raise ValueError('integer version required')
        row = self.db.execute('SELECT document FROM nasu_identity_versions WHERE version=?', (version,)).fetchone()
        if row is None:
            raise ValueError('unknown version')
        if not all(isinstance(x, str) and 8 <= len(x.strip()) <= 500 for x in (reason, evidence)):
            raise ValueError('explicit reason and provenance required')
        return self._append(json.loads(row[0]), 'revert: ' + reason, evidence)


class SelfMaintenance:
    """Bounded local goal using the existing native body and event ledger."""
    def __init__(self, loop, *, goal_id, target_cycles):
        if not isinstance(goal_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,55}', goal_id):
            raise ValueError('bounded goal_id required')
        if type(target_cycles) is not int or not 1 <= target_cycles <= 3:
            raise ValueError('target_cycles must be 1..3')
        if loop.config['mode'] != 'bounded':
            raise MaintenanceBlocked('observe-only host cannot mutate body')
        self.loop, self.db = loop, loop.engine.db
        self.goal_id, self.target_cycles = goal_id, target_cycles
        self.identity = IdentityContinuity(self.db)
        self.db.execute("""CREATE TABLE IF NOT EXISTS nasu_maintenance_goals (
            goal_id TEXT PRIMARY KEY, target_cycles INTEGER NOT NULL,
            initial_sha TEXT NOT NULL, identity_hash TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS nasu_maintenance_steps (
            goal_id TEXT NOT NULL, ordinal INTEGER NOT NULL, decision_id TEXT NOT NULL UNIQUE,
            before_sha TEXT NOT NULL, proposal TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('pending','complete','failed')),
            receipt TEXT, after_sha TEXT, evaluation TEXT,
            PRIMARY KEY (goal_id, ordinal))""")
        row = self.db.execute('SELECT target_cycles FROM nasu_maintenance_goals WHERE goal_id=?', (goal_id,)).fetchone()
        if row is None:
            identity_hash = self.db.execute(
                'SELECT record_hash FROM nasu_identity_versions ORDER BY version DESC LIMIT 1').fetchone()[0]
            self.db.execute('INSERT INTO nasu_maintenance_goals VALUES (?,?,?,?)',
                            (goal_id, target_cycles, loop.status()['self_model']['checkpoint_sha256'], identity_hash))
        elif int(row[0]) != target_cycles:
            raise MaintenanceBlocked('goal target changed across restart')

    def _rows(self):
        return self.db.execute("""SELECT ordinal, decision_id, before_sha, proposal, state,
                                    receipt, after_sha, evaluation FROM nasu_maintenance_steps
                                    WHERE goal_id=? ORDER BY ordinal""", (self.goal_id,)).fetchall()

    def _complete(self, ordinal, receipt):
        state = 'complete' if receipt['status'] == 'complete' else 'failed'
        after = receipt['self_model_after']['checkpoint_sha256']
        before = self.db.execute('SELECT before_sha, proposal FROM nasu_maintenance_steps WHERE goal_id=? AND ordinal=?',
                                 (self.goal_id, ordinal)).fetchone()
        if before is None:
            raise MaintenanceBlocked('missing intent for body outcome')
        proposal = json.loads(before[1])
        evaluation = {'before_sha': before[0], 'after_sha': after,
                      'requested_action': receipt['requested_action'], 'actual_action': receipt['actual_action'],
                      'vetoed': receipt['requested_action'] != receipt['actual_action'],
                      'feedback_matched': receipt['expected_outcome_matched'],
                      'measured_progress': 1 if state == 'complete' else 0,
                      'uncertainty': 'synthetic outcome, not calibrated prediction',
                      'identity_principles_retained': self.identity.verify()['principles'] == list(PRINCIPLES),
                      'reason_codes': proposal['reason_codes']}
        self.db.execute("""UPDATE nasu_maintenance_steps SET state=?, receipt=?, after_sha=?, evaluation=?
                           WHERE goal_id=? AND ordinal=? AND state='pending'""",
                        (state, canonical(receipt), after, canonical(evaluation), self.goal_id, ordinal))
        return evaluation

    def _reconcile(self):
        for ordinal, decision_id, before, proposal, state, receipt, after, evaluation in self._rows():
            if state == 'pending':
                native = self.loop.engine.get(decision_id)
                if native is None or native['status'] != 'complete':
                    raise MaintenanceBlocked('uncertain pending body action; manual reconciliation required')
                result = self.loop.receipt(native, replayed=True)
                if result['self_model_after']['checkpoint_sha256'] != self.loop.status()['self_model']['checkpoint_sha256']:
                    raise MaintenanceBlocked('body diverged during recovery')
                self._complete(ordinal, result)

    def status(self):
        self.identity.verify()
        self._reconcile()
        rows = self._rows()
        for ordinal, decision_id, before_sha, proposal, state, receipt, after_sha, evaluation in rows:
            if state in ('complete', 'failed'):
                native = self.loop.engine.get(decision_id)
                if native is None or native['status'] != 'complete' or not receipt:
                    raise MaintenanceBlocked('native decision ledger missing for recorded step')
                original = self.loop.receipt(native, replayed=False)
                saved = json.loads(receipt)
                for field in ('status', 'requested_action', 'actual_action', 'expected_outcome_matched'):
                    if saved.get(field) != original.get(field):
                        raise MaintenanceBlocked('recorded outcome conflicts with native ledger')
                if after_sha != original['self_model_after']['checkpoint_sha256']:
                    raise MaintenanceBlocked('recorded body checkpoint conflicts with native ledger')
        if any(row[4] == 'failed' for row in rows):
            state = 'failed'
        elif len(rows) == self.target_cycles and all(row[4] == 'complete' for row in rows):
            state = 'completed'
        else:
            state = 'incomplete'
        return {'schema': SCHEMA, 'goal_id': self.goal_id, 'status': state,
                'completed_cycles': sum(row[4] == 'complete' for row in rows),
                'target_cycles': self.target_cycles,
                'body_actions_remaining': self.loop.status()['actions_remaining'],
                'history': [json.loads(row[7]) for row in rows if row[7]],
                'identity_version': self.db.execute('SELECT MAX(version) FROM nasu_identity_versions').fetchone()[0],
                'external_model_api_used': False}

    def run(self):
        first = self.status()
        if first['status'] != 'incomplete':
            return first
        rows = self._rows()
        if rows and (not rows[-1][6] or rows[-1][6] != self.loop.status()['self_model']['checkpoint_sha256']):
            raise MaintenanceBlocked('native body changed outside bounded maintenance goal')
        while len(self._rows()) < self.target_cycles:
            state = self.loop.status()
            if state['actions_remaining'] <= 0 or state['unresolved_running']:
                raise MaintenanceBlocked('native body budget or unresolved operation blocks maintenance')
            snapshot = self.loop.observe()
            rows = self._rows()
            previous = json.loads(rows[-1][5]) if rows and rows[-1][5] else None
            proposal = plan(snapshot, previous=previous)
            if proposal['requested_action'] not in ('walk', 'observe'):
                raise MaintenanceBlocked('identity policy forbids proposed action')
            ordinal = len(rows) + 1
            decision_id = 'nasu-maint-' + self.goal_id + '-' + str(ordinal)
            self.db.execute("""INSERT INTO nasu_maintenance_steps
                (goal_id, ordinal, decision_id, before_sha, proposal, state)
                VALUES (?,?,?,?,?,'pending')""",
                (self.goal_id, ordinal, decision_id, snapshot['checkpoint_sha256'], canonical(proposal)))
            # Intent is persisted BEFORE native action. Never replay unknown effects.
            receipt = self.loop.step(decision_id=decision_id, duration_s=.1,
                                     preferred_action=proposal['requested_action'])
            self._complete(ordinal, receipt)
            if receipt['status'] != 'complete':
                break
        return self.status()
