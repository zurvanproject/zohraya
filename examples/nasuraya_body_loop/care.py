"""Finite body care with a source-derived memory between scheduled awakenings.

Policy thresholds are authored fixture heuristics. Existing decision/core/body
protection and durable receipts remain the authority over effects and learning.
"""
import json
import math

from reflection_cycle import canonical
from examples.nasuraya_agent_loop.local import ToolRejected
from .host import executed_body
from .api_host import digest


def plan(snapshot):
    state = snapshot['minimum_state']
    limits = {'sleep_pressure': .65, 'fatigue': .45, 'pain': .65}
    reasons = []
    for field, threshold in limits.items():
        value = state[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('finite fixture observation required')
        if value > threshold:
            reasons.append(field + '_high')
    hydration = state['hydration']
    if type(hydration) not in (int, float) or not math.isfinite(hydration):
        raise ValueError('finite fixture observation required')
    if hydration < .25:
        reasons.append('hydration_low')
    return dict(schema='nasuraya-fixture-care-policy/1', preferred_action='observe' if reasons else 'walk',
                reasons=reasons or ['fixture_motion_thresholds_clear'], duration_s=.1,
                scope='authored deterministic fixture policy; native guards retain control')


def episodes(loop, run_id):
    db = loop.engine.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_care_episodes'").fetchone():
        return []
    return [json.loads(row[0]) for row in db.execute(
        'SELECT memo FROM body_care_episodes WHERE run_id=? ORDER BY rowid', (run_id,))]


def reconcile(host):
    """Rebuild derived memos only from committed source records, never perform an action."""
    db = host.loop.engine.db
    rows = db.execute('''SELECT d.record FROM body_api_run_calls r
        JOIN body_api_calls c ON c.identity=r.identity
        JOIN decisions d ON d.id='body-api-' || c.identity
        WHERE r.run_id=? AND c.tool='request_body_action' ORDER BY d.rowid''', (host.run_id,))
    observations = []
    for row in db.execute('''SELECT c.result FROM body_api_calls c JOIN body_api_run_calls r
            ON r.identity=c.identity WHERE r.run_id=? AND c.tool='observe_body' AND c.status='complete' ''', (host.run_id,)):
        result = json.loads(row[0])
        if result['success']:
            observations.append(json.loads(result['output']))
    expected = []
    for row in rows:
        record = json.loads(row[0])
        if not executed_body(record):
            continue
        source = next(e for e in record['request']['evidence'] if e['id'] == 'body')
        before = next((s for s in observations if s['checkpoint_sha256'] == source['source_sha256']), None)
        if before is None:
            raise ValueError('committed care decision lacks its observed source')
        policy = plan(before)
        requested = max(record['request']['actions'], key=lambda a:a['score']['respect'])['id']
        if policy['preferred_action'] != requested:
            raise ValueError('care policy does not match saved request')
        receipt = host.loop.receipt(record, replayed=True)
        after = receipt['self_model_after']
        expected.append(dict(schema='nasuraya-care-episode/1', run_id=host.run_id,
            decision_id=record['id'], decision_sha256=digest(record),
            observed_before=before, observed_after=after,
            policy=policy, core_selected=receipt['requested_action'], body_actual=receipt['actual_action'],
            expected_outcome_matched=receipt['expected_outcome_matched'],
            recalled_feedback_ids=receipt['recalled_feedback_ids'],
            delta={key:after['minimum_state'][key]-value for key,value in before['minimum_state'].items()},
            evidence_scope='derived from stored observation and committed body receipt; not a new effect'))
    existing = episodes(host.loop, host.run_id)
    by_id = {memo['decision_id']:memo for memo in expected}
    if any(by_id.get(m['decision_id']) != m for m in existing):
        raise ValueError('care memory conflicts with committed source')
    if expected:
        with host.loop.engine.transaction():
            db.execute('''CREATE TABLE IF NOT EXISTS body_care_episodes(
                decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, memo TEXT NOT NULL)''')
            for memo in expected:
                db.execute('INSERT OR IGNORE INTO body_care_episodes VALUES(?,?,?)',
                           (memo['decision_id'],host.run_id,canonical(memo)))
    return episodes(host.loop, host.run_id)


def runner(host, contract, timeout_seconds):
    """One existing-grant action per awakening; yield unfinished goal to saved timer."""
    reconcile(host)
    if host.evaluate()['goal_reached']:
        return dict(status='completed', backend='care', live_api_verified=False)
    index = host.run_progress()['completed_cycles']
    def invoke(name, label, arguments=None):
        result = host.handle_required('care-' + host.run_id, dict(type='function_call',name=name,
            arguments=arguments or {},call_id=label+'-'+str(index),turn_id='care-turn'))
        if not result['success']:
            raise ToolRejected('fixture care request rejected')
        return json.loads(result['output'])
    snapshot = invoke('observe_body','observe')
    policy = plan(snapshot)
    invoke('evaluate_body','evaluate')
    invoke('request_body_action','action',dict(action=policy['preferred_action'],duration_s=policy['duration_s'],
           observed_checkpoint_sha256=snapshot['checkpoint_sha256']))
    reconcile(host)
    invoke('evaluate_body','finish')
    return dict(status='completed' if host.evaluate()['goal_reached'] else 'yielded',
                backend='care', live_api_verified=False)
