"""Finite execution bridge to the existing synthetic ToolHost.

Only in-memory workshop effects are executed. Host state and execution receipt
commit together; interrupted affect/feedback stages resume by their event IDs.
No shell, network, external callback or physical body is exposed to the planner.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from examples.nasuraya_agent_loop import local, guided
from examples.nasuraya_agent_loop.guided import _session_lock
from .engine import AffectiveAgent, CHECKS, TENDENCIES, canonical, digest, effective

KEY = 'nasuraya-affective-workshop/1'
TOOLS = {'process_job': ('process_job', {}),
         **{f'recover_{n}': ('recover', {'ticks': n}) for n in (1, 2, 3)}}


def fingerprint():
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (Path(__file__), Path(local.__file__), Path(guided.__file__))})


def encode_host(host):
    return dict(state=asdict(host.state), actions_used=host.actions_used,
                max_actions=host.max_actions, mode=host.mode,
                observed=host.observed, events=host.journal.events)


def decode_host(value):
    host = local.ToolHost(local.State(**value['state']), local.Journal(),
                          max_actions=value['max_actions'], mode=value['mode'])
    host.journal.events = deepcopy(value['events'])
    host.actions_used = value['actions_used']
    host.observed = value['observed']
    mutations = [e for e in host.journal.events if e['kind'] == 'tool_result'
                 and e['name'] in ('recover', 'process_job')]
    if (type(host.actions_used) is not int or host.actions_used != len(mutations)
            or not 0 <= host.actions_used <= host.max_actions
            or type(host.observed) is not bool
            or [e['seq'] for e in host.journal.events] != list(range(1, len(host.journal.events)+1))):
        raise ValueError('invalid workshop checkpoint')
    expected = mutations[-1]['after'] if mutations else host.journal.events[0]['initial_state']
    if expected != asdict(host.state):
        raise ValueError('workshop state differs from its last outcome')
    return host


def appraisal(identifier, state, *, receipt=None):
    """Engineering interpretation of measured workshop data, not a text reader."""
    blocked = state.energy < 35 or state.heat > 65
    checks = dict.fromkeys(CHECKS, 0.)
    checks.update(relevance=1., certainty=1., controllability=.7,
                  goal_congruence=-.8 if blocked else .3,
                  threat=max(0., (state.heat-65)/35, (35-state.energy)/35))
    source_value = asdict(state)
    if receipt is not None:
        source_value = receipt
        gained = receipt['after']['completed_jobs']-receipt['before']['completed_jobs']
        recovered = receipt['tool'] == 'recover'
        checks.update(goal_congruence=.8 if gained else (.5 if recovered else 0.),
                      progress=min(1., gained*.7 + float(recovered)*.2),
                      threat=0.)
    return dict(id=identifier, context='synthetic-workshop', topic='bounded-task',
                summary=('Measured tool outcome: ' + receipt['action_id'] if receipt else
                         'Measured workshop resources and remaining jobs'),
                source=dict(kind='observed', locator='workshop-state://sha256/'+digest(source_value)),
                cues=['workshop', 'resources', 'completion'], elapsed_hours=0.,
                appraisal=checks)


def candidates(host):
    """Use dry-run native tool validation, not caller-declared tool safety."""
    options = []
    sufficient_recovery = None
    for action_id, (tool, arguments) in TOOLS.items():
        trial = local.ToolHost(host.state, local.Journal(), mode=host.mode,
                               max_actions=host.max_actions)
        trial.actions_used = host.actions_used
        trial.call('observe_state', {})
        try:
            trial.call(tool, arguments)
        except local.ToolRejected:
            continue
        # Reject outcomes outside native success-safety bounds, even for recovery.
        if not local.evaluate(trial.state)['safe']:
            continue
        job = tool == 'process_job'
        ticks = arguments.get('ticks', 1)
        if not job:
            if sufficient_recovery is not None and ticks > sufficient_recovery:
                continue
            # Stop offering longer recovery once a shorter one permits all
            # remaining jobs. Native tools supply the transition/guard rules.
            lookahead = local.ToolHost(trial.state, local.Journal(), max_actions=100)
            try:
                for _ in range(trial.state.pending_jobs):
                    lookahead.call('observe_state', {})
                    lookahead.call('process_job', {})
            except local.ToolRejected:
                pass
            else:
                if local.evaluate(lookahead.state)['goal_reached']:
                    sufficient_recovery = ticks
        tendency = dict.fromkeys(TENDENCIES, 0.)
        tendency['consolidate' if job else 'repair'] = 1. if job else ticks/3
        options.append(dict(action=dict(id=action_id, consequences=[dict(
            probability=1., harm=0., benefit=1. if job else 0., cost=.1 if job else .015*ticks)],
            respect=1., honesty=1., balance=1., dignity=1., compassion=1.,
            disharmony=0., evidence_confidence=1.), tendencies=tendency))
    return options


def feedback_option():
    return [dict(action=dict(id='retain_outcome', consequences=[dict(probability=1., harm=0.)],
                             respect=1., honesty=1., balance=1., dignity=1., compassion=1.,
                             disharmony=0., evidence_confidence=1.),
                 tendencies=dict.fromkeys(TENDENCIES, 0.))]


class AffectiveWorkshop:
    def __init__(self, agent):
        self.agent = agent
        self._load()

    @classmethod
    def attach(cls, agent, state=None, *, max_actions=12, mode='bounded', use_affect=True):
        if type(use_affect) is not bool:
            raise ValueError('explicit affect switch required')
        host = local.ToolHost(state or local.State(), local.Journal(),
                              max_actions=max_actions, mode=mode)
        host.journal.emit('run_started', initial_state=asdict(host.state),
                          backend='affective-native-core', max_actions=max_actions, mode=mode)
        value = dict(schema=KEY, source_sha256=fingerprint(), host=encode_host(host),
                     use_affect=use_affect, pending=None, receipts={})
        with _session_lock(agent.path), agent.transaction():
            agent.db.execute('INSERT INTO meta VALUES(?,?)',
                             (KEY, canonical(dict(value=value, sha256=digest(value)))))
        return cls(agent)

    def _load(self):
        row = self.agent.db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if row is None:
            raise ValueError('explicit workshop attachment required')
        envelope = json.loads(row[0])
        value = envelope['value']
        if (digest(value) != envelope['sha256'] or value['schema'] != KEY
                or value['source_sha256'] != fingerprint()):
            raise ValueError('workshop source or integrity mismatch')
        decode_host(value['host'])
        return value

    def _save(self, value):
        with self.agent.transaction():
            self.agent.db.execute('UPDATE meta SET value=? WHERE key=?',
                                  (canonical(dict(value=value, sha256=digest(value))), KEY))

    def status(self):
        value = self._load()
        host = decode_host(value['host'])
        return dict(state=asdict(host.state), evaluation=local.evaluate(host.state),
                    actions_used=host.actions_used, actions_remaining=host.max_actions-host.actions_used,
                    pending=value['pending']['id'] if value['pending'] else None,
                    mode=host.mode, use_affect=value['use_affect'],
                    affect=effective(self.agent.state()), scope='synthetic_workshop_only')

    def _feedback(self, value):
        pending = value['pending']
        receipt = value['receipts'][pending['id']]
        event = appraisal('workshop:'+pending['id']+':outcome',
                          local.State(**receipt['after']), receipt=receipt)
        self.agent.step(event, feedback_option(), use_affect=value['use_affect'],
                        use_memory=value['use_affect'])
        value['pending'] = None
        self._save(value)

    def step(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', request_id):
            raise ValueError('bounded request ID required')
        with _session_lock(self.agent.path):
            value = self._load()
            pending = value['pending']
            if pending and pending['id'] != request_id:
                raise ValueError('resume pending request before starting another')
            if request_id in value['receipts']:
                if pending:
                    self._feedback(value)
                return dict(value['receipts'][request_id], replayed=True, this_call_actions=0)
            host = decode_host(value['host'])
            if pending is None:
                if local.evaluate(host.state)['goal_reached']:
                    raise ValueError('goal already reached')
                if host.mode != 'bounded':
                    raise ValueError('mutation disabled in observe mode')
                if host.actions_used >= host.max_actions:
                    raise ValueError('persistent action budget exhausted')
                choices = candidates(host)
                if not choices:
                    raise ValueError('no safe native tool candidate')
                pending = dict(id=request_id, host_sha256=digest(value['host']),
                               event=appraisal('workshop:'+request_id+':appraisal', host.state),
                               options=choices)
                value['pending'] = pending
                self._save(value)  # reservation precedes planning and execution
            plan = self.agent.step(pending['event'], pending['options'],
                                   use_affect=value['use_affect'], use_memory=value['use_affect'])
            selected = plan['decision']['selected_action']
            if selected not in {o['action']['id'] for o in pending['options']}:
                raise ValueError('planner did not select an admitted tool')
            if digest(value['host']) != pending['host_sha256']:
                raise ValueError('stale host observation')
            tool, arguments = TOOLS[selected]
            before = asdict(host.state)
            host.call('observe_state', {})
            host.journal.emit('action_selected', request_id=request_id, name=tool,
                              arguments=arguments, selection_source='native_core_with_affect',
                              baseline_action=plan['decision']['baseline_selected_action'])
            host.call(tool, arguments)  # actual native execution on the checkpoint clone
            measured = host.call('evaluate_state', {})
            receipt = dict(request_id=request_id, action_id=selected, tool=tool,
                           arguments=arguments, before=before, after=asdict(host.state),
                           evaluation=measured, actions_used=host.actions_used,
                           baseline_action=plan['decision']['baseline_selected_action'],
                           planning_event=plan['event']['id'])
            value['host'] = encode_host(host)
            value['receipts'][request_id] = receipt
            # This is the commit boundary for ALL effects: only simulated state.
            self._save(value)
            self._feedback(value)
            return dict(receipt, replayed=False, this_call_actions=1)

    def run(self, max_steps=12):
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValueError('finite run length 1..100 required')
        receipts = []
        for _ in range(max_steps):
            status = self.status()
            if status['evaluation']['goal_reached'] and not status['pending']:
                break
            if not status['actions_remaining'] and not status['pending']:
                break
            value = self._load()
            if value['pending']:
                identifier = value['pending']['id']
            else:
                index = len(value['receipts'])+1
                identifier = f'step-{index}'
                while identifier in value['receipts']:
                    index += 1
                    identifier = f'step-{index}'
            receipts.append(self.step(identifier))
        status = self.status()
        return dict(status='completed' if status['evaluation']['goal_reached'] else 'bounded_stop',
                    receipts=receipts, final=status, model_api_calls=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'status', 'step', 'run'))
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--energy', type=int, default=45)
    parser.add_argument('--heat', type=int, default=50)
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--max-actions', type=int, default=12)
    parser.add_argument('--max-steps', type=int, default=12)
    parser.add_argument('--mode', choices=('observe', 'bounded'), default='bounded')
    parser.add_argument('--without-affect', action='store_true')
    parser.add_argument('--request-id')
    args = parser.parse_args()
    if args.command != 'init' and not args.db.exists():
        parser.error('initialize workshop explicitly')
    if args.command == 'step' and not args.request_id:
        parser.error('step requires --request-id')
    with AffectiveAgent(args.db) as agent:
        workshop = (AffectiveWorkshop.attach(agent, local.State(args.energy, args.heat, args.jobs),
                    max_actions=args.max_actions, mode=args.mode, use_affect=not args.without_affect)
                    if args.command == 'init' else AffectiveWorkshop(agent))
        result = (workshop.run(args.max_steps) if args.command == 'run' else
                  workshop.step(args.request_id) if args.command == 'step' else workshop.status())
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
