"""Opt-in, receipt-trained admission control at the existing API/body boundary.

The native ReflectionCycle/ReflectiveBody sources remain unchanged. Decisions
are assessed after the existing core chooses, before its native callback runs.
Deferral is unverified non-execution, never a failed body-admission sample.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from examples.nasuraya_self_model.monitor import SelfModel, snapshot, digest, source
from examples.nasuraya_self_model.metacognitive_control import select
from examples.nasuraya_self_model.regulation import KnowledgeView
from reflection_cycle import ReflectiveBody, InterruptedExecution, canonical, instant
from unified_body_v2 import UnifiedBody

SCHEMA = 'nasuraya-api-metacognition/1'
CONFIG_KEY = 'nasuraya-api-metacognition'
MODES = ('shadow', 'enforce')


def sources():
    from examples.nasuraya_self_model import metacognitive_control
    return dict(bridge=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                monitor=source(),
                routing=hashlib.sha256(Path(metacognitive_control.__file__).read_bytes()).hexdigest())


def outcome_deferred(record):
    actual = record.get('actual_outcome') or {}
    return (record['status'] == 'complete' and actual.get('status') == 'deferred'
            and actual.get('native_executed') is False
            and 'body_receipt' not in actual and 'body_checkpoint' not in actual)


def configure(loop, *, memory_path, mode, expected_checkpoint, create_memory=False):
    if mode not in MODES or loop.body().checkpoint()['sha256'] != expected_checkpoint:
        raise ValueError('explicit mode and current checkpoint required')
    if any(r['status'] == 'running' for r in loop.records()):
        raise InterruptedExecution('resolve the body outcome before configuring metacognition')
    path = Path(memory_path).resolve()
    old = loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (CONFIG_KEY,)).fetchone()
    if old:
        previous = json.loads(old[0])
        if previous['memory_path'] != str(path) or previous['sources'] != sources() or create_memory:
            raise ValueError('existing memory/source binding cannot be silently replaced')
    model = SelfModel.create(path) if create_memory else SelfModel(path)
    if model.verify()['pending']:
        raise InterruptedExecution('resolve the self-model outcome before changing control mode')
    contract = dict(schema=SCHEMA, mode=mode, memory_path=str(path), sources=sources(),
                    scope='walk-only enforcement; other actions retain native arbitration')
    with loop.engine.transaction():
        loop.engine.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (CONFIG_KEY, canonical(contract)))
    attach(loop)
    return loop.metacognition.overview()


def attach(loop):
    row = loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (CONFIG_KEY,)).fetchone()
    if row is None:
        loop.metacognition = None
        return
    contract = json.loads(row[0])
    if contract['schema'] != SCHEMA or contract['sources'] != sources() or contract['mode'] not in MODES:
        raise ValueError('metacognitive source/version mismatch')
    bridge = MetacognitiveBody(loop.engine, key=loop.adapter.key, contract=contract)
    loop.adapter = loop.metacognition = bridge


class MetacognitiveBody(ReflectiveBody):
    def __init__(self, engine, *, key, contract):
        super().__init__(engine, key=key)
        self.contract = deepcopy(contract)
        self.model = SelfModel(contract['memory_path'])
        engine.db.execute('''CREATE TABLE IF NOT EXISTS body_metacognition(
            decision_id TEXT PRIMARY KEY, value TEXT NOT NULL, sha256 TEXT NOT NULL)''')
        self.reconcile()

    def overview(self):
        state = self.model.verify()
        return dict(schema=SCHEMA, mode=self.contract['mode'], learned_episodes=sum(
            sum(v) for v in state['counts'].values()), pending_outcomes=len(state['pending']),
            enforcement_scope='requested walk only', prediction_scope='software request admission')

    @staticmethod
    def native_request(body, event, action, duration, at_utc):
        return dict(event_id=event, at_utc=instant(at_utc).isoformat(), duration_s=duration,
                    requested=action, expected_revision=body.revision, external={})

    def assessment(self, body, action, duration):
        at = datetime.fromisoformat(body.owner.wall_utc) + timedelta(seconds=duration)
        q = self.native_request(body, 'assessment', action, duration, at.isoformat())
        obs = snapshot(body)
        state = json.loads(canonical(self.model.verify()))
        if action == 'walk':
            decision = select(state, obs, q, arm='control', now_s=obs['time_s'], refreshed=True)
        else:
            report = self.model.inspect(obs, q)
            decision = dict(choice='request_nonwalk', reasons=['nonwalk_native_arbitration'],
                            report=report, probability=report['inferred']['probability'])
        return self.reduced(decision, action, duration, obs['native_sha'])

    def reduced(self, decision, action, duration, before_sha):
        inferred = decision['report']['inferred']
        return dict(schema=SCHEMA, mode=self.contract['mode'], action=action, duration_s=duration,
            checkpoint_sha256=before_sha, probability=inferred['probability'], samples=inferred['samples'],
            unseen_context=inferred['unseen_context'], recommendation=decision['choice'],
            reasons=decision['reasons'], enforcement_applies=action == 'walk' and self.contract['mode'] == 'enforce',
            scope='bounded external self-model, not a globally calibrated success probability')

    def _put(self, row):
        with self.engine.transaction():
            self.engine.db.execute('INSERT OR REPLACE INTO body_metacognition VALUES(?,?,?)',
                (row['decision_id'], canonical(row), digest(row)))

    def _get(self, decision_id):
        raw = self.engine.db.execute('SELECT value,sha256 FROM body_metacognition WHERE decision_id=?',
                                     (decision_id,)).fetchone()
        if raw is None:
            return None
        row = json.loads(raw[0])
        if digest(row) != raw[1] or row['sources'] != sources() or row['schema'] != SCHEMA:
            raise ValueError('metacognitive decision integrity/source mismatch')
        q, obs = row['native_request'], row['observation']
        if q['requested'] == 'walk':
            expected = select(row['knowledge'], obs, q, arm='control', now_s=obs['time_s'], refreshed=True)
            if expected != row['decision']:
                raise ValueError('metacognitive decision differs from saved knowledge')
        else:
            report = SelfModel.inspect(KnowledgeView(row['knowledge']), obs, q)
            expected = dict(choice='request_nonwalk', reasons=['nonwalk_native_arbitration'],
                            report=report, probability=report['inferred']['probability'])
            if expected != row['decision']:
                raise ValueError('nonwalk report differs from saved knowledge')
        effective = ('defer' if row['mode'] == 'enforce' and q['requested'] == 'walk'
                     and row['decision']['choice'] != 'request_walk' else 'execute_under_native_guards')
        if row['mode'] not in MODES or row['effective_choice'] != effective:
            raise ValueError('metacognitive enforcement differs from saved policy')
        return row

    def _finish_learning(self, row, record):
        actual = record.get('actual_outcome') or {}
        if record['status'] != 'complete' or 'body_receipt' not in actual or 'body_checkpoint' not in actual:
            raise InterruptedExecution('native outcome unavailable; no metacognitive learning or replay')
        receipt = actual['body_receipt']
        result = self.model.finish(row['native_request']['event_id'],
            UnifiedBody.restore(actual['body_checkpoint']), receipt)
        row.update(phase='complete', outcome=dict(admitted=result['admitted'],
            receipt_sha256=digest(receipt), brier=result['brier'], learned=result['learned']))
        self._put(row)

    def reconcile(self, *, strict=False):
        """Use only a committed native checkpoint/receipt; never call cycle."""
        pending = self.model.verify()['pending']
        for event in pending:
            if not event.startswith('reflection:'):
                if strict:
                    raise InterruptedExecution('self-model pending event belongs to another execution path')
                continue
            decision_id = event[len('reflection:'):]
            row, record = self._get(decision_id), self.engine.get(decision_id)
            if row is None or record is None:
                if strict:
                    raise InterruptedExecution('self-model outcome belongs to another ledger or is unknown')
                continue
            actual = record.get('actual_outcome') or {}
            if record['status'] == 'complete' and 'body_receipt' in actual and 'body_checkpoint' in actual:
                self._finish_learning(row, record)
            elif strict:
                raise InterruptedExecution('native outcome is unknown; no action retried')
        # A crash may happen after model.finish, before the bridge row update.
        for item in list(self.engine.db.execute('SELECT decision_id FROM body_metacognition')):
            row = self._get(item[0])
            record = self.engine.get(item[0])
            if row['phase'] == 'planned' and record and record['status'] == 'complete':
                if outcome_deferred(record):
                    row.update(phase='deferred', outcome=None)
                    self._put(row)
                else:
                    actual = record.get('actual_outcome') or {}
                    if 'body_receipt' in actual and 'body_checkpoint' in actual:
                        self._finish_learning(row, record)

    def public_record(self, decision_id):
        row = self._get(decision_id)
        if row is None:
            return None
        q = row['native_request']
        result = self.reduced(row['decision'], q['requested'], q['duration_s'], row['observation']['native_sha'])
        # A historical receipt keeps the mode that governed that request.
        result['mode'] = row['mode']
        result['enforcement_applies'] = q['requested'] == 'walk' and row['mode'] == 'enforce'
        result.update(effective_choice=row['effective_choice'], learning=row['outcome'])
        return result

    def cycle(self, request, *, at_utc, duration_s=.1, external=None):
        if external:
            raise ValueError('API metacognition v0.1 supports the existing empty external-input contract')
        self.reconcile(strict=True)
        # Match ReflectiveBody's exact request contract before the core chooses.
        prepared = deepcopy(request)
        prepared['execution'] = dict(runtime_key=self.key, at_utc=instant(at_utc).isoformat(),
                                     duration_s=duration_s, external={})
        record = self.engine.decide(prepared)
        if record['status'] == 'complete' or record['selected_action'] is None:
            return record
        if record['status'] == 'running':
            raise InterruptedExecution('previous body execution is unresolved')
        candidate = next(c for c in record['request']['actions'] if c['id'] == record['selected_action'])
        body = UnifiedBody.restore(self.engine.runtime(self.key))
        q = self.native_request(body, 'reflection:'+record['id'], candidate['body_action'], duration_s, at_utc)
        if len(q['event_id']) > 100:
            raise ValueError('metacognitive event identifier exceeds the existing self-model contract')
        row = self._get(record['id'])
        if row is None:
            knowledge = json.loads(canonical(self.model.verify()))
            obs = snapshot(body)
            if q['requested'] == 'walk':
                decision = select(knowledge, obs, q, arm='control', now_s=obs['time_s'], refreshed=True)
            else:
                report = self.model.inspect(obs, q)
                decision = dict(choice='request_nonwalk', reasons=['nonwalk_native_arbitration'],
                                report=report, probability=report['inferred']['probability'])
            effective = ('defer' if self.contract['mode'] == 'enforce' and q['requested'] == 'walk'
                         and decision['choice'] != 'request_walk' else 'execute_under_native_guards')
            row = dict(schema=SCHEMA, sources=sources(), decision_id=record['id'],
                mode=self.contract['mode'], native_request=q, observation=obs, knowledge=knowledge,
                decision=decision, effective_choice=effective, phase='planned', outcome=None)
            self._put(row)
        if row['native_request'] != q:
            raise ValueError('saved assessment request differs from native request')
        if row['effective_choice'] == 'defer':
            deferred = self.engine.complete(record['id'],
                dict(status='deferred', native_executed=False, selected_action=None,
                     reason='metacognitive_admission_gate'),
                verified=False, evidence=[], reason='metacognitive deferral; no native outcome')
            row.update(phase='deferred')
            self._put(row)
            return deferred
        prediction = self.model.begin(body, q)
        if prediction != row['decision']['report']['inferred']:
            raise InterruptedExecution('self-model changed since selection; no native action issued')
        result = super().cycle(request, at_utc=at_utc, duration_s=duration_s, external={})
        self._finish_learning(row, result)
        return result
