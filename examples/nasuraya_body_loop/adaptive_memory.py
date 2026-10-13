"""Bounded, interpretable learning from verified native software-body receipts.

No model API, biology or calibrated probabilities. Native equations are untouched.
"""
from copy import deepcopy
import json
import math
import re
import time

from .self_maintenance import (IdentityContinuity, MaintenanceBlocked, PRINCIPLES,
                               canonical, digest, plan, unit)

FIELDS = ('energy', 'fatigue', 'sleep_pressure', 'pain', 'balance')
ALPHA = .5
DELTA_LIMIT = .1
ERROR_FLOOR = .005
MAX_EPISODES = 256
MAX_VERSIONS = 512
SCHEMA = 'nasuraya-adaptive-memory/1'


def state(snapshot):
    checkpoint = snapshot.get('checkpoint_sha256') if isinstance(snapshot,dict) else None
    if not isinstance(checkpoint,str) or not re.fullmatch('[0-9a-f]{64}', checkpoint):
        raise ValueError('valid checkpoint evidence required')
    values = {k: unit(snapshot.get('minimum_state', {}).get(k), k) for k in FIELDS}
    posture = snapshot['minimum_state'].get('posture')
    if not isinstance(posture, str) or not 1 <= len(posture) <= 40:
        raise ValueError('functional posture required')
    values['posture'] = posture
    # Validates temperature and the existing fixed safety envelope too.
    plan(snapshot)
    return values


def bucket(snapshot, action):
    if action not in ('walk', 'observe'):
        raise ValueError('only walk and observe are authorized')
    s = state(snapshot)
    risk = 'guarded' if plan(snapshot)['requested_action'] == 'observe' else 'normal'
    return action + '/' + risk + '/' + s['posture']


def initial_model():
    return {'schema': SCHEMA, 'alpha': ALPHA, 'delta_limit': DELTA_LIMIT,
            'error_floor': ERROR_FLOOR, 'buckets': {}, 'failure_streak': 0}


def validate_model(model):
    if set(model) != set(initial_model()) or any(model[k] != initial_model()[k] for k in
                                               ('schema', 'alpha', 'delta_limit', 'error_floor')):
        raise MaintenanceBlocked('model policy/schema changed')
    if type(model['failure_streak']) is not int or not 0 <= model['failure_streak'] <= MAX_EPISODES:
        raise MaintenanceBlocked('invalid failure streak')
    if not isinstance(model['buckets'], dict) or len(model['buckets']) > 64:
        raise MaintenanceBlocked('invalid model buckets')
    for key, item in model['buckets'].items():
        if not isinstance(key, str) or not re.fullmatch(r'(walk|observe)/(normal|guarded)/[^/]{1,40}', key):
            raise MaintenanceBlocked('invalid action bucket')
        if set(item) != {'count', 'delta', 'residual_bound', 'outcomes'}:
            raise MaintenanceBlocked('invalid parameter fields')
        if type(item['count']) is not int or not 1 <= item['count'] <= MAX_EPISODES:
            raise MaintenanceBlocked('invalid sample count')
        if set(item['delta']) != set(FIELDS) or set(item['residual_bound']) != set(FIELDS):
            raise MaintenanceBlocked('invalid prediction fields')
        for f in FIELDS:
            d, e = item['delta'][f], item['residual_bound'][f]
            if type(d) not in (float, int) or not math.isfinite(d) or abs(d) > DELTA_LIMIT:
                raise MaintenanceBlocked('parameter outside authorized bounds')
            if unit(e, 'residual_bound') < ERROR_FLOOR:
                raise MaintenanceBlocked('uncertainty floor cannot be lowered')
        if not isinstance(item['outcomes'], dict) or not set(item['outcomes']) <= {'walk', 'observe', 'protect'}:
            raise MaintenanceBlocked('invalid observed actions')
        if any(type(n) is not int or n <= 0 for n in item['outcomes'].values()) or sum(item['outcomes'].values()) != item['count']:
            raise MaintenanceBlocked('outcome count mismatch')
    return model


