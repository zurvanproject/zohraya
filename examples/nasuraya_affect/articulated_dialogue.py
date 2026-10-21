"""Caller-mediated affective dialogue -> one bounded articulated walking trial.

Each admitted trial starts from the existing controller's neutral fixture. This
is not persistent joint-state embodiment or an automatic chat listener. An
unknown execution is never repeated; measured outcomes can finish feedback.
"""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re

from examples.nasuraya_agent_loop.guided import _session_lock
from .engine import AffectiveAgent, canonical, digest, effective, validate_event, TENDENCIES

ROOT = Path(__file__).resolve().parents[2]
KEY = 'nasuraya-articulated-dialogue/1'


class Blocked(RuntimeError):
    pass


def provenance():
    paths = [Path(__file__), Path(__file__).with_name('engine.py'),
             ROOT/'runtimes/tadash_body/decision_core.py',
             ROOT/'examples/nasuraya_agent_loop/guided.py']
    paths += sorted((ROOT/'examples/nasuraya_research/articulated').glob('*.py'))
    paths += [ROOT/'assets/nasuraya_articulated_v02'/n for n in ('nasuraya.xml', 'robot.yaml')]
    return dict(files={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                packages={n: importlib.metadata.version(n) for n in ('numpy', 'scipy', 'mujoco', 'osqp', 'PyYAML')})


def choice(name):
    tendencies = dict.fromkeys(TENDENCIES, 0.)
    tendencies.update(explore=1.) if name == 'walk' else tendencies.update(verify=1., repair=1.)
    return dict(action=dict(id=name, consequences=[dict(probability=1., harm=.01, benefit=.5,
                cost=.01 if name == 'walk' else 0.)], respect=1., honesty=1., balance=1.,
                dignity=1., compassion=1., disharmony=0., evidence_confidence=1.), tendencies=tendencies)


def event_for(message):
    if not isinstance(message, dict) or set(message) != {'id', 'text', 'intent', 'appraisal', 'steps'}:
        raise ValueError('explicit id, text, intent, appraisal and steps required')
    if not isinstance(message['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,48}', message['id']):
        raise ValueError('bounded message ID required')
    if message['intent'] not in ('explore', 'walk', 'observe', 'reflect', 'stop'):
        raise ValueError('unsupported explicit intent')
    if type(message['steps']) is not int or message['steps'] not in (1, 2):
        raise ValueError('one or two requested steps required')
    return validate_event(dict(id='art-message:'+message['id'], context='nasuraya-articulated-dialogue',
        topic='embodied-task', summary=message['text'], cues=['body', 'dialogue', 'articulated'],
        source=dict(kind='authored', locator='caller-message://'+message['id']),
        elapsed_hours=0., appraisal=message['appraisal']))


def execute_trial(steps):
    from examples.nasuraya_research.articulated.stepping import walk_trial
    return walk_trial(label='dialogue-articulated', steps=steps)


def validate_measurement(result, requested):
    canonical(result)  # Reject non-finite values anywhere, including trace.
    if (type(result.get('walk_pass')) is not bool or result.get('requested_steps') != requested
            or type(result.get('accepted_steps')) is not int
            or not 0 <= result['accepted_steps'] <= requested
            or not isinstance(result.get('steps'), list)
            or not isinstance(result.get('trace'), list)):
        raise ValueError('invalid articulated measurement')
    landings = result['steps']
    if (len(landings) > requested or any(type(s.get('accepted')) is not bool for s in landings)
            or sum(s['accepted'] for s in landings) != result['accepted_steps']):
        raise ValueError('inconsistent measured landing counts')
    if result['walk_pass'] and (result['accepted_steps'] != requested or result.get('failure') is not None
            or result.get('nonfoot_ground_contacts') != [] or result.get('max_joint_limit_excess_rad', 1) > .02
            or result.get('max_motor_torque_fraction', 2) > 1.000001):
        raise ValueError('success contradicts controller acceptance')
    if type(result.get('simulated_seconds')) not in (float, int) or not 0 < result['simulated_seconds'] < 30:
        raise ValueError('invalid bounded trial duration')
    if len(result.get('pelvis_displacement_xyz_m', [])) != 3:
        raise ValueError('measured displacement required')
    return result


class ArticulatedDialogue:
    def __init__(self, affect):
        if not isinstance(affect, AffectiveAgent):
            raise ValueError('AffectiveAgent required')
        self.affect = affect
        self._load()

    @classmethod
    def enable(cls, affect):
        with _session_lock(affect.path):
            if affect.db.execute('SELECT 1 FROM meta WHERE key=?', (KEY,)).fetchone():
                raise Blocked('already enabled; budget cannot be reset')
            state = dict(schema=KEY, provenance=provenance(), enabled=True,
                         trials_remaining=1, messages={})
            with affect.transaction():
                affect.db.execute('INSERT INTO meta VALUES(?,?)',
                    (KEY, canonical(dict(value=state, sha256=digest(state)))))
        return cls(affect)

    def _load(self):
        row = self.affect.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if row is None:
            raise Blocked('explicit initialization required')
        envelope = json.loads(row[0]); state = envelope['value']
        if digest(state) != envelope['sha256'] or state['provenance'] != provenance():
            raise Blocked('source, model, dependency or state mismatch')
        return state

    def _save(self, state):
        with self.affect.transaction():
            self.affect.db.execute('UPDATE meta SET value=? WHERE key=?',
                (canonical(dict(value=state, sha256=digest(state))), KEY))

    def status(self):
        state = self._load()
        return dict(enabled=state['enabled'], trials_remaining=state['trials_remaining'],
            pending={k:v['stage'] for k,v in state['messages'].items() if v['stage'] != 'complete'},
            affect=effective(self.affect.state()),
            scope='One fresh articulated fixture trial; no continuous joint state or chat listener')

    def pause(self):
        with _session_lock(self.affect.path):
            state = self._load(); state['enabled'] = False; self._save(state)

    def _finish(self, state, identifier, replayed):
        item = state['messages'][identifier]; measured = item['measurement']
        validate_measurement(measured, item['message']['steps'])
        success = measured['walk_pass']
        appraisal = dict(item['event']['appraisal'])
        appraisal.update(goal_congruence=.7 if success else -.5, progress=1. if success else 0.,
                         novelty=0., relevance=1., certainty=1., loss=0.,
                         threat=0. if success else .5, norm_conflict=0.)
        feedback = dict(id='art-feedback:'+identifier, context=item['event']['context'], topic='embodied-task',
            summary=f"Articulated trial accepted {measured['accepted_steps']} of {measured['requested_steps']} steps; pass={success}",
            source=dict(kind='observed', locator='articulated-receipt://'+identifier+'/'+digest(measured)),
            cues=['body', 'dialogue', 'articulated'],
            elapsed_hours=(measured['simulated_seconds']+2.)/3600, appraisal=appraisal)
        receipt = self.affect.step(feedback, [choice('observe')])
        reply = (f"در شبیه‌ساز مفصلی، {measured['accepted_steps']} قدم پذیرفته‌شده برداشتم."
                 if success else f"آزمایش راه‌رفتن کامل نشد؛ {measured['accepted_steps']} قدم پذیرفته شد.")
        result = dict(message_id=identifier, plan=item['plan'], measurement=measured,
                      feedback_event_id=feedback['id'], affect_after=effective(receipt['state_after']),
                      reply_fa=reply, replayed=replayed, this_call_trials=0 if replayed else 1,
                      scope='Measured articulated fixture; feedback appraisal is authored; no physiological writeback')
        item.update(stage='complete', result=result)
        self._save(state)
        return deepcopy(result)

    def receive(self, message):
        event = event_for(message)
        with _session_lock(self.affect.path):
            state = self._load(); identifier = message['id']
            item = state['messages'].get(identifier)
            if item is not None:
                if canonical(item['message']) != canonical(message):
                    raise ValueError('conflicting message replay')
                if item['stage'] == 'complete':
                    return dict(deepcopy(item['result']), replayed=True, this_call_trials=0)
                if item['stage'] == 'executing':
                    raise Blocked('execution outcome unknown; no automatic repeat')
                if item['stage'] == 'measured':
                    return self._finish(state, identifier, True)
            else:
                # Stop remains possible when a prior trial is unresolved.
                if message['intent'] != 'stop' and any(v['stage'] != 'complete' for v in state['messages'].values()):
                    raise Blocked('resolve pending message first')
                if len(state['messages']) >= 32:
                    raise Blocked('message capacity reached; use pause command')
                if message['intent'] in ('explore', 'walk') and (not state['enabled'] or state['trials_remaining'] == 0):
                    raise Blocked('paused or trial budget exhausted')
                item = dict(message=deepcopy(message), event=event, stage='reserved')
                state['messages'][identifier] = item
                if message['intent'] == 'stop':
                    state['enabled'] = False
                self._save(state)
            if message['intent'] in ('explore', 'walk') and not state['enabled']:
                raise Blocked('paused before execution')
            options = [choice('walk')] if message['intent'] == 'walk' else [choice('observe')]
            if message['intent'] == 'explore':
                options.append(choice('walk'))
            planning = self.affect.step(item['event'], options)
            item['plan'] = planning['decision']
            if planning['decision']['selected_action'] != 'walk':
                result = dict(message_id=identifier, plan=item['plan'], measurement=None,
                    affect_after=effective(planning['state_after']), this_call_trials=0, replayed=False,
                    reply_fa='اتصال حرکتی متوقف شد.' if message['intent']=='stop' else 'پیام پردازش شد؛ آزمایش حرکتی اجرا نشد.')
                item.update(stage='complete', result=result); self._save(state)
                return deepcopy(result)
            if state['trials_remaining'] <= 0:
                raise Blocked('trial budget exhausted')
            # Persist both spend and unresolved barrier before any simulation.
            state['trials_remaining'] -= 1
            item['stage'] = 'executing'; self._save(state)
            measured = validate_measurement(execute_trial(message['steps']), message['steps'])
            item.update(stage='measured', measurement=measured)
            self._save(state)  # Full trace survives interruption before affect feedback.
            return self._finish(state, identifier, False)
