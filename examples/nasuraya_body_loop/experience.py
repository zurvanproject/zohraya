"""Receipt-grounded affect, self-prediction and consolidation for BodyLoop.

Original stdlib implementation informed by four documented upstream designs.
State belongs to the external software agent, not the conversational model.
No background worker, LLM call, sampled neurochemistry or consciousness score.
"""
from copy import deepcopy
from datetime import datetime
import math
import re

from reflection_cycle import canonical, digest, InterruptedExecution
from .host import BodyLoop, executed_body, validate_duration
from .affect_audit import audit_affect
from .self_knowledge import forecast_action, score_action, summarize_action_forecasts

KEY = 'nasuraya-experience/1'
METRICS = ('energy', 'fatigue', 'pain', 'sleep_pressure')
FLAGS = ('affect', 'prediction', 'memory', 'consolidation')


def clamp(x):
    return max(0., min(1., x))


def metrics(snapshot):
    result = {k: snapshot['minimum_state'][k] for k in METRICS}
    for value in result.values():
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError('finite normalized body observation required')
    return result


def seconds(snapshot):
    at = datetime.fromisoformat(snapshot['simulated_wall_utc'])
    if at.tzinfo is None:
        raise ValueError('aware simulated clock required')
    return at.timestamp()


def context(m):
    # Physical condition, never a fixture label or identity assertion.
    return canonical([m['energy'] < .25, m['fatigue'] > .52,
                      m['pain'] > .4, m['sleep_pressure'] > .65])


def initial_state(config, flags):
    return dict(schema=KEY, native_config=deepcopy(config), flags=flags,
                affect=dict(valence=.65, arousal=.35), error_ema=0.,
                predictors={}, episodes=[], intents={}, summaries=[],
                hypotheses=[], self_models=[], consolidated_digest=None,
                scope='engineering_state_from_software_receipts')


def _policy_plan(state, snapshot, duration_s):
    m = metrics(snapshot); ctx = context(m); now = seconds(snapshot)
    recalled = []
    if state['flags']['memory']:
        candidates = [e for e in state['episodes'] if not e['archived'] and e['context'] == ctx]
        candidates.sort(key=lambda e: (
            e['strength'] * e['importance'] * math.exp(-max(0., now-e['at'])/86400.),
            e['id']), reverse=True)
        recalled = candidates[:8]
    # Only an actual protection/pain outcome penalizes the associated preference.
    risk = max((e['harm'] * e['strength'] for e in recalled if e['preferred'] == 'walk'), default=0.)
    valence, arousal = .5, 0.
    if state['flags']['affect']:
        valence, arousal = state['affect']['valence'], state['affect']['arousal']
    scores = dict(walk=.7 + .15*(valence-.5) - .2*arousal - .65*risk,
                  observe=.35 + .2*arousal)
    if state['flags']['prediction']:
        scores['walk'] -= .15*state['error_ema']
    preferred = max(('walk', 'observe'), key=lambda a: (scores[a], a))
    key = canonical([ctx, preferred, duration_s])
    model = state['predictors'].get(key)
    delta = model['mean_delta'] if state['flags']['prediction'] and model else dict.fromkeys(METRICS, 0.)
    return dict(preferred=preferred, scores=scores, context=ctx,
                recalled=[e['id'] for e in recalled], memory_risk=risk,
                prediction=dict(key=key, before=m, expected={k: clamp(m[k]+delta[k]) for k in METRICS},
                    prior_samples=model['count'] if model else 0,
                    scope='next software state given controller preference; not calibrated probability'))


def plan(state, snapshot, duration_s):
    """Freeze predictions and matched-state diagnostics before body execution.

    The categorical forecast uses only earlier receipt-grounded episodes. The
    policy audit evaluates copies; neither it nor the forecast executes actions
    or overrides the existing controller/native protection.
    """
    proposed = _policy_plan(state, snapshot, duration_s)
    proposed['action_forecast'] = forecast_action(
        state['episodes'], context=proposed['context'],
        preferred=proposed['preferred'], duration_s=duration_s,
        enabled=state['flags']['prediction'])
    proposed['affect_audit'] = audit_affect(state, snapshot, duration_s, _policy_plan)
    return proposed


