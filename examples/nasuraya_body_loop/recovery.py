"""Bounded, local recovery controller using the same public body-tool contract.

No model/network call, elapsed-time healing, new action grant or body reset.
The task is one native walk cycle after recovery, not a claim of physical work.
"""
import json
import math


def recovery_ready_fixture():
    """Explicit near-threshold test body; never applied to an existing session."""
    from synthetic_fixture import synthetic_origin
    from unified_body_v2 import PersistentEmbodiment, UnifiedBody
    owner = PersistentEmbodiment.restore(synthetic_origin())
    before = owner.body()
    owner.aux['sleep_pressure'] = .6501
    owner._record(before, owner.body(), 'external_input',
                  'declared near-threshold recovery fixture, not a recovered user body', 0.)
    body = UnifiedBody.migrate(owner.checkpoint())
    body.migration['fixture_intervention'] = 'explicit initial sleep pressure .6501 for bounded recovery tests'
    return body


def recommended_action(minimum_state):
    """A policy proposal; the decision core and native body retain final say."""
    values = []
    for name in ('sleep_pressure', 'fatigue'):
        value = minimum_state[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('finite normalized recovery observation required')
        values.append(value)
    sleep, fatigue = values
    return 'sleep' if sleep > .65 else 'rest' if fatigue > .45 else 'walk'


def recovery_status(host):
    """Derive progress from committed body receipts, including after restart."""
    from .host import UnifiedBody, executed_body
    from reflection_cycle import canonical
    key = 'body-recovery-goal/' + host.run_id
    contract = dict(schema='nasuraya-recovery-goal/1', run_id=host.run_id,
                    goal='recover, then execute one native walk cycle',
                    scope='generated software body; local controller, no model invocation')
    encoded = canonical(contract)
    row = host.loop.engine.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    if row is not None and row[0] != encoded:
        raise ValueError('conflicting recovery goal')
    if row is None:
        host.loop.engine.db.execute('INSERT INTO meta VALUES(?,?)', (key, encoded))
    rows = host.loop.engine.db.execute('''SELECT d.record FROM body_api_run_calls r
        JOIN body_api_calls c ON c.identity=r.identity
        JOIN decisions d ON d.id='body-api-' || c.identity
        WHERE r.run_id=? AND c.tool='request_body_action' ORDER BY d.rowid''', (host.run_id,))
    actions, returned = [], False
    for row in rows:
        record = json.loads(row[0])
        if not executed_body(record):
            continue
        actual = record['actual_outcome']
        actions.append(actual['selected_action'])
        if actual['selected_action'] == 'walk':
            state = UnifiedBody.restore(actual['body_checkpoint']).owner.body()['minimum_state']
            returned |= recommended_action(state) == 'walk'
    minimum = host.snapshot()['minimum_state']
    return dict(goal=contract['goal'], completed=returned, actions=actions,
                next_recommendation=recommended_action(minimum),
                sleep_pressure=minimum['sleep_pressure'], fatigue=minimum['fatigue'],
                pending_recovery=not returned and recommended_action(minimum) != 'walk')


def recovery_step(host):
    """At most one action, fresh observation, existing budgets and durable IDs."""
    status = recovery_status(host)
    evaluation = host.evaluate()
    if evaluation['unresolved'] or not evaluation['safe']:
        raise ValueError('reconcile unresolved or failed work before recovery')
    if host.mode != 'bounded' or evaluation['goal_reached'] or evaluation['run_actions_remaining'] <= 0 or evaluation['tool_calls_remaining'] < 3:
        return dict(executed=False, recovery=status, evaluation=evaluation)
    index = host.run_progress()['actions_reserved'] + 1
    session, turn = 'local-recovery-' + host.run_id, 'local-recovery-turn'

    def invoke(name, args=None):
        result = host.handle_required(session, dict(type='function_call', name=name,
            call_id=f'recovery-{index}-{name}', turn_id=turn, arguments=args or {}))
        if not result['success']:
            raise ValueError('recovery tool request rejected')
        return json.loads(result['output'])

    before = invoke('observe_body')
    proposed = recommended_action(before['minimum_state'])
    receipt = invoke('request_body_action', dict(action=proposed, duration_s=1.,
        observed_checkpoint_sha256=before['checkpoint_sha256']))
    evaluation = invoke('evaluate_body')
    return dict(executed=True, proposed_action=proposed, receipt=receipt,
                recovery=recovery_status(host), evaluation=evaluation)
