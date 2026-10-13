"""Source-linked task decisions and durable feedback around DecisionCore v0.1.

SQLite is the external experience ledger, not model weights. Source labels are
caller declarations; this module does not authenticate truth or read sensors.
Executors are explicit Python callbacks. No shell/network executor is included.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from typing import Callable

from decision_core import Action, Consequence, DecisionCore

SCHEMA = 'tadash-reflection-cycle/0.1'
FAILURE_PENALTY = .6
MAX_DECISIONS = 10000
RUNTIME_VERSION = '0.2'
KINDS = {'observed', 'inference', 'authored'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError('bounded nonempty string required: ' + name)
    return value


def instant(value):
    d = datetime.fromisoformat(value)
    if d.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    return d.astimezone(timezone.utc)


def validate_evidence(rows):
    if not isinstance(rows, list) or len(rows) > 128:
        raise ValueError('bounded evidence list required')
    ids = set()
    for row in rows:
        required = {'id', 'kind', 'source_ref', 'locator', 'source_sha256', 'claim'}
        if not isinstance(row, dict) or not required <= set(row) or set(row)-required-{'expires_at'}:
            raise ValueError('complete evidence locator required')
        for key in ('id', 'source_ref', 'locator'):
            identifier(row[key], key)
        if row['id'] in ids or row['kind'] not in KINDS:
            raise ValueError('duplicate evidence id or unknown origin')
        ids.add(row['id'])
        h = row['source_sha256']
        if not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise ValueError('source digest required')
        claim = row['claim']
        if not isinstance(claim, dict) or set(claim) != {'key', 'value'}:
            raise ValueError('explicit claim key/value required')
        identifier(claim['key'], 'claim key')
        if 'expires_at' in row:
            instant(row['expires_at'])
        canonical(row)
    return deepcopy(rows)


def action_signature(candidate):
    contract = {key: candidate.get(key) for key in
        ('id', 'claims', 'requires_evidence', 'requires_tools', 'violates_goals', 'body_action', 'expected_outcome')}
    for key in ('requires_evidence', 'requires_tools', 'violates_goals'):
        contract[key] = sorted(set(contract[key] or []))
    contract['claims'] = sorted(contract['claims'] or [], key=canonical)
    return digest(contract)


def core_action(candidate):
    score = deepcopy(candidate['score'])
    consequences = tuple(Consequence(**x) for x in score.pop('consequences'))
    return Action(id=candidate['id'], consequences=consequences, **score)


def validate_request(request):
    r = deepcopy(request)
    required = {'id', 'context', 'topic', 'goal', 'goals', 'at_utc', 'evidence', 'tools', 'actions'}
    if not isinstance(r, dict) or not required <= set(r) or set(r)-required-{'execution'}:
        raise ValueError('request contract mismatch')
    for key in ('id', 'context', 'topic', 'goal'):
        identifier(r[key], key)
    instant(r['at_utc']); validate_evidence(r['evidence'])
    if not isinstance(r['goals'], list) or len(r['goals']) > 32:
        raise ValueError('bounded goal constraints required')
    goal_ids = set()
    for g in r['goals']:
        if not isinstance(g, dict) or set(g) != {'id', 'required'} or type(g['required']) is not bool:
            raise ValueError('explicit goal constraint required')
        identifier(g['id'], 'goal id')
        if g['id'] in goal_ids:
            raise ValueError('duplicate goal id')
        goal_ids.add(g['id'])
    if not isinstance(r['tools'], dict) or len(r['tools']) > 32:
        raise ValueError('bounded tool status map required')
    for key, value in r['tools'].items():
        identifier(key, 'tool')
        if value not in {'ok', 'failed', 'unknown'}:
            raise ValueError('unknown tool status')
    if not isinstance(r['actions'], list) or not 1 <= len(r['actions']) <= 32:
        raise ValueError('one to 32 candidates required')
    ids = set()
    fields = {'id', 'score', 'claims', 'requires_evidence', 'requires_tools', 'violates_goals', 'expected_outcome'}
    for c in r['actions']:
        if not isinstance(c, dict) or not fields <= set(c) or set(c)-fields-{'body_action'}:
            raise ValueError('candidate contract mismatch')
        identifier(c['id'], 'action id')
        if c['id'] in ids:
            raise ValueError('duplicate action id')
        ids.add(c['id']); core_action(c)
        for key in ('requires_evidence', 'requires_tools', 'violates_goals'):
            if not isinstance(c[key], list) or len(c[key]) > 32:
                raise ValueError('bounded requirements required')
            for item in c[key]: identifier(item, key)
        if not isinstance(c['claims'], list) or len(c['claims']) > 32:
            raise ValueError('bounded proposed claims required')
        for claim in c['claims']:
            if not isinstance(claim, dict) or set(claim) != {'key', 'value'}:
                raise ValueError('proposed claim contract mismatch')
            identifier(claim['key'], 'proposed claim key')
        if not isinstance(c['expected_outcome'], dict) or not c['expected_outcome']:
            raise ValueError('nonempty expected outcome required')
        if set(c['violates_goals']) - goal_ids:
            raise ValueError('unknown goal conflict')
        if 'body_action' in c: identifier(c['body_action'], 'body action')
    encoded = canonical(r)
    if len(encoded.encode()) > 128*1024:
        raise ValueError('request exceeds size limit')
    return r


def outcome_matches(expected, actual):
    return isinstance(actual, dict) and all(key in actual and canonical(actual[key]) == canonical(value)
        for key, value in expected.items())


class InterruptedExecution(RuntimeError):
    """The previous callback may have run; verify its outcome before retrying."""


class ReflectionCycle:
    def __init__(self, path, *, use_memory=True):
        if type(use_memory) is not bool:
            raise ValueError('explicit memory switch required')
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.use_memory = use_memory; self.core = DecisionCore()
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if names:
            if 'meta' not in names:
                self.close(); raise ValueError('not a reflection ledger')
            row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row is None or row[0] != SCHEMA:
                self.close(); raise ValueError('unsupported reflection ledger schema')
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, seq INTEGER UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL, context TEXT NOT NULL, topic TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('planned','running','complete')),
                record TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS retrieval ON decisions(context,topic,seq);
            CREATE TABLE IF NOT EXISTS commitments(id TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY, digest TEXT NOT NULL, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback_index(context TEXT NOT NULL, topic TEXT NOT NULL,
                signature TEXT NOT NULL, seq INTEGER NOT NULL, decision_id TEXT UNIQUE NOT NULL,
                PRIMARY KEY(context,topic,signature,seq));
        ''')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema',?)", (SCHEMA,))
        # Derived index: original decisions are authoritative and never rewritten.
        with self.transaction():
            version = self.db.execute("SELECT value FROM meta WHERE key='feedback_index_version'").fetchone()
            if version is None or version[0] != RUNTIME_VERSION:
                self.db.execute('DELETE FROM feedback_index')
                for item in self.db.execute("SELECT record FROM decisions WHERE status='complete'").fetchall():
                    self._index_feedback(json.loads(item[0]))
                self.db.execute("INSERT OR REPLACE INTO meta VALUES('feedback_index_version',?)", (RUNTIME_VERSION,))
        self.engine_fingerprint = digest(dict(schema=SCHEMA, penalty=FAILURE_PENALTY,
            reflection_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            core_sha256=sha256(Path(__file__).with_name('decision_core.py').read_bytes()).hexdigest()))

    def close(self):
        if getattr(self, 'db', None) is not None:
            self.db.close(); self.db = None

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def _get(self, id):
        row = self.db.execute('SELECT record FROM decisions WHERE id=?', (id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, id):
        identifier(id, 'decision id'); return self._get(id)

    def _index_feedback(self, record):
        if not record['feedback']['verified']:
            return
        candidate = next(c for c in record['request']['actions'] if c['id'] == record['selected_action'])
        self.db.execute('INSERT OR IGNORE INTO feedback_index VALUES(?,?,?,?,?)',
            (record['context'],record['topic'],action_signature(candidate),record['sequence'],record['id']))

    def recall(self, context, topic, *, signatures=None, at_utc=None):
        identifier(context, 'context'); identifier(topic, 'topic')
        parameters = [context,topic]
        clause = ''
        if signatures is not None:
            signatures = sorted(set(signatures))
            if not signatures: return {}
            clause = ' AND f.signature IN (' + ','.join('?' for _ in signatures) + ')'
            parameters += signatures
        rows = self.db.execute('SELECT d.record,f.signature FROM feedback_index f JOIN decisions d ON d.id=f.decision_id '
            'WHERE f.context=? AND f.topic=?'+clause+' ORDER BY f.seq DESC', parameters)
        now = instant(at_utc) if at_utc else None
        latest = {}
        seen = set()
        for row in rows:
            r = json.loads(row[0]); f = r['feedback']
            signature = row[1]
            if signature in seen:
                continue
            seen.add(signature)
            # An explicitly expired observation cannot support a current preference.
            if now and not any(e['kind'] == 'observed' and
                    ('expires_at' not in e or instant(e['expires_at']) >= now) for e in f['evidence']):
                continue
            latest[signature] = dict(decision_id=r['id'], success=f['success'],
                reason=f['reason'], evidence=f['evidence'], historical=True)
        return latest

    def decide(self, request):
        r = validate_request(request)
        fingerprint = digest(dict(request=r, engine=self.engine_fingerprint, use_memory=self.use_memory))
        with self.transaction():
            old = self._get(r['id'])
            if old:
                if canonical(old['request']) != canonical(r) or old['use_memory'] != self.use_memory:
                    raise ValueError('conflicting request replay')
                return old
            if self.db.execute('SELECT count(*) FROM decisions').fetchone()[0] >= MAX_DECISIONS:
                raise ValueError('ledger capacity reached; export before expanding it')
            memories = self.recall(r['context'], r['topic'],
                signatures=[action_signature(c) for c in r['actions']],at_utc=r['at_utc']) if self.use_memory else {}
            now = instant(r['at_utc'])
            fresh = [e for e in r['evidence'] if 'expires_at' not in e or instant(e['expires_at']) >= now]
            observations = [e for e in fresh if e['kind'] == 'observed']
            known = {e['id'] for e in observations}
            required_goals = {g['id'] for g in r['goals'] if g['required']}
            legacy = self.core.decide(tuple(core_action(c) for c in r['actions'])).to_dict()
            by_id = {e['action_id']: e for e in legacy['options']}
            options = []; unknown = []
            for c in sorted(r['actions'], key=lambda x:x['id']):
                e = deepcopy(by_id[c['id']]); reasons = list(e['reasons'])
                for source in c['requires_evidence']:
                    if source not in known:
                        reasons.append('missing_observed_evidence:' + source); unknown.append('evidence:' + source)
                for claim in c['claims']:
                    matching = [o for o in observations if o['claim']['key'] == claim['key']]
                    values = {canonical(o['claim']['value']) for o in matching}
                    if len(values) > 1:
                        reasons.append('conflicting_observations:' + claim['key']); unknown.append('claim:' + claim['key'])
                    elif not any(canonical(o['claim']) == canonical(claim) for o in matching):
                        reasons.append('unsupported_claim:' + claim['key']); unknown.append('claim:' + claim['key'])
                for tool in c['requires_tools']:
                    if r['tools'].get(tool) != 'ok':
                        reasons.append('tool_unavailable:' + tool); unknown.append('tool:' + tool)
                for goal in sorted(set(c['violates_goals']) & required_goals):
                    reasons.append('required_goal_conflict:' + goal)
                sig = action_signature(c); feedback = memories.get(sig)
                penalty = FAILURE_PENALTY if feedback and not feedback['success'] else 0.
                # Gate on structural evidence/constraints independently of learned preference.
                gate = e['eligible'] and len(reasons) == len(e['reasons'])
                options.append(dict(action_id=c['id'], base_score=e['score'], adjusted_score=e['score']-penalty,
                    risk_upper=e['risk_upper'], uncertainty=e['uncertainty'], eligible=gate,
                    reasons=reasons, memory_penalty=penalty,
                    recalled_feedback_id=feedback['decision_id'] if feedback else None))
            eligible = sorted((e for e in options if e['eligible']), key=lambda e:(-e['adjusted_score'],e['uncertainty'],e['action_id']))
            winner = eligible[0]['action_id'] if eligible else None
            chosen = next((c for c in r['actions'] if c['id'] == winner), None)
            seq = self.db.execute('SELECT coalesce(max(seq),0)+1 FROM decisions').fetchone()[0]
            record = dict(schema=SCHEMA, id=r['id'], sequence=seq, request_fingerprint=fingerprint,
                engine_fingerprint=self.engine_fingerprint, context=r['context'], topic=r['topic'], goal=r['goal'],
                request=r, evidence=deepcopy(r['evidence']), unknown=sorted(set(unknown)),
                selected_action=winner, action_signature=action_signature(chosen) if chosen else None,
                expected_outcome=deepcopy(chosen['expected_outcome']) if chosen else None,
                actual_outcome=None, feedback=None, status='planned', options=options,
                recalled_feedback_ids=sorted({m['decision_id'] for m in memories.values()}),
                legacy_decision=legacy, use_memory=self.use_memory,
                decision_scope='deterministic scoring, explicit evidence contracts and scoped feedback')
            self.db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?)',
                (r['id'],seq,fingerprint,r['context'],r['topic'],'planned',canonical(record)))
            return record

    def complete(self, id, actual_outcome, *, verified, evidence, reason, runtime_update=None):
        if type(verified) is not bool or not isinstance(actual_outcome, dict):
            raise ValueError('explicit verification and outcome required')
        identifier(reason, 'feedback reason'); witnesses = validate_evidence(evidence)
        if verified and not any(e['kind'] == 'observed' for e in witnesses):
            raise ValueError('verified feedback requires an observed source-linked witness')
        canonical(actual_outcome)
        with self.transaction():
            r = self._get(id)
            if r is None or r['selected_action'] is None:
                raise ValueError('no selected decision to complete')
            feedback = dict(success=outcome_matches(r['expected_outcome'], actual_outcome),
                verified=verified, evidence=witnesses, reason=reason,
                verification_scope='source-linked caller/runtime declaration, not external authentication')
            if r['status'] == 'complete':
                if canonical(r['actual_outcome']) != canonical(actual_outcome) or canonical(r['feedback']) != canonical(feedback):
                    raise ValueError('conflicting feedback replay')
                return r
            if runtime_update is not None:
                key, before_digest, value = runtime_update
                row = self.db.execute('SELECT digest FROM runtime WHERE key=?', (key,)).fetchone()
                if row is None or row[0] != before_digest:
                    raise ValueError('runtime changed since execution began')
                self.db.execute('UPDATE runtime SET digest=?,value=? WHERE key=?', (digest(value),canonical(value),key))
            r.update(actual_outcome=deepcopy(actual_outcome), feedback=feedback, status='complete')
            self.db.execute('UPDATE decisions SET status=?,record=? WHERE id=?', ('complete',canonical(r),id))
            self._index_feedback(r)
            return r

    def execute(self, request, executor: Callable, *, verified=False, evidence=(), reason='declared callback outcome', runtime_hook=None):
        if type(verified) is not bool:
            raise ValueError('explicit verification switch required')
        identifier(reason, 'feedback reason')
        witnesses = validate_evidence(list(evidence))
        if verified and not any(e['kind'] == 'observed' for e in witnesses):
            raise ValueError('verified feedback requires an observed source-linked witness')
        r = self.decide(request)
        if r['selected_action'] is None or r['status'] == 'complete':
            return r
        with self.transaction():
            r = self._get(r['id'])
            if r['status'] == 'complete': return r
            if r['status'] == 'running':
                raise InterruptedExecution('previous execution outcome is unresolved; inspect and complete it explicitly')
            r['status'] = 'running'
            self.db.execute('UPDATE decisions SET status=?,record=? WHERE id=?', ('running',canonical(r),r['id']))
        c = next(c for c in r['request']['actions'] if c['id'] == r['selected_action'])
        try:
            actual = executor(deepcopy(c))
            if not isinstance(actual, dict): raise TypeError('executor must return an outcome object')
            canonical(actual)
        except Exception as error:
            actual = dict(status='executor_failed', error_type=type(error).__name__)
        update = runtime_hook(actual) if runtime_hook else None
        return self.complete(r['id'], actual, verified=verified, evidence=witnesses, reason=reason, runtime_update=update)

    def set_commitment(self, id, *, target, actual, source_ref, locator, status='open'):
        identifier(id, 'commitment'); identifier(source_ref, 'commitment source'); identifier(locator, 'commitment locator')
        if type(target) is not int or type(actual) is not int or target < 1 or actual < 0:
            raise ValueError('integer target and realized progress required')
        if status not in {'open','completed','blocked'} or (status == 'completed' and actual < target):
            raise ValueError('invalid commitment completion')
        row = dict(id=id,target=target,actual=actual,remaining=max(0,target-actual),source_ref=source_ref,locator=locator,status=status)
        with self.transaction():
            old = self.db.execute('SELECT record FROM commitments WHERE id=?', (id,)).fetchone()
            if old and json.loads(old[0])['target'] != target:
                raise ValueError('commitment target change requires a new explicit revision')
            self.db.execute('INSERT OR REPLACE INTO commitments VALUES(?,?)', (id,canonical(row)))
        return row

    def commitments(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT record FROM commitments ORDER BY id')]

    def attach_runtime(self, key, checkpoint):
        identifier(key, 'runtime key'); value=canonical(checkpoint)
        with self.transaction():
            row=self.db.execute('SELECT digest FROM runtime WHERE key=?',(key,)).fetchone()
            if row is not None and row[0] != digest(checkpoint):
                raise ValueError('existing runtime must be resumed, not overwritten')
            self.db.execute('INSERT OR IGNORE INTO runtime VALUES(?,?,?)',(key,digest(checkpoint),value))

    def runtime(self, key):
        row=self.db.execute('SELECT value FROM runtime WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def export(self):
        return dict(schema=SCHEMA, decisions=[json.loads(r[0]) for r in self.db.execute('SELECT record FROM decisions ORDER BY seq')],
            commitments=self.commitments(),runtime_keys=[r[0] for r in self.db.execute('SELECT key FROM runtime ORDER BY key')])

    def backup(self, path):
        path=Path(path)
        if path.exists(): raise ValueError('backup destination already exists')
        destination=sqlite3.connect(path)
        try:self.db.backup(destination)
        finally:destination.close()


class ReflectiveBody:
    """Sequential cognitive wrapper invoking the existing UnifiedBody.cycle.

    Durable actual body checkpoint and feedback share one SQLite commit. A
    crash between callback execution and commit leaves a running decision;
    it must be reconciled explicitly. No user checkpoint is loaded implicitly.
    """
    def __init__(self, engine, *, body=None, key='tadash-body'):
        self.engine=engine; self.key=key
        if body is not None: engine.attach_runtime(key,body.checkpoint())
        if engine.runtime(key) is None: raise ValueError('attach or explicitly resume a body first')

    def cycle(self, request, *, at_utc, duration_s=.1, external=None):
        import unified_body_v2 as native_runtime
        UnifiedBody, ACTIONS = native_runtime.UnifiedBody, native_runtime.ACTIONS
        if instant(request['at_utc']) != instant(at_utc):
            raise ValueError('decision and execution clocks must match')
        request=deepcopy(request)
        request['execution']=dict(runtime_key=self.key,at_utc=instant(at_utc).isoformat(),
            duration_s=duration_s,external=deepcopy(external or {}))
        for c in request['actions']:
            if c.get('body_action') not in ACTIONS:
                raise ValueError('existing body action required for each candidate')
        envelope=self.engine.runtime(self.key); before=digest(envelope)
        body=UnifiedBody.restore(envelope)
        def executor(c):
            receipt=body.cycle(event_id='reflection:'+request['id'],at_utc=at_utc,
                duration_s=duration_s,external=external or {},requested=c['body_action'],expected_revision=body.revision)
            return dict(status='completed',selected_action=receipt['owner']['selected_action'],
                body_receipt=receipt,body_checkpoint=body.checkpoint())
        witness=dict(id='runtime:'+request['id'],kind='observed',source_ref='runtime://UnifiedBody.cycle',
            locator='event/reflection:'+request['id'],
            source_sha256=sha256(Path(native_runtime.__file__).read_bytes()).hexdigest(),
            claim=dict(key='verification',value='actual returned software body receipt'))
        def hook(actual):
            if 'body_checkpoint' not in actual: return None
            return (self.key,before,actual['body_checkpoint'])
        return self.engine.execute(request,executor,verified=True,evidence=[witness],
            reason='observed software runtime return or caught callback failure',runtime_hook=hook)