class ExperienceController:
    """Optional controller using the existing inode lock, budget and native veto.

    Intents precede execution. Native completion is authoritative; a crash after
    that commit is reconciled without repeating the physical software cycle.
    """
    def __init__(self, loop):
        if not isinstance(loop, BodyLoop):
            raise ValueError('existing locked BodyLoop required')
        self.loop = loop
        self._load()

    @classmethod
    def enable(cls, loop, **overrides):
        if not isinstance(loop, BodyLoop) or loop.config['mode'] != 'bounded':
            raise ValueError('bounded BodyLoop required')
        if set(overrides)-set(FLAGS) or any(type(v) is not bool for v in overrides.values()):
            raise ValueError('explicit boolean feature flags required')
        flags = {k: overrides.get(k, True) for k in FLAGS}
        state = initial_state(loop.config, flags)
        loop.engine.db.execute('INSERT INTO meta VALUES(?,?)',
            (KEY, canonical(dict(value=state, sha256=digest(state)))))
        return cls(loop)

    def _load(self):
        import json
        row = self.loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if row is None:
            raise ValueError('enable the experience controller explicitly first')
        envelope = json.loads(row[0]); state = envelope['value']
        if (digest(state) != envelope['sha256'] or state['schema'] != KEY or
                state['native_config'] != self.loop.config or
                set(state['flags']) != set(FLAGS) or
                any(type(v) is not bool for v in state['flags'].values())):
            raise ValueError('experience state integrity/contract mismatch')
        return state

    def _save(self, state):
        self.loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?',
            (canonical(dict(value=state, sha256=digest(state))), KEY))

    def status(self):
        state = self._load()
        return dict(state=state, native=self.loop.status(), external_model_api_used=False,
                    background_process_started=False,
                    self_knowledge=summarize_action_forecasts(state['intents']))

    def _finish(self, state, request_id, record, *, replayed):
        intent = state['intents'][request_id]
        request = record['request']; execution = request.get('execution', {})
        if ({k:v for k,v in request.items() if k != 'execution'} != intent['native_request'] or
                execution.get('duration_s') != intent['duration_s'] or
                execution.get('runtime_key') != 'nasuraya-body-loop' or execution.get('external') != {}):
            raise ValueError('native receipt differs from reserved experience intent')
        receipt = self.loop.receipt(record, replayed=replayed)
        p = intent['plan']; prediction = deepcopy(p['prediction'])
        ran = executed_body(record)
        action_forecast_score = None
        if ran:
            after = metrics(receipt['self_model_after']); before = prediction['before']
            error = sum(abs(after[k]-prediction['expected'][k]) for k in METRICS)/len(METRICS)
            prediction.update(actual=after, mean_absolute_error=error,
                              source='native-decision://' + record['id'] + '/' + digest(record))
            # The old reserved plan is authoritative, including on recovery.
            # Legacy intents have no categorical forecast: never backfill one
            # after observing the result, which would leak the answer.
            if 'action_forecast' in p:
                action_forecast_score = score_action(
                    p['action_forecast'], receipt['actual_action'], prediction['source'])
            if state['flags']['prediction']:
                state['error_ema'] = .8*state['error_ema'] + .2*error
                model = state['predictors'].setdefault(prediction['key'], dict(count=0, mean_delta=dict.fromkeys(METRICS, 0.)))
                model['count'] += 1
                for k in METRICS:
                    model['mean_delta'][k] += (after[k]-before[k]-model['mean_delta'][k])/model['count']
            harm = max(float(receipt['actual_action'] == 'protect'), clamp(after['pain']-before['pain']))
            now = seconds(receipt['self_model_after'])
            if state['flags']['affect']:
                affect = state['affect']
                decay = math.exp(-intent['duration_s']/60.)
                # Outcome appraisal uses actual need change, not relief from recalled fear.
                benefit = (after['energy']-before['energy']) + (before['fatigue']-after['fatigue'])
                affect['valence'] = clamp(.65+(affect['valence']-.65)*decay + .2*benefit - .25*harm)
                load = max(after['fatigue'], after['pain'], after['sleep_pressure'])
                affect['arousal'] = clamp(.35+(affect['arousal']-.35)*decay + .25*harm + .1*load + error)
            for e in state['episodes']:
                if e['id'] in p['recalled']:
                    e['strength'] = min(1., e['strength']+.1)
                    e['accesses'] += 1
            state['episodes'].append(dict(id=request_id, context=p['context'], preferred=p['preferred'],
                duration_s=intent['duration_s'],
                actual_action=receipt['actual_action'], harm=harm, importance=max(.2, harm, error),
                strength=1., accesses=0, at=now, last_decay_at=now, archived=False,
                source=prediction['source'], kind='observed_software_outcome'))
        else:
            prediction.update(actual=None, mean_absolute_error=None, unresolved=True)
        result = dict(request_id=request_id, plan=deepcopy(p), prediction=prediction,
                      action_forecast_score=action_forecast_score,
                      affect_after=deepcopy(state['affect']), native_receipt=receipt,
                      replayed=replayed, this_call_native_cycles=0 if replayed else int(ran))
        intent['result'] = result
        self._save(state)
        return deepcopy(result)

    def step(self, request_id, *, duration_s=.1):
        validate_duration(duration_s)
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', request_id):
            raise ValueError('bounded request ID required')
        state = self._load(); old = state['intents'].get(request_id)
        if old:
            if old['duration_s'] != duration_s:
                raise ValueError('conflicting experience replay')
            if old['result'] is not None:
                result = deepcopy(old['result']); result['replayed'] = True; result['this_call_native_cycles'] = 0
                return result
            record = self.loop.engine.get(old['native_id'])
            if record is not None:
                if record['status'] != 'complete':
                    raise InterruptedExecution('native experience outcome unresolved')
                return self._finish(state, request_id, record, replayed=True)
            if self.loop.body().checkpoint()['sha256'] != old['snapshot']['checkpoint_sha256']:
                raise InterruptedExecution('body changed after experience intent reservation')
        else:
            if any(v['result'] is None for v in state['intents'].values()):
                raise InterruptedExecution('reconcile pending experience intent first')
            status = self.loop.status()
            if status['unresolved_running']:
                raise InterruptedExecution('native outcome unresolved')
            if status['actions_remaining'] <= 0:
                raise ValueError('persistent action budget exhausted')
            native_id = 'experience:' + request_id
            if self.loop.engine.get(native_id) is not None:
                raise ValueError('native ID already belongs to another operation')
            snapshot = self.loop.observe()
            proposed = plan(state, snapshot, duration_s)
            old = dict(native_id=native_id, duration_s=duration_s, snapshot=snapshot, plan=proposed,
                       native_request=self.loop.make_request(native_id, snapshot, duration_s, proposed['preferred']), result=None)
            state['intents'][request_id] = old
            self._save(state)
        self.loop.observe()
        self.loop.step(decision_id=old['native_id'], duration_s=duration_s, preferred_action=old['plan']['preferred'])
        record = self.loop.engine.get(old['native_id'])
        return self._finish(state, request_id, record, replayed=False)

    def consolidate(self):
        state = self._load()
        if any(v['result'] is None for v in state['intents'].values()):
            raise InterruptedExecution('reconcile pending experience before consolidation')
        if not state['flags']['consolidation']:
            return dict(enabled=False, changed=False)
        now = seconds(self.loop.observe())
        changed = False
        for e in state['episodes']:
            elapsed = max(0., now-e['last_decay_at'])
            if elapsed:
                stability = 1. + e['importance']*2. + e['accesses']*.5
                e['strength'] *= math.exp(-elapsed/(86400.*stability))
                e['last_decay_at'] = now
                # Keep safety-relevant evidence retrievable. No destructive purge.
                e['archived'] = e['strength'] < .15 and e['harm'] == 0
                changed = True
        stamp = digest([(e['id'], e['source']) for e in state['episodes']])
        if stamp != state['consolidated_digest']:
            groups = {}
            for e in state['episodes']:
                k = canonical([e['context'], e['preferred']])
                row = groups.setdefault(k, dict(context=e['context'], preference=e['preferred'],
                    observations=0, protection_events=0, sources=[]))
                row['observations'] += 1
                row['protection_events'] += int(e['actual_action'] == 'protect')
                row['sources'].append(e['source'])
            state['summaries'] = list(groups.values())
            episodes = state['episodes']
            # Structured rehearsal proposal, never upgraded to an observed fact.
            state['hypotheses'] = ([dict(kind='authored_hypothesis',
                text='Compare these two controller preferences under matched body conditions.',
                source_ids=[episodes[-2]['id'], episodes[-1]['id']], verified=False)] if len(episodes) >= 2 else [])
            state['self_models'].append(dict(version=len(state['self_models'])+1,
                evidence_digest=stamp, learned_contexts=len(state['predictors']),
                observations=len(episodes), error_ema=state['error_ema'],
                scope='versioned software capability summary; no identity rewrite'))
            state['consolidated_digest'] = stamp
            changed = True
        if changed:
            self._save(state)
        return dict(enabled=True, changed=changed, summaries=deepcopy(state['summaries']),
                    hypotheses=deepcopy(state['hypotheses']), self_models=deepcopy(state['self_models']))