def forecast(model, snapshot, action, version):
    s = state(snapshot)
    key = bucket(snapshot, action)
    learned = model['buckets'].get(key)
    predicted = {f: min(1., max(0., s[f] + (learned['delta'][f] if learned else 0.))) for f in FIELDS}
    bounds = {f: min(1., max(ERROR_FLOOR, learned['residual_bound'][f])) if learned else 1. for f in FIELDS}
    outcome = max(learned['outcomes'], key=lambda a: (learned['outcomes'][a], a)) if learned else 'unknown'
    return {'model_version': version, 'before_sha': snapshot['checkpoint_sha256'],
            'action': action, 'bucket': key, 'next_state': predicted,
            'predicted_actual_action': outcome, 'samples': learned['count'] if learned else 0,
            'uncertainty': {'kind': 'empirical_residual_envelope_not_probability',
                            'bounds': bounds, 'unseen_context': learned is None},
            'reason': 'EMA of verified local deltas in action/safety/posture bucket' if learned else
                      'no verified history for bucket; persistence baseline, outcome unknown',
            'scope': 'one 0.1-second synthetic UnifiedBody cycle only'}


def errors(prediction, after):
    actual = state(after)
    signed = {f: actual[f] - prediction['next_state'][f] for f in FIELDS}
    return {'signed': signed, 'absolute': {f: abs(signed[f]) for f in FIELDS},
            'mae': sum(abs(x) for x in signed.values()) / len(FIELDS)}


def learn(model, before, prediction, receipt):
    updated = deepcopy(model)
    error = errors(prediction, receipt['self_model_after'])
    key = prediction['bucket']
    item = updated['buckets'].setdefault(key, {'count': 0, 'delta': {f: 0. for f in FIELDS},
                                              'residual_bound': {f: ERROR_FLOOR for f in FIELDS}, 'outcomes': {}})
    pre, post = state(before), state(receipt['self_model_after'])
    for f in FIELDS:
        delta = max(-DELTA_LIMIT, min(DELTA_LIMIT, post[f] - pre[f]))
        item['delta'][f] = max(-DELTA_LIMIT, min(DELTA_LIMIT, (1-ALPHA)*item['delta'][f] + ALPHA*delta))
        item['residual_bound'][f] = max(item['residual_bound'][f], error['absolute'][f], ERROR_FLOOR)
    item['count'] += 1
    actual = receipt['actual_action']
    item['outcomes'][actual] = item['outcomes'].get(actual, 0) + 1
    updated['failure_streak'] = min(MAX_EPISODES, model['failure_streak'] + 1) if error['mae'] > .05 else 0
    return validate_model(updated), error


def choose_action(model, snapshot, version):
    """Fixed safety policy; learning may only affect its local forecasts."""
    action = plan(snapshot)['requested_action']
    prediction = forecast(model,snapshot,action,version)
    if action == 'walk' and (
            prediction['uncertainty']['unseen_context'] or
            max(prediction['uncertainty']['bounds'].values()) > .05 or
            model['failure_streak'] >= 3 or prediction['predicted_actual_action'] != 'walk' or
            prediction['next_state']['energy'] <= .25 or prediction['next_state']['fatigue'] >= .45 or
            prediction['next_state']['pain'] >= .70 or prediction['next_state']['balance'] <= .35 or
            prediction['next_state']['sleep_pressure'] >= .65):
        action = 'observe'
    return action


