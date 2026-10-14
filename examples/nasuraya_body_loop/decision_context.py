"""Trusted, reduced next-step context from the saved goal and current body."""
import json
from reflection_cycle import canonical
from .host import executed_body
from .recovery import recommended_action


def context(host):
    e=host.evaluate()
    b=host.snapshot()
    values=b['minimum_state']
    db=host.loop.engine.db
    transport=None
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='body_api_transport'").fetchone():
        transport=db.execute('SELECT state,session_id,terminal_status FROM body_api_transport WHERE run_id=?',
                             (host.run_id,)).fetchone()
    transport_unknown=bool(transport and transport['session_id'] is None)
    transport_blocked=bool(transport and transport['state'] in ('failed','deleted')
                           and transport['terminal_status']!='completed')
    preference = recommended_action(values)
    reason = {'sleep': 'sleep_pressure_high', 'rest': 'fatigue_high',
              'walk': 'fixed_motion_thresholds_clear'}[preference]
    if transport_unknown:
        step,reason='stop','api_creation_outcome_unknown'
    elif transport_blocked:
        step,reason='stop','api_transport_needs_host_review'
    elif not e['safe']:
        step,reason='stop','unresolved_or_failed_effect'
    elif e['goal_reached']:
        step,reason='stop','saved_goal_complete'
    elif e['tool_calls_remaining']==0:
        step,reason='stop','tool_budget_empty'
    elif e['completed_cycles']>=host.target_cycles:
        step,reason='evaluate_body','cycles_complete_evaluation_pending'
    elif e['run_actions_remaining']==0:
        step,reason='stop','action_budget_empty'
    else:
        step='observe_then_evaluate_then_request'
    return dict(schema='nasuraya-next-decision/1',run_id=host.run_id,
        goal_source='body_api_runs/contract',target_cycles=host.target_cycles,
        completed_cycles=e['completed_cycles'],cycles_remaining=max(0,host.target_cycles-e['completed_cycles']),
        run_actions_remaining=e['run_actions_remaining'],tool_calls_remaining=e['tool_calls_remaining'],
        safe=e['safe'] and not transport_unknown and not transport_blocked,
        goal_reached=e['goal_reached'] and not transport_unknown,next_step=step,
        preferred_action=preference,reason_code=reason,reason_scope='host fixed rule; not model hidden reasoning',
        body=dict(revision=b['revision'],checkpoint_sha256=b['checkpoint_sha256'],values=values))


def save_intent(host,identity,decision_id,model_preference,before):
    db=host.loop.engine.db
    value=before|dict(decision_id=decision_id,model_preference=model_preference)
    with host.loop.engine.transaction():
        db.execute('''CREATE TABLE IF NOT EXISTS body_api_intents(
            identity TEXT PRIMARY KEY,run_id TEXT NOT NULL,intent TEXT NOT NULL)''')
        row=db.execute('SELECT intent FROM body_api_intents WHERE identity=?',(identity,)).fetchone()
        if row and row[0]!=canonical(value):
            raise ValueError('conflicting saved action intent')
        db.execute('INSERT OR IGNORE INTO body_api_intents VALUES(?,?,?)',(identity,host.run_id,canonical(value)))


def records(loop,run_id):
    db=loop.engine.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='body_api_intents'").fetchone():return []
    rows=[]
    for r in db.execute('SELECT intent FROM body_api_intents WHERE run_id=? ORDER BY rowid',(run_id,)):
        intent=json.loads(r[0]);decision=loop.engine.get(intent['decision_id'])
        complete=decision is not None and executed_body(decision)
        state='complete' if complete else 'failed' if decision and decision['status']=='complete' else 'unresolved'
        reasons=[]
        if complete:
            if decision['selected_action']!=intent['model_preference']:
                penalized=any(o['action_id']==intent['model_preference'] and o.get('memory_penalty',0)>0
                              for o in decision['options'])
                reasons.append('verified_feedback_penalty' if penalized else 'core_selection')
            if decision['actual_outcome']['selected_action']!=decision['selected_action']:
                reasons.append('native_body_veto')
            if not reasons:reasons.append('requested_preference_executed')
        rows.append(dict(intent=intent,outcome_state=state,
            core_selected=decision['selected_action'] if complete else None,outcome_reason_codes=reasons,
            body_actual=decision['actual_outcome']['selected_action'] if complete else None,
            recalled_feedback_ids=decision['recalled_feedback_ids'] if complete else []))
    return rows
