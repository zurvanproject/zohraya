"""Opt-in goal gate: self-knowledge can pause a tick, never override the body."""
from .monitor import snapshot


def step_goal(model,journal):
    goal=journal.load()
    request=goal.request()
    report=model.inspect(snapshot(goal.body),request)
    if report['recommendation']!='continue_with_native_guards':
        return dict(executed=False,self_report=report)
    model.begin(goal.body,request)
    receipt=journal.step(event_id=request['event_id'],expected_head=goal.checkpoint()['sha256'])
    result=model.finish(request['event_id'],journal.load().body,receipt)
    return dict(executed=True,self_report=report,verified_result=result)


def reconcile_goal(model,journal):
    """Read only an existing native receipt for a pending prediction."""
    state=model.verify()
    if not state['pending']:return dict(status='clean')
    event=state['pending'][0]
    goal=journal.load()  # may reconcile a durable local outcome, never a tick
    receipt=goal.body.results.get(event)
    if receipt is None:raise ValueError('native outcome unknown; no automatic action replay')
    result=model.finish(event,goal.body,receipt)
    return dict(status='reconciled',result=result,native_actions_executed=0)