class AdaptiveMemory:
    """Intent before action; verified outcome + model revision in one transaction.

    Integrity hashes detect damage, not an authenticated malicious database rewrite.
    The trusted producer is this process's existing locked native ledger only.
    """
    def __init__(self, loop, *, adaptive=True):
        if type(adaptive) is not bool:
            raise ValueError('explicit adaptive flag required')
        self.loop, self.db, self.adaptive = loop, loop.engine.db, adaptive
        self.identity = IdentityContinuity(self.db)
        existed = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='nasu_predictor_versions'").fetchone()
        self.db.execute('''CREATE TABLE IF NOT EXISTS nasu_predictor_versions (
            version INTEGER PRIMARY KEY, parent_hash TEXT NOT NULL, record TEXT NOT NULL, hash TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS nasu_experiences (
            id TEXT PRIMARY KEY, intent TEXT NOT NULL, intent_hash TEXT NOT NULL,
            result TEXT, result_hash TEXT)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS nasu_adaptive_goals (
            id TEXT PRIMARY KEY, contract TEXT NOT NULL, hash TEXT NOT NULL)''')
        if not self.db.execute('SELECT 1 FROM nasu_predictor_versions').fetchone():
            if existed:
                raise MaintenanceBlocked('model history missing; implicit reset forbidden')
            with loop.engine.transaction():
                self._append(initial_model(), 'initialize fixed local predictor contract', 'design://adaptive-v01', 'init')
        self.verify()

    def _append(self, model, reason, source, kind):
        row = self.db.execute('SELECT version,hash FROM nasu_predictor_versions ORDER BY version DESC LIMIT 1').fetchone()
        v, parent = (row[0]+1, row[1]) if row else (1, 'GENESIS')
        if v > MAX_VERSIONS:
            raise MaintenanceBlocked('model version budget exhausted')
        record = {'version': v, 'parent': parent, 'model': validate_model(model), 'adaptive': self.adaptive,
                  'reason': reason, 'source': source, 'kind': kind,
                  'principles': list(PRINCIPLES)}
        self.db.execute('INSERT INTO nasu_predictor_versions VALUES (?,?,?,?)', (v, parent, canonical(record), digest(record)))
        return v

    def verify(self):
        self.identity.verify()
        parent, expected, model = 'GENESIS', 1, None
        versions, experiences = {}, {}
        for v, prev, raw, h in self.db.execute('SELECT * FROM nasu_predictor_versions ORDER BY version'):
            try:
                r = json.loads(raw)
                valid = (v == expected and prev == parent and r['version'] == v and r['parent'] == prev
                         and r['adaptive'] == self.adaptive and r['principles'] == list(PRINCIPLES) and digest(r) == h)
                model = validate_model(r['model'])
            except (ValueError, TypeError, KeyError) as exc:
                raise MaintenanceBlocked('corrupt model memory') from exc
            if not valid or expected > MAX_VERSIONS:
                raise MaintenanceBlocked('model version chain/policy mismatch')
            versions[v] = r
            parent, expected = h, expected+1
        if model is None:
            raise MaintenanceBlocked('model history missing')
        for id_, raw, h, result, rh in self.db.execute('SELECT * FROM nasu_experiences'):
            try:
                intent = json.loads(raw)
                state(intent['before'])
                if digest(intent) != h or intent['id'] != id_:
                    raise MaintenanceBlocked('corrupt experience intent')
                pv = intent['prediction']['model_version']
                if pv not in versions or intent['prediction'] != forecast(
                        versions[pv]['model'],intent['before'],intent['action'],pv):
                    raise MaintenanceBlocked('prediction conflicts with recorded model version')
                experiences[id_] = (intent, None)
                if result is not None:
                    saved = json.loads(result)
                    if digest(saved) != rh:
                        raise MaintenanceBlocked('corrupt experience result')
                    native = self._native(id_, intent)
                    if saved['receipt'] != native or saved['error'] != errors(intent['prediction'], native['self_model_after']):
                        raise MaintenanceBlocked('experience conflicts with verified native result')
                    if saved['model_before'] != pv or saved['model_after'] != pv+1 or saved['learned'] != self.adaptive:
                        raise MaintenanceBlocked('experience model version conflict')
                    experiences[id_] = (intent, saved)
            except (ValueError, KeyError, TypeError) as exc:
                raise MaintenanceBlocked('corrupt experience memory') from exc
        # Every parameter revision must be reconstructible from its verified producer.
        for v, record in versions.items():
            try:
                if v == 1:
                    valid = record['kind'] == 'init' and record['model'] == initial_model()
                elif record['kind'] == 'revert':
                    source = int(record['source'].removeprefix('model-version://'))
                    valid = source < v and record['model'] == versions[source]['model']
                elif record['kind'] in ('learn','baseline-observation'):
                    id_ = record['source'].removeprefix('native-ledger://')
                    intent, saved = experiences[id_]
                    target,_ = learn(versions[v-1]['model'],intent['before'],intent['prediction'],saved['receipt'])
                    valid = (saved['model_after'] == v and record['model'] ==
                             (target if self.adaptive else versions[v-1]['model']))
                else:
                    valid = False
            except (ValueError,KeyError,TypeError) as exc:
                raise MaintenanceBlocked('missing revision provenance') from exc
            if not valid:
                raise MaintenanceBlocked('unauthorized parameter revision')
        return expected-1, deepcopy(model)

    def predict(self, snapshot, action):
        version, model = self.verify()
        return forecast(model, snapshot, action, version)

    def _native(self, id_, intent):
        record = self.loop.engine.get(id_)
        if record is None or record['status'] != 'complete':
            raise MaintenanceBlocked('unknown action outcome; automatic replay forbidden')
        receipt = self.loop.receipt(record, replayed=False)
        request = record['request']
        if (receipt['status'] != 'complete' or receipt['actual_action'] not in ('walk','observe','protect')
                or request['execution']['duration_s'] != .1):
            raise MaintenanceBlocked('unverified or unsupported native result')
        evidence = next((e for e in request['evidence'] if e['id'] == 'body'), None)
        preferred = max(request['actions'], key=lambda a: a['score']['respect'])['id']
        if evidence is None or evidence['source_sha256'] != intent['before']['checkpoint_sha256'] or preferred != intent['action']:
            raise MaintenanceBlocked('native provenance/action conflict')
        audit = receipt['body_audit']
        if not audit or not audit.get('same_owner_ticks') or any(
                type(audit.get(f)) not in (float, int) or not math.isfinite(audit[f]) or abs(audit[f]) > limit
                for f, limit in [('energy_error_J', 1e-6), ('water_error_L', 1e-9), ('light_error_J', 1e-6)]):
            raise MaintenanceBlocked('native body audit failed')
        state(receipt['self_model_after'])
        return receipt

    def _finish(self, id_, *, fault=None):
        row = self.db.execute('SELECT intent,result FROM nasu_experiences WHERE id=?', (id_,)).fetchone()
        intent = json.loads(row[0])
        if row[1] is not None:
            return json.loads(row[1])
        receipt = self._native(id_, intent)
        version, model = self.verify()
        if version != intent['prediction']['model_version']:
            raise MaintenanceBlocked('model diverged while action outcome pending')
        updated, error = learn(model, intent['before'], intent['prediction'], receipt)
        result = {'receipt': receipt, 'error': error, 'learned': self.adaptive,
                  'source': 'native-ledger://' + id_, 'model_before': version}
        with self.loop.engine.transaction():
            new = self._append(updated if self.adaptive else model, 'verified native outcome prediction error',
                               result['source'], 'learn' if self.adaptive else 'baseline-observation')
            result['model_after'] = new
            if fault:
                fault('during_learning')
            self.db.execute('UPDATE nasu_experiences SET result=?,result_hash=? WHERE id=? AND result IS NULL',
                            (canonical(result), digest(result), id_))
        return result

    def reconcile(self):
        self.verify()
        for id_, in self.db.execute('SELECT id FROM nasu_experiences WHERE result IS NULL ORDER BY rowid').fetchall():
            self._finish(id_)

    def execute(self, id_, action, *, goal='explicit local experiment', fault=None):
        if not isinstance(id_, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', id_):
            raise ValueError('bounded experience id required')
        if action not in ('walk','observe') or not isinstance(goal, str) or not 1 <= len(goal) <= 200:
            raise ValueError('bounded authorized action and goal required')
        self.verify()
        row = self.db.execute('SELECT intent,result FROM nasu_experiences WHERE id=?', (id_,)).fetchone()
        if row:
            intent = json.loads(row[0])
            if intent['action'] != action or intent['goal'] != goal:
                raise MaintenanceBlocked('conflicting experience replay')
            if row[1]:
                return json.loads(row[1])
            # Resolve from native ledger only, never call step again.
            return self._finish(id_)
        self.reconcile()
        current = self.loop.status()
        if current['mode'] != 'bounded' or current['actions_remaining'] <= 0 or current['unresolved_running']:
            raise MaintenanceBlocked('native authorization, budget or pending outcome blocks action')
        if self.db.execute('SELECT COUNT(*) FROM nasu_experiences').fetchone()[0] >= MAX_EPISODES:
            raise MaintenanceBlocked('experience storage budget exhausted')
        snapshot = self.loop.observe()
        # Changing body outside the last confirmed episode is not silently accepted.
        last = self.db.execute('SELECT result FROM nasu_experiences WHERE result IS NOT NULL ORDER BY rowid DESC LIMIT 1').fetchone()
        if last and json.loads(last[0])['receipt']['self_model_after']['checkpoint_sha256'] != snapshot['checkpoint_sha256']:
            raise MaintenanceBlocked('body changed outside adaptive contract')
        if self.loop.engine.get(id_) is not None:
            raise MaintenanceBlocked('native decision id already owned by another request')
        prediction = self.predict(snapshot, action)
        intent = {'id': id_, 'before': snapshot, 'action': action, 'goal': goal,
                  'reason': 'explicit bounded experimental action through existing DecisionCore',
                  'decision_evidence': {'fixed_safety_plan': plan(snapshot),
                                        'selection_kind': 'fixed predictive policy' if goal == 'bounded predictive self-maintenance' else 'explicit experiment contract'},
                  'prediction': prediction}
        self.db.execute('INSERT INTO nasu_experiences VALUES (?,?,?,NULL,NULL)', (id_, canonical(intent), digest(intent)))
        if fault:
            fault('after_intent')
        self.loop.step(decision_id=id_, duration_s=.1, preferred_action=action)
        if fault:
            fault('after_native_commit')
        return self._finish(id_, fault=fault)

    def revert_to(self, version, *, reason):
        self.reconcile()
        if type(version) is not int or not isinstance(reason,str) or not 8 <= len(reason) <= 200:
            raise ValueError('version and explicit revert reason required')
        row = self.db.execute('SELECT record FROM nasu_predictor_versions WHERE version=?', (version,)).fetchone()
        if not row:
            raise ValueError('unknown model version')
        with self.loop.engine.transaction():
            return self._append(json.loads(row[0])['model'], reason, 'model-version://' + str(version), 'revert')

    def run_goal(self, goal_id, *, target_cycles=3, time_budget_s=30.):
        if not isinstance(goal_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}',goal_id):
            raise ValueError('bounded goal id required')
        if type(target_cycles) is not int or not 1 <= target_cycles <= 3:
            raise ValueError('goal cycles must be 1..3')
        if type(time_budget_s) not in (float,int) or not math.isfinite(time_budget_s) or not 1 <= time_budget_s <= 60:
            raise ValueError('time budget must be 1..60 seconds')
        self.reconcile()
        contract = {'id': goal_id, 'cycles': target_cycles, 'time_budget_s': float(time_budget_s),
                    'goal': 'bounded predictive self-maintenance', 'allowed': ['walk','observe']}
        row = self.db.execute('SELECT contract,hash FROM nasu_adaptive_goals WHERE id=?',(goal_id,)).fetchone()
        if row and (json.loads(row[0]) != contract or digest(contract) != row[1]):
            raise MaintenanceBlocked('goal contract conflict or corruption')
        if not row:
            if self.db.execute('SELECT COUNT(*) FROM nasu_adaptive_goals').fetchone()[0] >= MAX_EPISODES:
                raise MaintenanceBlocked('goal storage budget exhausted')
            self.db.execute('INSERT INTO nasu_adaptive_goals VALUES (?,?,?)',(goal_id,canonical(contract),digest(contract)))
        start = time.monotonic()
        history = []
        for i in range(target_cycles):
            id_ = 'adapt-' + goal_id + '-' + str(i+1)
            old = self.db.execute('SELECT intent,result FROM nasu_experiences WHERE id=?',(id_,)).fetchone()
            if old:
                if json.loads(old[0])['goal'] != contract['goal']:
                    raise MaintenanceBlocked('goal experience id conflict')
                if not old[1]:
                    raise MaintenanceBlocked('goal outcome unresolved')
                history.append(json.loads(old[1]))
                continue
            if time.monotonic()-start >= time_budget_s:
                return {'status':'time_budget_exhausted','history':history}
            snapshot = self.loop.observe()
            version, model = self.verify()
            proposal = choose_action(model,snapshot,version)
            history.append(self.execute(id_, proposal, goal=contract['goal']))
        return {'status':'completed','history':history,'model_version':self.verify()[0],
                'identity_principles':self.identity.verify()['principles'],
                'actions_remaining':self.loop.status()['actions_remaining'],'api_calls':0}
