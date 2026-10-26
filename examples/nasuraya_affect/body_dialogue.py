"""Message -> affective plan -> native Tadash body -> measured dialogue receipt.

Load through dialogue_cli's verified worker. Intent/appraisal are supplied by
the conversational caller; there is no hidden NLP classifier or live model API.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re

from examples.nasuraya_body_loop.host import BodyLoop, executed_body, validate_duration
from examples.nasuraya_body_loop.experience import ExperienceController, KEY as EXPERIENCE_KEY
from examples.nasuraya_agent_loop.guided import _session_lock
from examples.nasuraya_research.native_snapshot import snapshot
from .engine import AffectiveAgent, canonical, digest, effective, validate_event, TENDENCIES

KEY = 'nasuraya-dialogue-body/1'


class BridgeBlocked(RuntimeError):
    pass


def source_hash():
    from examples.nasuraya_body_loop import host
    from examples.nasuraya_body_loop import experience
    from experiments.affect_api_20261023 import prediction_router, paired_comparison
    from examples.nasuraya_research import native_snapshot
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (Path(__file__), Path(host.__file__), Path(native_snapshot.__file__),
                             Path(experience.__file__), Path(prediction_router.__file__), Path(paired_comparison.__file__))})


def choice(name):
    tendencies = dict.fromkeys(TENDENCIES, 0.)
    if name == 'walk':
        tendencies['explore'] = 1.
    else:
        tendencies.update(verify=1., repair=1.)
    return dict(action=dict(id=name, consequences=[dict(probability=1., harm=.01,
                benefit=.5, cost=.01 if name == 'walk' else 0.)], respect=1., honesty=1.,
                balance=1., dignity=1., compassion=1., disharmony=0., evidence_confidence=1.),
                tendencies=tendencies)


def validate_message(message):
    if not isinstance(message, dict) or set(message) != {'id', 'text', 'intent', 'appraisal', 'duration_s'}:
        raise ValueError('explicit message, intent, appraisal and duration required')
    if not isinstance(message['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,48}', message['id']):
        raise ValueError('bounded message ID required')
    if message['intent'] not in ('explore', 'observe', 'reflect', 'stop'):
        raise ValueError('unknown intent; no automatic command inference')
    validate_duration(message['duration_s'])
    event = validate_event(dict(id='dialogue:'+message['id'], context='nasuraya-dialogue',
                topic='embodied-task', summary=message['text'], cues=['body', 'dialogue'],
                source=dict(kind='observed', locator='conversation://'+message['id']),
                elapsed_hours=0., appraisal=message['appraisal']))
    return event


class DialogueBodyBridge:
    def __init__(self, loop, affect):
        if not isinstance(loop, BodyLoop) or not isinstance(affect, AffectiveAgent):
            raise ValueError('native BodyLoop and separate AffectiveAgent required')
        self.loop, self.affect = loop, affect
        self._load()
        self.experience = ExperienceController(loop)

    @classmethod
    def enable(cls, loop, affect):
        if (loop.path.resolve() == affect.path.resolve() or loop.config['mode'] != 'bounded'
                or not 1 <= loop.config['max_actions'] <= 3):
            raise ValueError('separate stores and native bounded budget 1..3 required')
        binding = dict(body_path=str(loop.path.resolve()), affect_path=str(affect.path.resolve()),
                       initial_body=loop.config['initial_checkpoint_sha256'])
        state = dict(schema=KEY, source_hash=source_hash(), binding=binding,
                     enabled=True, intents={}, experience_integrated=True)
        # The native loop already owns an exclusive lock; always take affect second.
        with _session_lock(affect.path):
            if loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone():
                raise ValueError('bridge already enabled; resume without resetting')
            row = affect.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
            if row is not None and row[0] != canonical(binding):
                raise ValueError('affect ledger already bound to another body')
            if loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (EXPERIENCE_KEY,)).fetchone() is None:
                ExperienceController.enable(loop)
            else:
                ExperienceController(loop)  # Reuse, never reset prior memory/budget.
            with affect.transaction():
                affect.db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', (KEY, canonical(binding)))
            loop.engine.db.execute('INSERT INTO meta VALUES(?,?)',
                (KEY, canonical(dict(value=state, sha256=digest(state)))))
        return cls(loop, affect)

    def _load(self):
        import json
        row = self.loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if row is None:
            raise BridgeBlocked('explicit enable required')
        envelope = json.loads(row[0]); state = envelope['value']
        binding = dict(body_path=str(self.loop.path.resolve()), affect_path=str(self.affect.path.resolve()),
                       initial_body=self.loop.config['initial_checkpoint_sha256'])
        paired = self.affect.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if (digest(state) != envelope['sha256'] or state['source_hash'] != source_hash()
                or state['binding'] != binding or not paired or paired[0] != canonical(binding)):
            raise BridgeBlocked('bridge source or paired-ledger binding mismatch')
        return state

    def _save(self, state):
        self.loop.engine.db.execute('UPDATE meta SET value=? WHERE key=?',
            (canonical(dict(value=state, sha256=digest(state))), KEY))

    def resume(self):
        state = self._load(); state['enabled'] = True; self._save(state)

    def pause(self):
        # Always available, including when an earlier outcome is unresolved.
        state = self._load(); state['enabled'] = False; self._save(state)

    def status(self):
        state = self._load()
        return dict(enabled=state['enabled'], body=self.loop.status(),
                    affect=effective(self.affect.state()),
                    pending=[k for k,v in state['intents'].items() if v['result'] is None],
                    experience=self.experience.status()['state'],
                    connection='caller-mediated message bridge; no background listener',
                    body_kind='native UnifiedBody/Tadash, not articulated MuJoCo')

    def trace(self, identifier):
        """Recover a message -> memory -> decision -> forecast -> receipt chain."""
        state = self._load()
        intent = state['intents'].get(identifier)
        if intent is None:
            raise ValueError('unknown message id')
        result = intent['result']
        return dict(message=dict(id=identifier, text=intent['message']['text'], kind='caller_message',
                                 source='conversation://' + identifier),
                    appraisal_kind='caller_authored_interpretation',
                    recalled=deepcopy(intent.get('recalled', [])),
                    prior_body_memory=deepcopy(intent.get('body_memory', {})),
                    plan=deepcopy(intent.get('plan')), forecast=deepcopy(intent.get('forecast')),
                    result=deepcopy(result), status='completed' if result is not None else 'pending',
                    body_cycles_executed_by_trace=0)

    def recall(self, cues):
        with _session_lock(self.affect.path):
            return dict(records=self.affect.recall('nasuraya-dialogue', 'embodied-task', cues),
                        scope='source-attributed historical context; not permission or verified user beliefs',
                        body_cycles_executed=0)

    def _finish(self, state, identifier, *, replayed):
        intent = state['intents'][identifier]
        native = self.loop.engine.get(intent['native_id'])
        if native is None or native['status'] != 'complete':
            raise BridgeBlocked('native outcome unresolved; no automatic reexecution')
        request = native['request']; execution = request.get('execution', {})
        if ({k:v for k,v in request.items() if k != 'execution'} != intent['native_request']
                or execution.get('duration_s') != intent['message']['duration_s']
                or execution.get('external') != {}):
            raise BridgeBlocked('native receipt differs from reserved message plan')
        receipt = self.loop.receipt(native, replayed=replayed)
        ran = executed_body(native)
        matched = ran and receipt['actual_action'] == intent['preferred_action']
        checks = dict(intent['event']['appraisal'])
        checks.update(goal_congruence=.7 if matched else -.5, progress=.7 if matched else 0.,
                      novelty=0., relevance=1., certainty=1., loss=0.,
                      threat=0. if matched else .5, norm_conflict=0.)
        feedback = dict(id='body-feedback:'+identifier, context='nasuraya-dialogue', topic='embodied-task',
                        summary='Native body returned '+str(receipt['actual_action']),
                        source=dict(kind='observed', locator='native-decision://'+native['id']+'/'+digest(native)),
                        cues=['body', 'dialogue'], elapsed_hours=intent['message']['duration_s']/3600 if ran else 0.,
                        appraisal=checks)
        self.affect.step(feedback, [choice('observe')])
        experience = self.experience.complete_external(identifier, replayed=replayed)
        actual = receipt['actual_action']
        reply = ('بدن تجمیعی تداش یک چرخهٔ کوتاه راه‌رفتن اجرا کرد.' if actual == 'walk' else
                 'بدن تجمیعی تداش یک چرخهٔ مشاهده اجرا کرد.' if actual == 'observe' else
                 'محافظ بدن حرکت را نپذیرفت.' if actual == 'protect' else
                 'اجرای موفق بدن تأیید نشد.')
        result = dict(message_id=identifier, native_receipt=receipt,
                      plan=intent['plan'], restrictions=intent['restrictions'],
                      affect_after=effective(self.affect.state()), reply_fa=reply,
                      experience=experience, recalled=deepcopy(intent.get('recalled', [])),
                      provenance=dict(message='conversation://' + identifier,
                                      appraisal='caller_authored_interpretation',
                                      outcome=experience['prediction'].get('source')),
                      this_call_body_cycles=int(ran and not replayed), replayed=replayed,
                      scope='source-pinned native software body; not biological or articulated MuJoCo')
        intent['result'] = result
        if not ran:
            state['enabled'] = False
        self._save(state)
        return deepcopy(result)

    def receive(self, message):
        event = validate_message(message)
        with _session_lock(self.affect.path):
            state = self._load(); identifier = message['id']
            previous = state['intents'].get(identifier)
            if previous is not None:
                if canonical(previous['message']) != canonical(message):
                    raise ValueError('conflicting message replay')
                if previous['result'] is not None:
                    result = dict(deepcopy(previous['result']), replayed=True, this_call_body_cycles=0)
                    if result.get('native_receipt'):
                        result['native_receipt']['replayed'] = True
                    if result.get('experience'):
                        result['experience'].update(replayed=True, this_call_native_cycles=0)
                        result['experience']['native_receipt']['replayed'] = True
                    return result
                if previous.get('stage') == 'executing':
                    return self._finish(state, identifier, replayed=True)
            else:
                if any(v['result'] is None for v in state['intents'].values()):
                    raise BridgeBlocked('resume unresolved message first')
                if len(state['intents']) >= 32:
                    raise BridgeBlocked('bounded message capacity reached')
                motion = message['intent'] in ('explore', 'observe')
                if motion and (not state['enabled'] or self.loop.status()['actions_remaining'] <= 0):
                    raise BridgeBlocked('paused or persistent body budget exhausted')
                native_id = 'dialogue-body:'+identifier
                if self.loop.engine.get(native_id) is not None:
                    raise BridgeBlocked('native ID already owned by another request')
                observation = self.loop.observe()
                audit = snapshot(self.loop.body())['audit']
                checks = event['appraisal']
                restrictions = audit['walking_restrictions']
                body_memory = self.experience.preview(observation, message['duration_s'])
                if body_memory['memory_risk'] > .5:
                    restrictions = list(restrictions) + ['remembered_native_harm']
                if restrictions:
                    # Body-derived concern, not a claim about the user's emotion.
                    checks['threat'] = max(checks['threat'], .8)
                    checks['controllability'] = min(checks['controllability'], .3)
                choices = [choice('observe')]
                if (message['intent'] == 'explore' and audit['upper_controller_walk_guard_allows']
                        and body_memory['memory_risk'] <= .5):
                    choices.append(choice('walk'))
                previous = dict(message=deepcopy(message), event=event, choices=choices,
                                native_id=native_id, observation=observation,
                                restrictions=restrictions, body_memory=body_memory,
                                result=None, stage='reserved')
                state['intents'][identifier] = previous
                self._save(state)
            if message['intent'] in ('explore', 'observe') and not state['enabled']:
                raise BridgeBlocked('bridge paused before execution')
            plan = self.affect.step(previous['event'], previous['choices'])
            previous['plan'] = plan['decision']
            previous['recalled'] = plan['recalled']
            if message['intent'] in ('reflect', 'stop'):
                if message['intent'] == 'stop':
                    state['enabled'] = False
                result = dict(message_id=identifier, reply_fa='اتصال حرکتی متوقف شد.' if message['intent']=='stop' else 'پیام و ارزیابی تألیفی آن در حافظه ثبت شد.',
                              plan=plan['decision'], affect_after=effective(self.affect.state()),
                              native_receipt=None, this_call_body_cycles=0, replayed=False)
                previous['result'] = result; self._save(state)
                return result
            if self.loop.body().checkpoint()['sha256'] != previous['observation']['checkpoint_sha256']:
                raise BridgeBlocked('body changed after the message observation')
            preferred = plan['decision']['selected_action']
            if preferred not in ('walk', 'observe'):
                raise BridgeBlocked('no admitted body action')
            previous['preferred_action'] = preferred
            previous['native_request'] = self.loop.make_request(previous['native_id'],
                previous['observation'], message['duration_s'], preferred)
            previous['forecast'] = self.experience.reserve_external(identifier, previous['native_id'],
                previous['observation'], message['duration_s'], preferred)['prediction']
            previous['stage'] = 'executing'
            self._save(state)
            self.loop.observe()
            self.loop.step(decision_id=previous['native_id'], duration_s=message['duration_s'], preferred_action=preferred)
            return self._finish(state, identifier, replayed=False)
